from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext
from app.config import settings
import app.database as db
import asyncio
import logging

router = APIRouter(prefix="/api/auth", tags=["Autentikasi"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)


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
    setuju: str = Form(...),
    file_ktp: UploadFile = File(...),
    file_nib: UploadFile = File(...),
):
    try:
        # FIX: konversi setuju manual
        setuju_bool = setuju.lower() in ("true", "1", "yes", "on")
        if not setuju_bool:
            raise HTTPException(422, detail={"status": "error", "message": "Anda harus menyetujui syarat & ketentuan"})
        if len(password) < 6:
            raise HTTPException(422, detail={"status": "error", "message": "Password minimal 6 karakter"})

        loop = asyncio.get_event_loop()

        # FIX: semua DB call sync → run_in_executor agar tidak block event loop
        def _check_email():
            return db.supabase.table("umkm").select("id").eq("email", email).maybe_single().execute()

        def _check_kios():
            return (
                db.supabase.table("umkm")
                .select("id")
                .eq("nomor_stand", kios_id)
                .neq("status_pendaftaran", "rejected")
                .maybe_single()
                .execute()
            )

        try:
            existing_email = await asyncio.wait_for(loop.run_in_executor(None, _check_email), timeout=10)
        except asyncio.TimeoutError:
            raise HTTPException(503, detail={"status": "error", "message": "Database timeout, coba lagi."})

        if existing_email.data:
            raise HTTPException(409, detail={"status": "error", "message": "Email sudah terdaftar. Silakan login atau gunakan email lain."})

        try:
            existing_kios = await asyncio.wait_for(loop.run_in_executor(None, _check_kios), timeout=10)
        except asyncio.TimeoutError:
            raise HTTPException(503, detail={"status": "error", "message": "Database timeout, coba lagi."})

        if existing_kios.data:
            raise HTTPException(409, detail={"status": "error", "message": f"Kios {kios_id} sudah dipilih oleh pendaftar lain. Silakan pilih kios lain."})

        # Baca file async
        ktp_content = await file_ktp.read()
        nib_content = await file_nib.read()
        ktp_filename = file_ktp.filename or "ktp.jpg"
        nib_filename = file_nib.filename or "nib.jpg"
        ktp_content_type = file_ktp.content_type or "application/octet-stream"
        nib_content_type = file_nib.content_type or "application/octet-stream"

        def _upload_ktp() -> Optional[str]:
            return _upload_sync(ktp_content, ktp_content_type, settings.STORAGE_BUCKET_DOKUMEN, f"ktp/{email}_{ktp_filename}", ktp_filename)

        def _upload_nib() -> Optional[str]:
            return _upload_sync(nib_content, nib_content_type, settings.STORAGE_BUCKET_DOKUMEN, f"nib/{email}_{nib_filename}", nib_filename)

        try:
            ktp_url = await asyncio.wait_for(loop.run_in_executor(None, _upload_ktp), timeout=15.0)
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"Upload KTP gagal ({e}) — fallback ke nama file")
            ktp_url = ktp_filename

        try:
            nib_url = await asyncio.wait_for(loop.run_in_executor(None, _upload_nib), timeout=15.0)
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"Upload NIB gagal ({e}) — fallback ke nama file")
            nib_url = nib_filename

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

        def _insert():
            return db.supabase.table("umkm").insert(new_umkm).execute()

        try:
            resp = await asyncio.wait_for(loop.run_in_executor(None, _insert), timeout=10)
        except asyncio.TimeoutError:
            raise HTTPException(503, detail={"status": "error", "message": "Database timeout saat menyimpan data."})
        except Exception as e:
            logger.error(f"DB insert gagal: {e}")
            raise HTTPException(500, detail={"status": "error", "message": "Gagal menyimpan data. Coba lagi."})

        if not resp.data:
            raise HTTPException(500, detail={"status": "error", "message": "Gagal menyimpan data. Coba lagi."})

        return {
            "status": "success",
            "message": "Pendaftaran berhasil! Menunggu konfirmasi admin.",
            "data": _umkm_to_profile(resp.data[0]),
        }

    except HTTPException:
        raise
    except asyncio.CancelledError:
        logger.warning("Register request cancelled by client/server")
        raise HTTPException(503, detail={"status": "error", "message": "Request dibatalkan, coba lagi."})
    except BaseException as e:
        logger.error(f"Unexpected error in register: {e}", exc_info=True)
        raise HTTPException(500, detail={"status": "error", "message": "Terjadi kesalahan pada server. Silakan coba lagi."})


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

def _upload_sync(
    content: bytes,
    content_type: str,
    bucket: str,
    path: str,
    fallback_name: str,
) -> Optional[str]:
    """
    Upload file ke Supabase Storage — SYNC, dimaksudkan untuk dipanggil via run_in_executor.
    Return public URL atau fallback_name jika gagal.
    """
    try:
        db.supabase.storage.from_(bucket).upload(
            path, content,
            {"content-type": content_type, "upsert": "true"},
        )
        return db.supabase.storage.from_(bucket).get_public_url(path)
    except Exception as e:
        logger.warning(f"Storage upload gagal ({bucket}/{path}): {e}")
        return fallback_name


async def _upload_file(file, bucket: str, path: str) -> Optional[str]:
    """Async wrapper agar bisa di-await dari router lain (promo, profil, dll.)."""
    content = await file.read()
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(
            None,
            _upload_sync,
            content,
            file.content_type or "application/octet-stream",
            bucket,
            path,
            file.filename,
        ),
        timeout=15,
    )


def _kategori_to_zona(kategori: str) -> str:
    mapping = {
        "Kuliner": "Kuliner",
        "Fashion": "Fashion & Aksesoris",
        "Kerajinan": "Kerajinan & Seni",
        "Lainnya": "Umum",
    }
    return mapping.get(kategori, "Umum")