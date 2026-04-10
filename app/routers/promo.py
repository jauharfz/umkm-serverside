from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import date
from pydantic import BaseModel
from app.deps import get_current_umkm
import app.database as db

router = APIRouter(prefix="/api/promo", tags=["Promo & Diskon"])

TIPE_VALID   = {"Persentase", "Nominal", "BeliXGratisY", "GratisOngkir", "Lainnya"}
STATUS_VALID = {"aktif", "nonaktif"}


# ── Schemas ───────────────────────────────────────────────────
class PromoBody(BaseModel):
    nama:  str
    tipe:  str
    nilai: str
    mulai: date
    akhir: date


class PromoUpdateBody(BaseModel):
    nama:   Optional[str]  = None
    tipe:   Optional[str]  = None
    nilai:  Optional[str]  = None
    mulai:  Optional[date] = None
    akhir:  Optional[date] = None
    status: Optional[str]  = None


# ── Formatter ─────────────────────────────────────────────────
def _fmt(p: dict) -> dict:
    return {
        "id":     p["id"],
        "nama":   p["nama"],
        "tipe":   p["tipe"],
        "nilai":  p["nilai"],
        "mulai":  p["mulai"],
        "akhir":  p["akhir"],
        "status": p["status"],
    }


# ── GET /api/promo ────────────────────────────────────────────
@router.get("")
async def get_promo(umkm: dict = Depends(get_current_umkm)):
    resp = (
        db.supabase.table("promo")
        .select("*")
        .eq("umkm_id", umkm["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return {"status": "success", "data": [_fmt(p) for p in (resp.data or [])]}


# ── POST /api/promo ───────────────────────────────────────────
@router.post("", status_code=201)
async def tambah_promo(body: PromoBody, umkm: dict = Depends(get_current_umkm)):
    _validate(body.nama, body.tipe, body.nilai, body.mulai, body.akhir)

    resp = db.supabase.table("promo").insert({
        "umkm_id": umkm["id"],
        "nama":    body.nama,
        "tipe":    body.tipe,
        "nilai":   body.nilai,
        "mulai":   body.mulai.isoformat(),
        "akhir":   body.akhir.isoformat(),
        "status":  "aktif",
    }).execute()

    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal menyimpan promo"})

    return {"status": "success", "message": "Promo berhasil ditambahkan", "data": _fmt(resp.data[0])}


# ── PUT /api/promo/{id} ───────────────────────────────────────
@router.put("/{promo_id}")
async def update_promo(promo_id: str, body: PromoUpdateBody, umkm: dict = Depends(get_current_umkm)):
    _get_or_404(promo_id, umkm["id"])

    update_data = {}
    if body.nama   is not None: update_data["nama"]   = body.nama
    if body.tipe   is not None:
        if body.tipe not in TIPE_VALID:
            raise HTTPException(422, detail={"status": "error", "message": f"Tipe promo tidak valid: {body.tipe}"})
        update_data["tipe"] = body.tipe
    if body.nilai  is not None: update_data["nilai"]  = body.nilai
    if body.mulai  is not None: update_data["mulai"]  = body.mulai.isoformat()
    if body.akhir  is not None: update_data["akhir"]  = body.akhir.isoformat()
    if body.status is not None:
        if body.status not in STATUS_VALID:
            raise HTTPException(422, detail={"status": "error", "message": "Status harus 'aktif' atau 'nonaktif'"})
        update_data["status"] = body.status

    if not update_data:
        return {"status": "success", "message": "Tidak ada perubahan", "data": _fmt(_get_or_404(promo_id, umkm["id"]))}

    resp = (
        db.supabase.table("promo")
        .update(update_data)
        .eq("id", promo_id)
        .eq("umkm_id", umkm["id"])
        .execute()
    )
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal memperbarui promo"})

    return {"status": "success", "message": "Promo berhasil diperbarui", "data": _fmt(resp.data[0])}


# ── DELETE /api/promo/{id} ────────────────────────────────────
@router.delete("/{promo_id}")
async def hapus_promo(promo_id: str, umkm: dict = Depends(get_current_umkm)):
    _get_or_404(promo_id, umkm["id"])
    db.supabase.table("promo").delete().eq("id", promo_id).eq("umkm_id", umkm["id"]).execute()
    return {"status": "success", "message": "Promo berhasil dihapus"}


# ── Helpers ───────────────────────────────────────────────────
def _get_or_404(promo_id: str, umkm_id: str) -> dict:
    resp = (
        db.supabase.table("promo")
        .select("*")
        .eq("id", promo_id)
        .eq("umkm_id", umkm_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, detail={"status": "error", "message": "Data tidak ditemukan"})
    return resp.data[0]


def _validate(nama, tipe, nilai, mulai, akhir):
    if not nama or not tipe or not nilai:
        raise HTTPException(422, detail={"status": "error", "message": "Field nama, tipe, nilai, mulai, dan akhir wajib diisi"})
    if tipe not in TIPE_VALID:
        raise HTTPException(422, detail={"status": "error", "message": f"Tipe tidak valid. Pilihan: {', '.join(TIPE_VALID)}"})
    if akhir < mulai:
        raise HTTPException(422, detail={"status": "error", "message": "Tanggal akhir tidak boleh sebelum tanggal mulai"})