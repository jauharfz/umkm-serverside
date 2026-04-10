from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Optional
import app.database as db
from app.config import settings
import asyncio
import logging

router = APIRouter(prefix="/api/auth", tags=["Autentikasi"])
logger = logging.getLogger(__name__)


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
        "qris_url": u.get("qris_url"),       # ← wajib ada agar Kasir.jsx bisa tampilkan QRIS
        "status_pendaftaran": u["status_pendaftaran"],
        "created_at": u["created_at"],
    }


# ── POST /api/auth/login ──────────────────────────────────────
@router.post("/login")
async def login(body: dict):
    email    = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        raise HTTPException(422, detail={"status": "error", "message": "Field email dan password wajib diisi"})

    # ── 1. Cek status pendaftaran dulu (sebelum auth call) ──
    umkm_resp = (
        db.supabase.table("umkm")
        .select("*")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    if not umkm_resp.data:
        raise HTTPException(401, detail={"status": "error", "message": "Email atau password salah"})

    umkm = umkm_resp.data[0]

    status = umkm["status_pendaftaran"]
    if status == "pending":
        raise HTTPException(403, detail={"status": "error", "message": "Pendaftaran kamu sedang diproses. Tunggu konfirmasi admin."})
    if status == "rejected":
        raise HTTPException(403, detail={"status": "error", "message": "Pendaftaran kamu ditolak. Silakan hubungi admin."})

    # ── 2. Autentikasi via Supabase Auth ────────────────────
    try:
        auth_resp = db.supabase.auth.sign_in_with_password({"email": email, "password": password})
        if not auth_resp.session:
            raise HTTPException(401, detail={"status": "error", "message": "Email atau password salah"})
        token = auth_resp.session.access_token
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, detail={"status": "error", "message": "Email atau password salah"})

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
    nama_pemilik: str     = Form(...),
    email: str            = Form(...),
    password: str         = Form(...),
    nama_usaha: str       = Form(...),
    alamat: str           = Form(""),
    kategori: str         = Form(...),
    deskripsi: Optional[str] = Form(None),
    nomor_stand: str      = Form(...),
    setuju: str           = Form(...),
    file_ktp: UploadFile  = File(...),
    file_nib: UploadFile  = File(...),
):
    auth_user_id = None  # untuk rollback jika DB insert gagal

    try:
        setuju_bool = setuju.lower() in ("true", "1", "yes", "on")
        if not setuju_bool:
            raise HTTPException(422, detail={"status": "error", "message": "Anda harus menyetujui syarat & ketentuan"})
        if len(password) < 8:
            raise HTTPException(422, detail={"status": "error", "message": "Password minimal 8 karakter"})

        loop = asyncio.get_event_loop()

        def _check_email():
            return db.supabase.table("umkm").select("id").eq("email", email).limit(1).execute()

        def _check_kios():
            return (
                db.supabase.table("umkm")
                .select("id")
                .eq("nomor_stand", nomor_stand)
                .neq("status_pendaftaran", "rejected")
                .limit(1)
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
            raise HTTPException(409, detail={"status": "error", "message": f"Kios {nomor_stand} sudah dipilih oleh pendaftar lain. Silakan pilih kios lain."})

        # ── Buat user di Supabase Auth ─────────────────────────
        def _create_auth_user():
            return db.supabase.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,  # skip email verification — status pendaftaran yang jadi gatekeeper
                "user_metadata": {"nama_pemilik": nama_pemilik},
            })

        try:
            auth_resp = await asyncio.wait_for(loop.run_in_executor(None, _create_auth_user), timeout=15)
            if not auth_resp.user:
                raise HTTPException(500, detail={"status": "error", "message": "Gagal membuat akun autentikasi."})
            auth_user_id = auth_resp.user.id
        except HTTPException:
            raise
        except asyncio.TimeoutError:
            raise HTTPException(503, detail={"status": "error", "message": "Auth timeout, coba lagi."})
        except Exception as e:
            err_msg = str(e).lower()
            if "already registered" in err_msg or "already exists" in err_msg:
                raise HTTPException(409, detail={"status": "error", "message": "Email sudah terdaftar."})
            logger.error(f"create_auth_user gagal: {e}")
            raise HTTPException(500, detail={"status": "error", "message": "Gagal membuat akun. Coba lagi."})

        # ── Upload KTP & NIB ────────────────────────────────────
        ktp_content = await file_ktp.read()
        nib_content = await file_nib.read()
        ktp_filename    = file_ktp.filename or "ktp.jpg"
        nib_filename    = file_nib.filename or "nib.jpg"
        ktp_content_type = file_ktp.content_type or "application/octet-stream"
        nib_content_type = file_nib.content_type or "application/octet-stream"

        def _upload_ktp():
            return _upload_sync(ktp_content, ktp_content_type, settings.STORAGE_BUCKET_DOKUMEN, f"ktp/{email}_{ktp_filename}", ktp_filename)

        def _upload_nib():
            return _upload_sync(nib_content, nib_content_type, settings.STORAGE_BUCKET_DOKUMEN, f"nib/{email}_{nib_filename}", nib_filename)

        try:
            ktp_url = await asyncio.wait_for(loop.run_in_executor(None, _upload_ktp), timeout=15.0)
        except Exception as e:
            logger.warning(f"Upload KTP gagal ({e}) — fallback ke nama file")
            ktp_url = ktp_filename

        try:
            nib_url = await asyncio.wait_for(loop.run_in_executor(None, _upload_nib), timeout=15.0)
        except Exception as e:
            logger.warning(f"Upload NIB gagal ({e}) — fallback ke nama file")
            nib_url = nib_filename

        # ── Insert ke tabel umkm ────────────────────────────────
        zona = _kategori_to_zona(kategori)
        new_umkm = {
            "auth_id":           auth_user_id,   # FK ke auth.users.id
            "nama_pemilik":      nama_pemilik,
            "email":             email,
            "nama_usaha":        nama_usaha,
            "alamat":            alamat,
            "kategori":          kategori,
            "deskripsi":         deskripsi,
            "nomor_stand":       nomor_stand,
            "zona":              zona,
            "status_pendaftaran": "pending",
            "file_ktp_url":      ktp_url,
            "file_nib_url":      nib_url,
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

        # Berhasil — reset auth_user_id agar tidak di-rollback
        auth_user_id = None

        return {
            "status": "success",
            "message": "Pendaftaran berhasil! Menunggu konfirmasi admin.",
            "data": _umkm_to_profile(resp.data[0]),
        }

    except HTTPException:
        # Rollback: hapus user auth jika DB insert gagal
        if auth_user_id:
            try:
                db.supabase.auth.admin.delete_user(auth_user_id)
            except Exception as e:
                logger.warning(f"Rollback delete auth user gagal: {e}")
        raise
    except asyncio.CancelledError:
        if auth_user_id:
            try:
                db.supabase.auth.admin.delete_user(auth_user_id)
            except Exception:
                pass
        logger.warning("Register request cancelled by client/server")
        raise HTTPException(503, detail={"status": "error", "message": "Request dibatalkan, coba lagi."})
    except BaseException as e:
        if auth_user_id:
            try:
                db.supabase.auth.admin.delete_user(auth_user_id)
            except Exception:
                pass
        logger.error(f"Unexpected error in register: {e}", exc_info=True)
        raise HTTPException(500, detail={"status": "error", "message": "Terjadi kesalahan pada server. Silakan coba lagi."})


# ── GET /api/auth/status ──────────────────────────────────────
@router.get("/status")
async def check_status(email: str):
    if not email:
        raise HTTPException(422, detail={"status": "error", "message": "Parameter email wajib diisi"})

    resp = (
        db.supabase.table("umkm")
        .select("email, status_pendaftaran")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, detail={"status": "error", "message": "Email tidak ditemukan"})

    return {
        "status": "success",
        "data": {
            "email": resp.data[0]["email"],
            "status_pendaftaran": resp.data[0]["status_pendaftaran"],
        },
    }


# ── GET /api/auth/check-email ─────────────────────────────────
# Dipanggil oleh form Register (on-blur) untuk cek ketersediaan email
# sebelum user submit. Tidak memerlukan JWT karena user belum login.
# ⚠ Rate-limit wajib di reverse-proxy: maks 30 req/menit per IP.
@router.get("/check-email")
async def check_email_availability(email: str):
    if not email or "@" not in email:
        return {"status": "success", "available": False}
    resp = (
        db.supabase.table("umkm")
        .select("id")
        .eq("email", email.strip().lower())
        .limit(1)
        .execute()
    )
    return {"status": "success", "available": not bool(resp.data)}


# ── Helpers ───────────────────────────────────────────────────

def _upload_sync(
    content: bytes,
    content_type: str,
    bucket: str,
    path: str,
    fallback_name: str,
) -> Optional[str]:
    """
    Upload file ke Supabase Storage — SYNC, dipanggil via run_in_executor.
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
    """Async wrapper untuk dipanggil dari router lain (promo, profil, dll.)."""
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
        "Kuliner":    "Kuliner",
        "Fashion":    "Fashion & Aksesoris",
        "Kerajinan":  "Kerajinan & Seni",
        "Lainnya":    "Umum",
    }
    return mapping.get(kategori, "Umum")