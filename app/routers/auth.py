from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext
from app.config import settings
import app.database as db

router = APIRouter(prefix="/api/auth", tags=["Autentikasi"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_access_token(umkm_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    data = {"sub": umkm_id, "exp": expire}
    return jwt.encode(data, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _umkm_to_profile(u: dict) -> dict:
    return {
        "id": u["id"],
        "nama_pemilik": u["nama_pemilik"],
        "email": u["email"],
        "nama_usaha": u["nama_usaha"],
        "alamat": u.get("alamat"),
        "kategori": u.get("kategori"),
        "deskripsi": u.get("deskripsi"),
        "nomor_stand": u.get("nomor_stand"),
        "zona": u.get("zona"),
        "status_pendaftaran": u["status_pendaftaran"],
        "created_at": u["created_at"],
    }


# ── POST /api/auth/login ──────────────────────────────────────
@router.post("/login")
async def login(body: dict):
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        raise HTTPException(422, detail={"status": "error", "message": "Field email dan password wajib diisi"})

    resp = db.supabase.table("umkm").select("*").eq("email", email).maybe_single().execute()
    if not resp.data:
        raise HTTPException(401, detail={"status": "error", "message": "Email atau password salah"})

    umkm = resp.data
    if not pwd_context.verify(password, umkm["password_hash"]):
        raise HTTPException(401, detail={"status": "error", "message": "Email atau password salah"})

    status = umkm["status_pendaftaran"]
    if status == "pending":
        raise HTTPException(403, detail={"status": "error", "message": "Pendaftaran kamu sedang diproses. Tunggu konfirmasi admin."})
    if status == "rejected":
        raise HTTPException(403, detail={"status": "error", "message": "Pendaftaran kamu ditolak. Silakan hubungi admin."})

    token = create_access_token(umkm["id"])
    return {
        "status": "success",
        "message": "Login berhasil",
        "data": {
            "token": token,
            "user": _umkm_to_profile(umkm),
        },
    }


# ── POST /api/auth/register ───────────────────────────────────
@router.post("/register", status_code=201)
async def register(
    nama_pemilik: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    nama_usaha: str = Form(...),
    alamat: str = Form(""),
    kategori: str = Form(...),
    deskripsi: Optional[str] = Form(None),
    kios_id: str = Form(...),
    setuju: bool = Form(...),
    file_ktp: UploadFile = File(...),
    file_nib: UploadFile = File(...),
):
    # Validasi
    if not setuju:
        raise HTTPException(422, detail={"status": "error", "message": "Anda harus menyetujui syarat & ketentuan"})
    if len(password) < 6:
        raise HTTPException(422, detail={"status": "error", "message": "Password minimal 6 karakter"})

    # Cek email duplikat
    existing_email = db.supabase.table("umkm").select("id").eq("email", email).maybe_single().execute()
    if existing_email.data:
        raise HTTPException(409, detail={"status": "error", "message": "Email sudah terdaftar. Silakan login atau gunakan email lain."})

    # Cek kios sudah diambil (approved saja yang terkunci, pending bisa bentrok)
    existing_kios = (
        db.supabase.table("umkm")
        .select("id")
        .eq("nomor_stand", kios_id)
        .neq("status_pendaftaran", "rejected")
        .maybe_single()
        .execute()
    )
    if existing_kios.data:
        raise HTTPException(409, detail={"status": "error", "message": f"Kios {kios_id} sudah dipilih oleh pendaftar lain. Silakan pilih kios lain."})

    # Upload dokumen ke Supabase Storage
    ktp_url = await _upload_file(file_ktp, settings.STORAGE_BUCKET_DOKUMEN, f"ktp/{email}_{file_ktp.filename}")
    nib_url = await _upload_file(file_nib, settings.STORAGE_BUCKET_DOKUMEN, f"nib/{email}_{file_nib.filename}")

    password_hash = pwd_context.hash(password)
    zona = _kategori_to_zona(kategori)

    new_umkm = {
        "nama_pemilik": nama_pemilik,
        "email": email,
        "password_hash": password_hash,
        "nama_usaha": nama_usaha,
        "alamat": alamat,
        "kategori": kategori,
        "deskripsi": deskripsi,
        "nomor_stand": kios_id,
        "zona": zona,
        "status_pendaftaran": "pending",
        "file_ktp_url": ktp_url,
        "file_nib_url": nib_url,
    }

    resp = db.supabase.table("umkm").insert(new_umkm).execute()
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal menyimpan data. Coba lagi."})

    return {
        "status": "success",
        "message": "Pendaftaran berhasil! Menunggu konfirmasi admin.",
        "data": _umkm_to_profile(resp.data[0]),
    }


# ── GET /api/auth/status ──────────────────────────────────────
@router.get("/status")
async def check_status(email: str):
    if not email:
        raise HTTPException(422, detail={"status": "error", "message": "Parameter email wajib diisi"})

    resp = db.supabase.table("umkm").select("email, status_pendaftaran, nama_usaha").eq("email", email).maybe_single().execute()
    if not resp.data:
        raise HTTPException(404, detail={"status": "error", "message": "Email tidak ditemukan"})

    return {
        "status": "success",
        "data": {
            "email": resp.data["email"],
            "status_pendaftaran": resp.data["status_pendaftaran"],
            "nama_usaha": resp.data["nama_usaha"],
        },
    }


# ── Helpers ───────────────────────────────────────────────────

async def _upload_file(upload: UploadFile, bucket: str, path: str) -> Optional[str]:
    """Upload file ke Supabase Storage. Return public/signed URL atau None jika gagal."""
    try:
        content = await upload.read()
        content_type = upload.content_type or "application/octet-stream"
        db.supabase.storage.from_(bucket).upload(path, content, {"content-type": content_type, "upsert": "true"})
        # Untuk bucket private, gunakan signed URL. Untuk public, gunakan public URL.
        url = db.supabase.storage.from_(bucket).get_public_url(path)
        return url
    except Exception:
        # Jika storage belum dikonfigurasi, simpan saja nama file
        return upload.filename


def _kategori_to_zona(kategori: str) -> str:
    mapping = {
        "Kuliner": "Kuliner",
        "Fashion": "Fashion & Aksesoris",
        "Kerajinan": "Kerajinan & Seni",
        "Lainnya": "Umum",
    }
    return mapping.get(kategori, "Umum")
