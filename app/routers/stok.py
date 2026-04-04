from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from app.deps import get_current_umkm
from app.schemas import CreateBarangRequest, UpdateBarangRequest
import app.database as db

router = APIRouter(prefix="/api/stok", tags=["Stok"])

STOK_KRITIS_THRESHOLD = 5


def _fmt(b: dict) -> dict:
    return {
        "id": b["id"],
        "nama": b["nama"],
        "stok": b["stok"],
        "max": b["stok_max"],
        "harga": b["harga"],
        "kategori": b.get("kategori"),
        "satuan": b.get("satuan"),
        "deskripsi": b.get("deskripsi"),
    }


# ── GET /api/stok ─────────────────────────────────────────────
@router.get("")
async def get_stok(search: Optional[str] = None, umkm: dict = Depends(get_current_umkm)):
    query = db.supabase.table("barang").select("*").eq("umkm_id", umkm["id"])

    if search:
        # Supabase supports ilike for case-insensitive search
        query = query.or_(f"nama.ilike.%{search}%,kategori.ilike.%{search}%")

    resp = query.order("created_at", desc=True).execute()
    return {"status": "success", "data": [_fmt(b) for b in (resp.data or [])]}


# ── POST /api/stok ────────────────────────────────────────────
@router.post("", status_code=201)
async def tambah_barang(body: CreateBarangRequest, umkm: dict = Depends(get_current_umkm)):
    if not body.nama or body.stok is None or body.harga is None:
        raise HTTPException(422, detail={"status": "error", "message": "Field nama, stok, dan harga wajib diisi"})

    payload = {
        "umkm_id": umkm["id"],
        "nama": body.nama,
        "stok": body.stok,
        "stok_max": body.max or 100,
        "harga": body.harga,
        "kategori": body.kategori.value if body.kategori else None,
        "satuan": body.satuan,
        "deskripsi": body.deskripsi,
    }

    resp = db.supabase.table("barang").insert(payload).execute()
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal menyimpan data"})

    barang = resp.data[0]

    # Cek stok kritis → buat notifikasi
    if barang["stok"] <= STOK_KRITIS_THRESHOLD:
        _buat_notif_stok_kritis(umkm["id"], barang)

    return {"status": "success", "message": "Barang berhasil ditambahkan", "data": _fmt(barang)}


# ── PUT /api/stok/{id} ────────────────────────────────────────
@router.put("/{item_id}")
async def update_barang(item_id: str, body: UpdateBarangRequest, umkm: dict = Depends(get_current_umkm)):
    # Verifikasi kepemilikan
    existing = _get_barang_or_404(item_id, umkm["id"])

    update_data = {}
    if body.nama is not None:
        update_data["nama"] = body.nama
    if body.stok is not None:
        update_data["stok"] = body.stok
    if body.harga is not None:
        update_data["harga"] = body.harga
    if body.kategori is not None:
        update_data["kategori"] = body.kategori.value
    if body.satuan is not None:
        update_data["satuan"] = body.satuan
    if body.deskripsi is not None:
        update_data["deskripsi"] = body.deskripsi
    if body.max is not None:
        update_data["stok_max"] = body.max

    if not update_data:
        return {"status": "success", "message": "Tidak ada perubahan", "data": _fmt(existing)}

    resp = (
        db.supabase.table("barang")
        .update(update_data)
        .eq("id", item_id)
        .eq("umkm_id", umkm["id"])
        .execute()
    )
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal memperbarui data"})

    updated = resp.data[0]

    # Cek stok kritis setelah update
    if "stok" in update_data and updated["stok"] <= STOK_KRITIS_THRESHOLD:
        _buat_notif_stok_kritis(umkm["id"], updated)

    return {"status": "success", "message": "Data barang berhasil diperbarui", "data": _fmt(updated)}


# ── DELETE /api/stok/{id} ─────────────────────────────────────
@router.delete("/{item_id}")
async def hapus_barang(item_id: str, umkm: dict = Depends(get_current_umkm)):
    _get_barang_or_404(item_id, umkm["id"])

    db.supabase.table("barang").delete().eq("id", item_id).eq("umkm_id", umkm["id"]).execute()
    return {"status": "success", "message": "Barang berhasil dihapus"}


# ── Helpers ───────────────────────────────────────────────────

def _get_barang_or_404(item_id: str, umkm_id: str) -> dict:
    resp = (
        db.supabase.table("barang")
        .select("*")
        .eq("id", item_id)
        .eq("umkm_id", umkm_id)
        .maybe_single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, detail={"status": "error", "message": "Data tidak ditemukan"})
    return resp.data


def _buat_notif_stok_kritis(umkm_id: str, barang: dict):
    try:
        db.supabase.table("notifikasi").insert({
            "umkm_id": umkm_id,
            "title": f"Stok {barang['nama']} Hampir Habis",
            "deskripsi": f"Sisa {barang['stok']} {barang.get('satuan') or 'unit'} — di bawah batas minimum ({STOK_KRITIS_THRESHOLD}).",
            "type": "stok",
            "detail": {
                "produk": barang["nama"],
                "stokSisa": f"{barang['stok']} {barang.get('satuan') or 'unit'}",
                "stokMinimum": str(STOK_KRITIS_THRESHOLD),
                "kategori": barang.get("kategori"),
                "saran": "Segera lakukan restok.",
            },
        }).execute()
    except Exception:
        pass  # Notifikasi gagal tidak boleh break main flow
