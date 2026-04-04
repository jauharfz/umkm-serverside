from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from app.deps import get_current_umkm
from app.schemas import CreateKasRequest, UpdateKasRequest
import app.database as db

router = APIRouter(prefix="/api/kas", tags=["Buku Kas"])


def _compute_saldo(transaksi: list) -> list:
    """Hitung saldo kumulatif (running balance) berurut tgl ASC, created_at ASC."""
    sorted_trx = sorted(transaksi, key=lambda t: (t["tgl"], t["created_at"]))
    saldo = 0
    for t in sorted_trx:
        if t["jenis"] == "masuk":
            saldo += t["nominal"]
        else:
            saldo -= t["nominal"]
        t["saldo"] = saldo
    # Kembalikan urutan DESC (terbaru di atas) setelah saldo dihitung
    return list(reversed(sorted_trx))


def _ringkasan(transaksi: list) -> dict:
    masuk = [t for t in transaksi if t["jenis"] == "masuk"]
    keluar = [t for t in transaksi if t["jenis"] == "keluar"]
    total_masuk = sum(t["nominal"] for t in masuk)
    total_keluar = sum(t["nominal"] for t in keluar)
    return {
        "saldo": total_masuk - total_keluar,
        "total_masuk": total_masuk,
        "total_keluar": total_keluar,
        "count_masuk": len(masuk),
        "count_keluar": len(keluar),
    }


def _fmt(t: dict) -> dict:
    return {
        "id": t["id"],
        "tgl": t["tgl"],
        "ket": t["ket"],
        "jenis": t["jenis"],
        "nominal": t["nominal"],
        "saldo": t.get("saldo", 0),
        "kategori": t.get("kategori"),
    }


# ── GET /api/kas ──────────────────────────────────────────────
@router.get("")
async def get_kas(
    jenis: Optional[str] = None,
    umkm: dict = Depends(get_current_umkm),
):
    query = db.supabase.table("kas").select("*").eq("umkm_id", umkm["id"])
    # Ambil semua dulu untuk hitung running saldo
    all_resp = query.order("tgl", desc=False).order("created_at", desc=False).execute()
    all_trx = all_resp.data or []

    # Hitung running saldo pada semua transaksi
    all_with_saldo = _compute_saldo(all_trx)

    # Filter jenis setelah saldo dihitung
    if jenis and jenis in ("masuk", "keluar"):
        filtered = [t for t in all_with_saldo if t["jenis"] == jenis]
    else:
        filtered = all_with_saldo

    return {
        "status": "success",
        "data": {
            "ringkasan": _ringkasan(all_trx),
            "transaksi": [_fmt(t) for t in filtered],
        },
    }


# ── POST /api/kas ─────────────────────────────────────────────
@router.post("", status_code=201)
async def tambah_kas(body: CreateKasRequest, umkm: dict = Depends(get_current_umkm)):
    payload = {
        "umkm_id": umkm["id"],
        "tgl": body.tgl.isoformat(),
        "ket": body.ket,
        "jenis": body.jenis.value,
        "nominal": body.nominal,
        "kategori": body.kategori,
    }
    resp = db.supabase.table("kas").insert(payload).execute()
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal menyimpan transaksi"})

    # Hitung saldo terkini
    all_resp = db.supabase.table("kas").select("*").eq("umkm_id", umkm["id"]).order("tgl").order("created_at").execute()
    all_with_saldo = _compute_saldo(all_resp.data or [])

    # Cari saldo untuk record baru
    new_id = resp.data[0]["id"]
    new_with_saldo = next((t for t in all_with_saldo if t["id"] == new_id), resp.data[0])

    return {"status": "success", "message": "Transaksi berhasil disimpan", "data": _fmt(new_with_saldo)}


# ── PUT /api/kas/{id} ─────────────────────────────────────────
@router.put("/{kas_id}")
async def update_kas(kas_id: str, body: UpdateKasRequest, umkm: dict = Depends(get_current_umkm)):
    _get_kas_or_404(kas_id, umkm["id"])

    update_data = {}
    if body.tgl is not None:
        update_data["tgl"] = body.tgl.isoformat()
    if body.ket is not None:
        update_data["ket"] = body.ket
    if body.jenis is not None:
        update_data["jenis"] = body.jenis.value
    if body.nominal is not None:
        update_data["nominal"] = body.nominal
    if body.kategori is not None:
        update_data["kategori"] = body.kategori

    if not update_data:
        raise HTTPException(422, detail={"status": "error", "message": "Tidak ada data yang diubah"})

    db.supabase.table("kas").update(update_data).eq("id", kas_id).eq("umkm_id", umkm["id"]).execute()

    # Hitung ulang saldo
    all_resp = db.supabase.table("kas").select("*").eq("umkm_id", umkm["id"]).order("tgl").order("created_at").execute()
    all_with_saldo = _compute_saldo(all_resp.data or [])
    updated = next((t for t in all_with_saldo if t["id"] == kas_id), None)

    return {"status": "success", "message": "Data berhasil diupdate", "data": _fmt(updated) if updated else {}}


# ── DELETE /api/kas/{id} ──────────────────────────────────────
@router.delete("/{kas_id}")
async def hapus_kas(kas_id: str, umkm: dict = Depends(get_current_umkm)):
    _get_kas_or_404(kas_id, umkm["id"])
    db.supabase.table("kas").delete().eq("id", kas_id).eq("umkm_id", umkm["id"]).execute()
    return {"status": "success", "message": "Data berhasil dihapus"}


# ── Helpers ───────────────────────────────────────────────────

def _get_kas_or_404(kas_id: str, umkm_id: str) -> dict:
    resp = (
        db.supabase.table("kas")
        .select("*")
        .eq("id", kas_id)
        .eq("umkm_id", umkm_id)
        .maybe_single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, detail={"status": "error", "message": "Data tidak ditemukan"})
    return resp.data
