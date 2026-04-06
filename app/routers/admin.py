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
from fastapi import APIRouter, HTTPException, Header, Query
from typing import Optional
import app.database as db
from app.config import settings

router = APIRouter(prefix="/api/admin", tags=["Admin"])
logger = logging.getLogger(__name__)


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


def _umkm_to_registration(u: dict) -> dict:
    """Serialisasi data UMKM untuk response registrasi."""
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
        "file_ktp_url": u.get("file_ktp_url"),
        "file_nib_url": u.get("file_nib_url"),
        "created_at": u["created_at"],
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
            .select("id, status_pendaftaran, email, nama_usaha")
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
