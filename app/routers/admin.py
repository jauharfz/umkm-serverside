"""
Router: Admin — Manajemen Pendaftaran UMKM
──────────────────────────────────────────
Endpoint ini digunakan oleh Gate Backend (backend-app) untuk
mengelola persetujuan/penolakan pendaftaran UMKM.

Autentikasi: X-Admin-Key header harus cocok dengan env var ADMIN_SECRET_KEY.
Ini adalah service-to-service auth — Gate Backend menyimpan key ini
dan meneruskannya ke endpoint ini.

Endpoints:
  GET  /api/admin/registrations          → list semua/pending UMKM
  PATCH /api/admin/registrations/{id}    → approve / reject
"""

import logging
import re
from fastapi import APIRouter, HTTPException, Header, Query
from typing import Optional
import app.database as db
from app.config import settings

router = APIRouter(prefix="/api/admin", tags=["Admin"])
logger = logging.getLogger(__name__)

# Signed URL berlaku 1 jam (3600 detik).
# Cukup untuk admin melihat dokumen — tidak perlu lama.
SIGNED_URL_EXPIRES = 3600


def _verify_admin_key(x_admin_key: Optional[str]) -> None:
    """Verifikasi service-to-service API key."""
    if not settings.ADMIN_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "ADMIN_SECRET_KEY belum dikonfigurasi di server."},
        )
    if x_admin_key != settings.ADMIN_SECRET_KEY:
        raise HTTPException(
            status_code=403,
            detail={"status": "error", "message": "Admin key tidak valid."},
        )


