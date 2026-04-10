from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import Optional
from app.deps import get_current_umkm
from app.schemas import CreateBarangRequest, UpdateBarangRequest
from app.config import settings
import app.database as db
import httpx
import uuid
import mimetypes
import logging

router = APIRouter(prefix="/api/stok", tags=["Stok"])
logger = logging.getLogger(__name__)

STOK_KRITIS_THRESHOLD = 5


def _fmt(b: dict) -> dict:
    return {
        "id":       b["id"],
        "nama":     b["nama"],
        "stok":     b["stok"],
        "max":      b["stok_max"],
        "harga":    b["harga"],
        "kategori": b.get("kategori"),
        "satuan":   b.get("satuan"),
        "deskripsi":b.get("deskripsi"),
        "foto_url": b.get("foto_url"),   # foto produk (opsional)
    }


# ── GET /api/stok ─────────────────────────────────────────────
@router.get("")
async def get_stok(search: Optional[str] = None, umkm: dict = Depends(get_current_umkm)):
    query = db.supabase.table("barang").select("*").eq("umkm_id", umkm["id"])
    if search:
        query = query.or_(f"nama.ilike.%{search}%,kategori.ilike.%{search}%")
    resp = query.order("created_at", desc=True).execute()
    return {"status": "success", "data": [_fmt(b) for b in (resp.data or [])]}


# ── POST /api/stok ────────────────────────────────────────────
@router.post("", status_code=201)
async def tambah_barang(body: CreateBarangRequest, umkm: dict = Depends(get_current_umkm)):
    if not body.nama or body.stok is None or body.harga is None:
        raise HTTPException(422, detail={"status": "error", "message": "Field nama, stok, dan harga wajib diisi"})

    payload = {
        "umkm_id":  umkm["id"],
        "nama":     body.nama,
        "stok":     body.stok,
        "stok_max": body.max or 100,
        "harga":    body.harga,
        "kategori": body.kategori.value if body.kategori else None,
        "satuan":   body.satuan,
        "deskripsi":body.deskripsi,
    }

    resp = db.supabase.table("barang").insert(payload).execute()
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal menyimpan data"})

    barang = resp.data[0]
    if barang["stok"] <= STOK_KRITIS_THRESHOLD:
        _buat_notif_stok_kritis(umkm["id"], barang)

    return {"status": "success", "message": "Barang berhasil ditambahkan", "data": _fmt(barang)}


# ── PUT /api/stok/{id} ────────────────────────────────────────
@router.put("/{item_id}")
async def update_barang(item_id: str, body: UpdateBarangRequest, umkm: dict = Depends(get_current_umkm)):
    existing = _get_barang_or_404(item_id, umkm["id"])

    update_data = {}
    if body.nama      is not None: update_data["nama"]     = body.nama
    if body.stok      is not None: update_data["stok"]     = body.stok
    if body.harga     is not None: update_data["harga"]    = body.harga
    if body.kategori  is not None: update_data["kategori"] = body.kategori.value
    if body.satuan    is not None: update_data["satuan"]   = body.satuan
    if body.deskripsi is not None: update_data["deskripsi"]= body.deskripsi
    if body.max       is not None: update_data["stok_max"] = body.max

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
    if "stok" in update_data and updated["stok"] <= STOK_KRITIS_THRESHOLD:
        _buat_notif_stok_kritis(umkm["id"], updated)

    return {"status": "success", "message": "Data barang berhasil diperbarui", "data": _fmt(updated)}


# ── DELETE /api/stok/{id} ─────────────────────────────────────
@router.delete("/{item_id}")
async def hapus_barang(item_id: str, umkm: dict = Depends(get_current_umkm)):
    _get_barang_or_404(item_id, umkm["id"])
    db.supabase.table("barang").delete().eq("id", item_id).eq("umkm_id", umkm["id"]).execute()
    return {"status": "success", "message": "Barang berhasil dihapus"}


# ── POST /api/stok/{id}/foto ──────────────────────────────────
# Upload foto produk ke Supabase Storage (bucket: poster-promo, public).
# Gunakan direct HTTP agar service_role key benar-benar terkirim (bypass RLS).
@router.post("/{item_id}/foto")
async def upload_foto_barang(
    item_id: str,
    file: UploadFile = File(...),
    umkm: dict = Depends(get_current_umkm),
):
    _get_barang_or_404(item_id, umkm["id"])  # pastikan barang milik umkm ini

    allowed = {"image/jpeg", "image/png", "image/webp"}
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if content_type not in allowed:
        raise HTTPException(400, detail={"status": "error", "message": "Hanya JPG/PNG/WEBP yang diperbolehkan"})

    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(400, detail={"status": "error", "message": "Ukuran file maksimal 2 MB"})

    ext = (file.filename or "foto.jpg").rsplit(".", 1)[-1].lower()
    file_path = f"barang/{umkm['id']}/{item_id}/{uuid.uuid4()}.{ext}"
    bucket    = settings.STORAGE_BUCKET_POSTER  # poster-promo (public)

    try:
        storage_url = f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}/{file_path}"
        headers = {
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": content_type,
            "x-upsert": "true",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(storage_url, content=contents, headers=headers)
            if resp.status_code not in (200, 201):
                logger.error(f"Foto barang upload gagal: {resp.status_code} {resp.text}")
                raise Exception(f"Storage {resp.status_code}: {resp.text}")

        foto_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/{bucket}/{file_path}"
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Foto barang upload error: {e}")
        raise HTTPException(500, detail={"status": "error", "message": "Gagal mengupload foto produk"})

    resp = (
        db.supabase.table("barang")
        .update({"foto_url": foto_url})
        .eq("id", item_id)
        .eq("umkm_id", umkm["id"])
        .execute()
    )
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Upload berhasil tapi gagal menyimpan URL"})

    return {"status": "success", "foto_url": foto_url}


# ── Helpers ───────────────────────────────────────────────────
def _get_barang_or_404(item_id: str, umkm_id: str) -> dict:
    resp = (
        db.supabase.table("barang")
        .select("*")
        .eq("id", item_id)
        .eq("umkm_id", umkm_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, detail={"status": "error", "message": "Data tidak ditemukan"})
    return resp.data[0]


def _buat_notif_stok_kritis(umkm_id: str, barang: dict):
    try:
        db.supabase.table("notifikasi").insert({
            "umkm_id": umkm_id,
            "title": f"Stok {barang['nama']} Hampir Habis",
            "deskripsi": f"Sisa {barang['stok']} {barang.get('satuan') or 'unit'} — di bawah batas minimum ({STOK_KRITIS_THRESHOLD}).",
            "type": "stok",
            "detail": {
                "produk":      barang["nama"],
                "stokSisa":    f"{barang['stok']} {barang.get('satuan') or 'unit'}",
                "stokMinimum": str(STOK_KRITIS_THRESHOLD),
                "kategori":    barang.get("kategori"),
                "saran":       "Segera lakukan restok.",
            },
        }).execute()
    except Exception:
        pass


# ── PATCH /api/stok/{id}/foto-hapus ──────────────────────────
# Set foto_url = NULL di DB (hapus referensi, bukan file dari storage)
@router.patch("/{item_id}/foto-hapus")
async def hapus_foto_barang(item_id: str, umkm: dict = Depends(get_current_umkm)):
    _get_barang_or_404(item_id, umkm["id"])
    resp = (
        db.supabase.table("barang")
        .update({"foto_url": None})
        .eq("id", item_id)
        .eq("umkm_id", umkm["id"])
        .execute()
    )
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal menghapus foto"})
    return {"status": "success", "message": "Foto berhasil dihapus"}
