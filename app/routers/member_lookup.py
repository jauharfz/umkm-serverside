"""
Router: Member Lookup (Proxy ke Gate Backend)
─────────────────────────────────────────────
GET /api/member/lookup   → Proxy ke Gate Backend GET /api/members/lookup
                           Proteksi: JWT UMKM (user yang login)

ARSITEKTUR:
  UMKM Frontend → (JWT) → UMKM Backend → (X-Member-Lookup-Key) → Gate Backend
                                                ↓
                                        Return: { nama, status, is_aktif, no_hp_masked }

KENAPA DIPROXY (tidak langsung dari frontend)?
  - Shared secret GATE_LOOKUP_KEY tidak boleh terekspos di browser (VITE_* bisa dilihat publik)
  - UMKM Backend menyimpan secret aman di HuggingFace Spaces env vars
  - Frontend hanya perlu JWT UMKM yang sudah punya (dari login)

SETUP:
  Set GATE_LOOKUP_KEY di HuggingFace Spaces → UMKM Backend secrets.
  Nilai harus sama persis dengan MEMBER_LOOKUP_API_KEY di Gate Backend secrets.
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.deps import get_current_umkm

router = APIRouter(prefix="/api/member", tags=["Member Lookup"])


@router.get("/lookup")
async def lookup_member(
    uid: str = Query("", description="NFC UID dari kartu (hex string dari USB RFID reader)"),
    no_hp: str = Query("", description="Nomor HP member (fallback manual)"),
    _umkm: dict = Depends(get_current_umkm),
):
    """
    Verifikasi apakah pembeli adalah member aktif Peken Banyumasan.

    Endpoint ini menjadi perantara (proxy) antara aplikasi UMKM dan Gate Backend.
    UMKM user wajib sudah login (JWT) agar endpoint ini bisa dipanggil.

    Cara pakai:
    - Dengan USB RFID Reader keyboard emulator: UID kartu otomatis terisi di input
    - Tanpa NFC reader: kasir input nomor HP member secara manual

    Response sukses:
      { status: "success", data: { nama, status, is_aktif, no_hp_masked, lookup_by } }

    Response member tidak ditemukan:
      HTTP 404 { status: "error", message: "Member tidak ditemukan dalam sistem" }
    """
    # Cek konfigurasi
    if not settings.GATE_API_BASE_URL:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "message": "Layanan verifikasi member belum dikonfigurasi. Hubungi admin.",
            },
        )

    if not settings.GATE_LOOKUP_KEY:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "message": "Kunci autentikasi Gate belum dikonfigurasi. Set GATE_LOOKUP_KEY di env.",
            },
        )

    uid_clean = uid.strip()
    no_hp_clean = no_hp.strip()

    if not uid_clean and not no_hp_clean:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "error",
                "message": "Parameter uid (NFC UID) atau no_hp harus diisi",
            },
        )

    # Susun query params untuk Gate Backend
    params = {}
    if uid_clean:
        params["uid"] = uid_clean
    else:
        params["no_hp"] = no_hp_clean

    gate_url = f"{settings.GATE_API_BASE_URL.rstrip('/')}/api/members/lookup"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                gate_url,
                params=params,
                headers={"X-Member-Lookup-Key": settings.GATE_LOOKUP_KEY},
            )

        if resp.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail={"status": "error", "message": "Member tidak ditemukan dalam sistem"},
            )

        if resp.status_code == 401:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "error",
                    "message": "Autentikasi ke Gate Backend gagal. Pastikan GATE_LOOKUP_KEY sudah benar.",
                },
            )

        if not resp.is_success:
            raise HTTPException(
                status_code=502,
                detail={
                    "status": "error",
                    "message": "Gate Backend tidak merespons dengan benar. Coba lagi.",
                },
            )

        return resp.json()

    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail={"status": "error", "message": "Koneksi ke Gate Backend timeout. Coba lagi."},
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail={"status": "error", "message": "Gagal menghubungi Gate Backend."},
        )