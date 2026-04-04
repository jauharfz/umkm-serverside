from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional
from datetime import date
from app.deps import get_current_umkm
from app.routers.auth import _upload_file
from app.config import settings
import app.database as db

router = APIRouter(prefix="/api/promo", tags=["Promo & Diskon"])

TIPE_VALID = {"Persentase", "Nominal", "BeliXGratisY", "GratisOngkir", "Lainnya"}
STATUS_VALID = {"aktif", "nonaktif"}


def _fmt(p: dict) -> dict:
    return {
        "id": p["id"],
        "nama": p["nama"],
        "tipe": p["tipe"],
        "nilai": p["nilai"],
        "mulai": p["mulai"],
        "akhir": p["akhir"],
        "status": p["status"],
        "poster_url": p.get("poster_url"),
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
async def tambah_promo(
    nama: str = Form(...),
    tipe: str = Form(...),
    nilai: str = Form(...),
    mulai: date = Form(...),
    akhir: date = Form(...),
    file_poster: Optional[UploadFile] = File(None),
    umkm: dict = Depends(get_current_umkm),
):
    _validate_promo_fields(nama, tipe, nilai, mulai, akhir)

    poster_url = None
    if file_poster and file_poster.filename:
        poster_url = await _upload_file(
            file_poster,
            settings.STORAGE_BUCKET_POSTER,
            f"{umkm['id']}/{file_poster.filename}",
        )

    payload = {
        "umkm_id": umkm["id"],
        "nama": nama,
        "tipe": tipe,
        "nilai": nilai,
        "mulai": mulai.isoformat(),
        "akhir": akhir.isoformat(),
        "status": "aktif",
        "poster_url": poster_url,
    }

    resp = db.supabase.table("promo").insert(payload).execute()
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal menyimpan promo"})

    return {"status": "success", "message": "Promo berhasil ditambahkan", "data": _fmt(resp.data[0])}


# ── PUT /api/promo/{id} ───────────────────────────────────────
@router.put("/{promo_id}")
async def update_promo(
    promo_id: str,
    nama: Optional[str] = Form(None),
    tipe: Optional[str] = Form(None),
    nilai: Optional[str] = Form(None),
    mulai: Optional[date] = Form(None),
    akhir: Optional[date] = Form(None),
    status: Optional[str] = Form(None),
    file_poster: Optional[UploadFile] = File(None),
    umkm: dict = Depends(get_current_umkm),
):
    _get_promo_or_404(promo_id, umkm["id"])

    update_data = {}
    if nama is not None:
        update_data["nama"] = nama
    if tipe is not None:
        if tipe not in TIPE_VALID:
            raise HTTPException(422, detail={"status": "error", "message": f"Tipe promo tidak valid: {tipe}"})
        update_data["tipe"] = tipe
    if nilai is not None:
        update_data["nilai"] = nilai
    if mulai is not None:
        update_data["mulai"] = mulai.isoformat()
    if akhir is not None:
        update_data["akhir"] = akhir.isoformat()
    if status is not None:
        if status not in STATUS_VALID:
            raise HTTPException(422, detail={"status": "error", "message": "Status harus 'aktif' atau 'nonaktif'"})
        update_data["status"] = status

    if file_poster and file_poster.filename:
        poster_url = await _upload_file(
            file_poster,
            settings.STORAGE_BUCKET_POSTER,
            f"{umkm['id']}/{file_poster.filename}",
        )
        update_data["poster_url"] = poster_url

    if not update_data:
        existing = _get_promo_or_404(promo_id, umkm["id"])
        return {"status": "success", "message": "Tidak ada perubahan", "data": _fmt(existing)}

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
    _get_promo_or_404(promo_id, umkm["id"])
    db.supabase.table("promo").delete().eq("id", promo_id).eq("umkm_id", umkm["id"]).execute()
    return {"status": "success", "message": "Promo berhasil dihapus"}


# ── Helpers ───────────────────────────────────────────────────

def _get_promo_or_404(promo_id: str, umkm_id: str) -> dict:
    resp = (
        db.supabase.table("promo")
        .select("*")
        .eq("id", promo_id)
        .eq("umkm_id", umkm_id)
        .maybe_single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, detail={"status": "error", "message": "Data tidak ditemukan"})
    return resp.data


def _validate_promo_fields(nama, tipe, nilai, mulai, akhir):
    if not nama or not tipe or not nilai:
        raise HTTPException(422, detail={"status": "error", "message": "Field nama, tipe, nilai, mulai, dan akhir wajib diisi"})
    if tipe not in TIPE_VALID:
        raise HTTPException(422, detail={"status": "error", "message": f"Tipe tidak valid. Pilihan: {', '.join(TIPE_VALID)}"})
    if akhir < mulai:
        raise HTTPException(422, detail={"status": "error", "message": "Tanggal akhir tidak boleh sebelum tanggal mulai"})
