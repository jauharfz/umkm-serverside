from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from app.deps import get_current_umkm
import app.database as db

router = APIRouter(prefix="/api/notifikasi", tags=["Notifikasi"])


def _fmt(n: dict) -> dict:
    return {
        "id": n["id"],
        "title": n["title"],
        "desc": n.get("deskripsi"),
        "type": n["type"],
        "time": n["created_at"],
        "read": n["read"],
        "detail": n.get("detail"),
    }


# ── GET /api/notifikasi ───────────────────────────────────────
@router.get("")
async def get_notifikasi(
    filter: Optional[str] = "semua",
    umkm: dict = Depends(get_current_umkm),
):
    query = db.supabase.table("notifikasi").select("*").eq("umkm_id", umkm["id"])

    if filter == "belum":
        query = query.eq("read", False)
    elif filter == "sudah":
        query = query.eq("read", True)

    resp = query.order("created_at", desc=True).execute()
    notifs = resp.data or []

    unread_count = sum(1 for n in notifs if not n["read"])

    return {
        "status": "success",
        "data": {
            "unread_count": unread_count,
            "notifikasi": [_fmt(n) for n in notifs],
        },
    }


# ── PATCH /api/notifikasi/baca-semua ─────────────────────────
# Harus di atas /{id}/baca agar tidak clash routing
@router.patch("/baca-semua")
async def baca_semua_notifikasi(umkm: dict = Depends(get_current_umkm)):
    db.supabase.table("notifikasi").update({"read": True}).eq("umkm_id", umkm["id"]).eq("read", False).execute()
    return {"status": "success", "message": "Semua notifikasi ditandai sudah dibaca"}


# ── PATCH /api/notifikasi/{id}/baca ──────────────────────────
@router.patch("/{notif_id}/baca")
async def baca_notifikasi(notif_id: str, umkm: dict = Depends(get_current_umkm)):
    resp = (
        db.supabase.table("notifikasi")
        .select("id")
        .eq("id", notif_id)
        .eq("umkm_id", umkm["id"])
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, detail={"status": "error", "message": "Data tidak ditemukan"})

    db.supabase.table("notifikasi").update({"read": True}).eq("id", notif_id).execute()
    return {"status": "success", "message": "Notifikasi ditandai sudah dibaca"}