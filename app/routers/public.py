from fastapi import APIRouter, Query
from typing import Optional
from datetime import date
import app.database as db

router = APIRouter(prefix="/api/public", tags=["Publik (Gate Integration)"])


# ── GET /api/public/tenant ────────────────────────────────────
@router.get("/tenant")
async def get_public_tenant(
    kategori: Optional[str] = Query(None),
    is_aktif: Optional[bool] = Query(True),
):
    """
    Endpoint publik tanpa auth — dipanggil oleh backend Gate sebagai proxy.
    Hanya mengembalikan UMKM dengan status_pendaftaran = approved.
    """
    query = (
        db.supabase.table("umkm")
        .select("id, nama_usaha, kategori, nomor_stand, deskripsi, created_at")
        .eq("status_pendaftaran", "approved")
    )

    if kategori:
        query = query.ilike("kategori", f"%{kategori}%")

    resp = query.order("created_at", desc=False).execute()
    tenants = resp.data or []

    data = [
        {
            "id": t["id"],
            "nama_tenant": t["nama_usaha"],
            "kategori": (t.get("kategori") or "").lower(),
            "nomor_stand": t.get("nomor_stand") or "-",
            "deskripsi": t.get("deskripsi"),
            "created_at": t["created_at"],
        }
        for t in tenants
    ]

    return {"status": "success", "data": data}


# ── GET /api/public/diskon ────────────────────────────────────
@router.get("/diskon")
async def get_public_diskon(
    is_aktif: Optional[bool] = Query(True),
    tenant_id: Optional[str] = Query(None),
):
    """
    Endpoint publik tanpa auth — dipanggil Gate untuk menampilkan
    benefit diskon kepada member yang tap NFC (REQ-MEMBER-002).
    Data bersumber dari tabel promo UMKM yang sudah approved.
    """
    today = date.today().isoformat()

    # Join promo + umkm melalui FK
    promo_query = (
        db.supabase.table("promo")
        .select("*, umkm:umkm_id(id, nama_usaha, nomor_stand, status_pendaftaran)")
        .eq("status", "aktif")
        .gte("akhir", today)  # Promo masih berlaku
    )

    if tenant_id:
        promo_query = promo_query.eq("umkm_id", tenant_id)

    resp = promo_query.order("created_at", desc=True).execute()
    promos = resp.data or []

    # Filter hanya promo dari UMKM yang approved
    data = []
    for p in promos:
        umkm = p.get("umkm") or {}
        if umkm.get("status_pendaftaran") != "approved":
            continue

        persentase = _parse_persentase(p["tipe"], p["nilai"])

        data.append({
            "id": p["id"],
            "tenant_id": p["umkm_id"],
            "nama_tenant": umkm.get("nama_usaha", "-"),
            "nomor_stand": umkm.get("nomor_stand", "-"),
            "deskripsi_diskon": p["nama"],
            "persentase_diskon": persentase,
            "berlaku_mulai": p["mulai"],
            "berlaku_hingga": p["akhir"],
            "is_aktif": p["status"] == "aktif",
        })

    return {"status": "success", "data": data}


# ── Helper ────────────────────────────────────────────────────

def _parse_persentase(tipe: str, nilai: str) -> float:
    """
    Ekstrak nilai persentase numerik dari field 'nilai'.
    Contoh: tipe=Persentase, nilai="20%" → 20.0
             tipe=Nominal, nilai="10000" → 0.0
    """
    if tipe == "Persentase":
        try:
            return float(nilai.replace("%", "").strip())
        except (ValueError, AttributeError):
            return 0.0
    return 0.0
