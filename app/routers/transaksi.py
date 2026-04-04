from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import datetime, timedelta, timezone
from app.deps import get_current_umkm
import app.database as db

router = APIRouter(prefix="/api/transaksi", tags=["Riwayat Transaksi"])

WIB = timezone(timedelta(hours=7))


def _fmt(t: dict, kiosk: str) -> dict:
    return {
        "id": t["id"],
        "customer": t.get("customer"),
        "item": t.get("item"),
        "total": t["total"],
        "time": t["waktu"],
        "status": t["status"],
        "kiosk": kiosk,
    }


# ── GET /api/transaksi ────────────────────────────────────────
@router.get("")
async def get_transaksi(
    search: Optional[str] = None,
    status: Optional[str] = None,
    umkm: dict = Depends(get_current_umkm),
):
    query = db.supabase.table("transaksi").select("*").eq("umkm_id", umkm["id"])

    if search:
        query = query.or_(f"customer.ilike.%{search}%,item.ilike.%{search}%")

    if status and status in ("Selesai", "Proses"):
        query = query.eq("status", status)

    resp = query.order("waktu", desc=True).execute()
    kiosk = f"{umkm['nama_usaha']} · Stand {umkm.get('nomor_stand', '-')}"

    return {
        "status": "success",
        "data": [_fmt(t, kiosk) for t in (resp.data or [])],
    }


# ── POST /api/transaksi ───────────────────────────────────────
# Endpoint tambahan (tidak di spec) agar UMKM bisa input transaksi manual
@router.post("", status_code=201, include_in_schema=True)
async def tambah_transaksi(body: dict, umkm: dict = Depends(get_current_umkm)):
    customer = body.get("customer")
    item = body.get("item")
    total = body.get("total", 0)
    trx_status = body.get("status", "Selesai")
    waktu = body.get("waktu") or datetime.now(WIB).isoformat()

    if total < 0:
        raise HTTPException(422, detail={"status": "error", "message": "Total tidak boleh negatif"})
    if trx_status not in ("Selesai", "Proses"):
        raise HTTPException(422, detail={"status": "error", "message": "Status harus 'Selesai' atau 'Proses'"})

    payload = {
        "umkm_id": umkm["id"],
        "customer": customer,
        "item": item,
        "total": total,
        "waktu": waktu,
        "status": trx_status,
    }

    resp = db.supabase.table("transaksi").insert(payload).execute()
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal menyimpan transaksi"})

    kiosk = f"{umkm['nama_usaha']} · Stand {umkm.get('nomor_stand', '-')}"

    # Buat notifikasi transaksi baru
    _buat_notif_transaksi(umkm["id"], resp.data[0], kiosk)

    return {
        "status": "success",
        "message": "Transaksi berhasil disimpan",
        "data": _fmt(resp.data[0], kiosk),
    }


def _buat_notif_transaksi(umkm_id: str, trx: dict, kiosk: str):
    try:
        db.supabase.table("notifikasi").insert({
            "umkm_id": umkm_id,
            "title": f"Transaksi Baru – Rp {trx['total']:,}",
            "deskripsi": f"Pelanggan: {trx.get('customer') or '-'} | {trx.get('item') or '-'}",
            "type": "transaksi",
            "detail": {
                "id": str(trx["id"]),
                "customer": trx.get("customer"),
                "total": trx["total"],
                "status": trx["status"],
            },
        }).execute()
    except Exception:
        pass
