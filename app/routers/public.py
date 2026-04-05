from fastapi import APIRouter, Query
from typing import Optional
import requests as http
import app.database as db
from app.config import settings

router = APIRouter(prefix="/api/public", tags=["Publik (Gate Integration)"])

_TIMEOUT = 8  # detik


# ── GET /api/public/event ─────────────────────────────────────
@router.get("/event")
async def get_public_event():
    """
    Proxy ke Gate Backend GET /api/events/public (tanpa auth).
    Mengembalikan event aktif atau event mendatang terdekat dari sistem Gate.
    UMKM Frontend memakai tanggal ini untuk countdown dashboard.

    Field yang dikembalikan: { id, nama_event, tanggal, lokasi, status }
    Catatan: tanggal = DATE (YYYY-MM-DD). Frontend menggunakan
             tanggal + "T08:00:00+07:00" sebagai target countdown.

    Return { data: null } jika GATE_API_BASE_URL belum dikonfigurasi
    atau tidak ada event aktif/mendatang.
    """
    api_base = (settings.GATE_API_BASE_URL or "").strip()
    if not api_base:
        return {"status": "success", "data": None}

    url = f"{api_base.rstrip('/')}/api/events/public"
    try:
        resp = http.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        # Gate mengembalikan { status, data: {...} | null }
        return {"status": "success", "data": body.get("data")}
    except Exception:
        # Gagal hubungi Gate → kembalikan null, countdown tidak tampil
        return {"status": "success", "data": None}



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


# ── GET /api/public/kios-tersedia ─────────────────────────────
@router.get("/kios-tersedia")
async def get_kios_tersedia():
    """
    Endpoint publik — dipanggil frontend Register untuk menampilkan
    status kios real-time. Return: list nomor_stand yang sudah dipakai
    (status pending atau approved). Frontend tandai kios ini sebagai 'full'.
    """
    resp = (
        db.supabase.table("umkm")
        .select("nomor_stand")
        .neq("status_pendaftaran", "rejected")
        .execute()
    )
    occupied = [
        row["nomor_stand"]
        for row in (resp.data or [])
        if row.get("nomor_stand")
    ]
    return {"status": "success", "data": occupied}


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

    FIX: filter .gte("akhir", today) dihapus agar promo status=aktif
    selalu tampil di Gate terlepas dari tanggal. Gate menampilkan
    berlaku_hingga sehingga admin tahu mana yang sudah expired.
    """
    # Join promo + umkm melalui FK
    promo_query = (
        db.supabase.table("promo")
        .select("*, umkm:umkm_id(id, nama_usaha, nomor_stand, status_pendaftaran)")
        .eq("status", "aktif")
        # FIX: hapus .gte("akhir", today) — promo baru langsung tampil di Gate
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