def _extract_storage_path(url: Optional[str], bucket: str) -> Optional[str]:
    """
    Ekstrak path relatif dari URL storage Supabase.

    URL format dari get_public_url():
      https://PROJECT.supabase.co/storage/v1/object/public/BUCKET/path/to/file.jpg
    atau dari create_signed_url() sebelumnya:
      https://PROJECT.supabase.co/storage/v1/object/sign/BUCKET/path/to/file.jpg?token=...

    Return: "path/to/file.jpg" (tanpa leading slash), atau None jika tidak bisa diekstrak.
    """
    if not url:
        return None

    # Coba ekstrak dari pola URL Supabase storage (public atau signed)
    patterns = [
        rf"/storage/v1/object/(?:public|sign)/{re.escape(bucket)}/(.+?)(?:\?|$)",
        rf"/object/(?:public|sign)/{re.escape(bucket)}/(.+?)(?:\?|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    # Fallback: kalau URL tidak dikenali (misalnya hanya nama file dari fallback upload),
    # kembalikan None — kita tidak bisa buat signed URL dari nama file saja.
    return None


def _make_signed_url(path: Optional[str], bucket: str) -> Optional[str]:
    """
    Buat signed URL untuk file di bucket private Supabase Storage.
    Return None jika path kosong atau pembuatan URL gagal.
    """
    if not path:
        return None
    try:
        result = db.supabase.storage.from_(bucket).create_signed_url(path, SIGNED_URL_EXPIRES)
        # supabase-py v2: result adalah dict {"signedURL": "...", "error": None}
        # supabase-py v1: result adalah dict {"signedURL": "..."}
        signed = result.get("signedURL") or result.get("signed_url") or result.get("url")
        if not signed:
            logger.warning(f"create_signed_url tidak mengembalikan URL untuk {bucket}/{path}: {result}")
        return signed
    except Exception as e:
        logger.warning(f"Gagal membuat signed URL untuk {bucket}/{path}: {e}")
        return None


def _resolve_doc_url(raw_url: Optional[str], bucket: str) -> Optional[str]:
    """
    Ubah raw URL (public URL atau fallback filename) ke signed URL.
    Jika signed URL gagal dibuat, kembalikan raw_url apa adanya
    (lebih baik user dapat error 400 dari Supabase daripada link None).
    """
    if not raw_url:
        return None

    path = _extract_storage_path(raw_url, bucket)
    if not path:
        # Mungkin hanya nama file dari fallback upload — tidak bisa dibuat signed URL
        logger.debug(f"Tidak bisa ekstrak path dari URL: {raw_url}")
        return raw_url  # kembalikan as-is

    signed = _make_signed_url(path, bucket)
    return signed if signed else raw_url  # fallback ke raw_url jika gagal


def _umkm_to_registration(u: dict) -> dict:
    """
    Serialisasi data UMKM untuk response registrasi.
    KTP dan NIB di-resolve ke signed URL agar bisa dibuka dari browser
    meskipun bucket 'dokumen-umkm' bersifat private.
    """
    bucket = settings.STORAGE_BUCKET_DOKUMEN  # "dokumen-umkm"

    return {
        "id":                 u["id"],
        "nama_pemilik":       u["nama_pemilik"],
        "email":              u["email"],
        "nama_usaha":         u["nama_usaha"],
        "alamat":             u.get("alamat"),
        "kategori":           u.get("kategori"),
        "deskripsi":          u.get("deskripsi"),
        "nomor_stand":        u.get("nomor_stand"),
        "zona":               u.get("zona"),
        "status_pendaftaran": u["status_pendaftaran"],
        # Signed URLs — berlaku 1 jam. None jika tidak ada file.
        "file_ktp_url":       _resolve_doc_url(u.get("file_ktp_url"), bucket),
        "file_nib_url":       _resolve_doc_url(u.get("file_nib_url"), bucket),
        "created_at":         u["created_at"],
    }


# ── GET /api/admin/registrations ─────────────────────────────────────────────
@router.get("/registrations")
async def list_registrations(
    status: Optional[str] = Query(None, description="Filter: pending | approved | rejected"),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """
    List pendaftaran UMKM.
    - Tanpa filter status → kembalikan semua
    - ?status=pending     → hanya yang menunggu persetujuan

    file_ktp_url dan file_nib_url dikembalikan sebagai signed URL (berlaku 1 jam).
    """
    _verify_admin_key(x_admin_key)

    try:
        query = (
            db.supabase.table("umkm")
            .select("*")
            .order("created_at", desc=True)
        )
        if status and status in ("pending", "approved", "rejected"):
            query = query.eq("status_pendaftaran", status)

        resp = query.execute()
        data = resp.data or []

        return {
            "status": "success",
            "total": len(data),
            "data": [_umkm_to_registration(u) for u in data],
        }
    except Exception as e:
        logger.error(f"list_registrations error: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": "Gagal mengambil data registrasi."},
        )


# ── PATCH /api/admin/registrations/{umkm_id} ─────────────────────────────────
@router.patch("/registrations/{umkm_id}")
async def update_registration_status(
    umkm_id: str,
    body: dict,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """
    Approve atau reject pendaftaran UMKM.
    Body: { "status": "approved" | "rejected" }
    """
    _verify_admin_key(x_admin_key)

    new_status = (body.get("status") or "").strip()
    if new_status not in ("approved", "rejected"):
        raise HTTPException(
            status_code=422,
            detail={"status": "error", "message": "Status harus 'approved' atau 'rejected'."},
        )

    try:
        # Cek eksistensi dulu
        check = (
            db.supabase.table("umkm")
            .select("id, status_pendaftaran, email, nama_usaha, file_ktp_url, file_nib_url, nama_pemilik, alamat, kategori, deskripsi, nomor_stand, zona, created_at")
            .eq("id", umkm_id)
            .limit(1)
            .execute()
        )
        if not check.data:
            raise HTTPException(
                status_code=404,
                detail={"status": "error", "message": "Data UMKM tidak ditemukan."},
            )

        current = check.data[0]
        if current["status_pendaftaran"] == new_status:
            return {
                "status": "success",
                "message": f"Status sudah '{new_status}', tidak ada perubahan.",
                "data": _umkm_to_registration(current),
            }

        # Update status
        resp = (
            db.supabase.table("umkm")
            .update({"status_pendaftaran": new_status})
            .eq("id", umkm_id)
            .execute()
        )
        if not resp.data:
            raise HTTPException(
                status_code=500,
                detail={"status": "error", "message": "Gagal memperbarui status."},
            )

        updated = resp.data[0]
        action = "disetujui" if new_status == "approved" else "ditolak"
        logger.info(
            f"UMKM {updated['email']} ({updated['nama_usaha']}) {action} oleh admin."
        )

        return {
            "status": "success",
            "message": f"Pendaftaran UMKM berhasil {action}.",
            "data": _umkm_to_registration(updated),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_registration_status error: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": "Gagal memperbarui status registrasi."},
        )