from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from app.deps import get_current_umkm
from app.schemas import UpdateProfilRequest, GantiPasswordRequest
import app.database as db

router = APIRouter(prefix="/api", tags=["Profil & Pengaturan"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _fmt_profile(u: dict) -> dict:
    # Hitung stats
    total_produk = 0
    total_transaksi = 0
    try:
        bp = db.supabase.table("barang").select("id", count="exact").eq("umkm_id", u["id"]).execute()
        total_produk = bp.count or 0
        tp = db.supabase.table("transaksi").select("id", count="exact").eq("umkm_id", u["id"]).execute()
        total_transaksi = tp.count or 0
    except Exception:
        pass

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
        "stats": {
            "total_produk": total_produk,
            "total_transaksi": total_transaksi,
        },
        "created_at": u["created_at"],
    }


# ── GET /api/profil ───────────────────────────────────────────
@router.get("/profil")
async def get_profil(umkm: dict = Depends(get_current_umkm)):
    return {"status": "success", "data": _fmt_profile(umkm)}


# ── PATCH /api/profil ─────────────────────────────────────────
@router.patch("/profil")
async def update_profil(body: UpdateProfilRequest, umkm: dict = Depends(get_current_umkm)):
    update_data = {}
    if body.nama_pemilik is not None:
        update_data["nama_pemilik"] = body.nama_pemilik
    if body.nama_usaha is not None:
        update_data["nama_usaha"] = body.nama_usaha
    if body.alamat is not None:
        update_data["alamat"] = body.alamat
    if body.kategori is not None:
        update_data["kategori"] = body.kategori.value
    if body.deskripsi is not None:
        update_data["deskripsi"] = body.deskripsi

    if not update_data:
        return {"status": "success", "message": "Tidak ada perubahan", "data": _fmt_profile(umkm)}

    resp = db.supabase.table("umkm").update(update_data).eq("id", umkm["id"]).execute()
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal memperbarui profil"})

    return {"status": "success", "message": "Profil berhasil diperbarui", "data": _fmt_profile(resp.data[0])}


# ── PATCH /api/pengaturan/password ────────────────────────────
@router.patch("/pengaturan/password")
async def ganti_password(body: GantiPasswordRequest, umkm: dict = Depends(get_current_umkm)):
    if body.password_baru != body.konfirmasi_password:
        raise HTTPException(400, detail={"status": "error", "message": "Password baru dan konfirmasi tidak sama"})

    if not pwd_context.verify(body.password_lama, umkm["password_hash"]):
        raise HTTPException(400, detail={"status": "error", "message": "Password lama tidak sesuai"})

    new_hash = pwd_context.hash(body.password_baru)
    db.supabase.table("umkm").update({"password_hash": new_hash}).eq("id", umkm["id"]).execute()

    return {"status": "success", "message": "Password berhasil diubah"}
