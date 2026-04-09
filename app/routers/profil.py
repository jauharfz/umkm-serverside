from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.deps import get_current_umkm
from app.schemas import UpdateProfilRequest, GantiPasswordRequest
from app.config import settings
import app.database as db
import logging
import uuid
import mimetypes

router = APIRouter(prefix="/api", tags=["Profil & Pengaturan"])
logger = logging.getLogger(__name__)


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
        "qris_url": u.get("qris_url"),
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
    if body.qris_url is not None:
        update_data["qris_url"] = body.qris_url

    if not update_data:
        return {"status": "success", "message": "Tidak ada perubahan", "data": _fmt_profile(umkm)}

    resp = db.supabase.table("umkm").update(update_data).eq("id", umkm["id"]).execute()
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Gagal memperbarui profil"})

    return {"status": "success", "message": "Profil berhasil diperbarui", "data": _fmt_profile(resp.data[0])}


# ── PATCH /api/pengaturan/password ────────────────────────────
@router.patch("/pengaturan/password")
async def ganti_password(body: GantiPasswordRequest, umkm: dict = Depends(get_current_umkm)):
    # Jika konfirmasi_password dikirim, validasi kecocokan (frontend sudah validasi duluan)
    if body.konfirmasi_password is not None and body.password_baru != body.konfirmasi_password:
        raise HTTPException(400, detail={"status": "error", "message": "Password baru dan konfirmasi tidak sama"})

    # ── Verifikasi password lama via Supabase Auth sign_in ───
    # (sama seperti Gate yang menggunakan Supabase Auth)
    try:
        db.supabase.auth.sign_in_with_password({
            "email": umkm["email"],
            "password": body.password_lama,
        })
    except Exception:
        raise HTTPException(400, detail={"status": "error", "message": "Password lama tidak sesuai"})

    # ── Update password di Supabase Auth via admin API ───────
    auth_id = umkm.get("auth_id")
    if not auth_id:
        logger.error(f"umkm {umkm['id']} tidak memiliki auth_id")
        raise HTTPException(500, detail={"status": "error", "message": "Kesalahan konfigurasi akun. Hubungi admin."})

    try:
        db.supabase.auth.admin.update_user_by_id(
            auth_id,
            {"password": body.password_baru},
        )
    except Exception as e:
        logger.error(f"update_user_by_id gagal untuk auth_id {auth_id}: {e}")
        raise HTTPException(500, detail={"status": "error", "message": "Gagal mengubah password. Coba lagi."})

    return {"status": "success", "message": "Password berhasil diubah"}

# ── POST /api/profil/qris-upload ─────────────────────────────
# Upload foto QRIS statis ke Supabase Storage (bucket: poster-promo).
# Frontend mengirim multipart/form-data dengan key "file".
# Response: { status, qris_url }
@router.post("/profil/qris-upload")
async def upload_qris(
    file: UploadFile = File(...),
    umkm: dict = Depends(get_current_umkm),
):
    # Validasi tipe file
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if content_type not in allowed_types:
        raise HTTPException(400, detail={"status": "error", "message": "Hanya file gambar (JPG/PNG/WEBP) yang diperbolehkan"})

    # Ukuran max 2 MB
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(400, detail={"status": "error", "message": "Ukuran file maksimal 2 MB"})

    ext = (file.filename or "qris.jpg").rsplit(".", 1)[-1].lower()
    file_path = f"qris/{umkm['id']}/{uuid.uuid4()}.{ext}"

    try:
        bucket = settings.STORAGE_BUCKET_POSTER  # poster-promo (public)
        db.supabase.storage.from_(bucket).upload(
            file_path,
            contents,
            {"content-type": content_type, "upsert": "true"},
        )
        # Bangun URL publik
        qris_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/{bucket}/{file_path}"
    except Exception as e:
        logger.error(f"QRIS upload error: {e}")
        raise HTTPException(500, detail={"status": "error", "message": "Gagal mengupload foto QRIS"})

    # Simpan URL ke DB
    resp = db.supabase.table("umkm").update({"qris_url": qris_url}).eq("id", umkm["id"]).execute()
    if not resp.data:
        raise HTTPException(500, detail={"status": "error", "message": "Upload berhasil tapi gagal menyimpan URL"})

    return {"status": "success", "qris_url": qris_url}