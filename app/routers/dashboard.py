from fastapi import APIRouter, Depends
from datetime import date, datetime, timedelta, timezone
from app.deps import get_current_umkm
import app.database as db

router = APIRouter(prefix="/api", tags=["Dashboard"])

WIB = timezone(timedelta(hours=7))


@router.get("/dashboard")
async def get_dashboard(umkm: dict = Depends(get_current_umkm)):
    umkm_id = umkm["id"]
    today = datetime.now(WIB).date()
    today_str = today.isoformat()

    # ── Total produk ──────────────────────────────────────────
    barang_resp = db.supabase.table("barang").select("*").eq("umkm_id", umkm_id).execute()
    all_barang = barang_resp.data or []
    total_produk = len(all_barang)
    stok_kritis = sum(1 for b in all_barang if b["stok"] <= 5)

    # ── Transaksi hari ini ────────────────────────────────────
    trx_resp = (
        db.supabase.table("transaksi")
        .select("*")
        .eq("umkm_id", umkm_id)
        .gte("waktu", f"{today_str}T00:00:00+07:00")
        .lte("waktu", f"{today_str}T23:59:59+07:00")
        .execute()
    )
    today_trx = trx_resp.data or []
    omset_hari_ini = sum(t["total"] for t in today_trx if t["status"] == "Selesai")
    transaksi_hari_ini = len(today_trx)

    # ── Chart 7 hari terakhir ─────────────────────────────────
    hari_labels = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"]
    chart_data = []
    for i in range(6, -1, -1):
        d = (datetime.now(WIB) - timedelta(days=i)).date()
        d_str = d.isoformat()
        day_label = hari_labels[d.weekday() + 1 if d.weekday() < 6 else 0]
        # weekday() returns 0=Mon … 6=Sun, kita pakai label Bahasa Indonesia
        day_label = _day_label(d)
        trx_day = (
            db.supabase.table("transaksi")
            .select("total, status")
            .eq("umkm_id", umkm_id)
            .gte("waktu", f"{d_str}T00:00:00+07:00")
            .lte("waktu", f"{d_str}T23:59:59+07:00")
            .execute()
        )
        rows = trx_day.data or []
        pendapatan = sum(r["total"] for r in rows if r["status"] == "Selesai")
        chart_data.append({
            "label": day_label,
            "pendapatan": pendapatan,
            "jumlah_transaksi": len(rows),
        })

    # ── 5 Transaksi terakhir ──────────────────────────────────
    last5_resp = (
        db.supabase.table("transaksi")
        .select("*")
        .eq("umkm_id", umkm_id)
        .order("waktu", desc=True)
        .limit(5)
        .execute()
    )
    kiosk_label = f"{umkm['nama_usaha']} · Stand {umkm.get('nomor_stand', '-')}"
    transaksi_terakhir = [_fmt_trx(t, kiosk_label) for t in (last5_resp.data or [])]

    # ── Ringkasan stok ────────────────────────────────────────
    ringkasan_stok = [_fmt_barang(b) for b in all_barang]

    return {
        "status": "success",
        "data": {
            "stats": {
                "total_produk": total_produk,
                "omset_hari_ini": omset_hari_ini,
                "transaksi_hari_ini": transaksi_hari_ini,
                "stok_kritis": stok_kritis,
            },
            "chart_penjualan": chart_data,
            "transaksi_terakhir": transaksi_terakhir,
            "ringkasan_stok": ringkasan_stok,
        },
    }


def _day_label(d: date) -> str:
    labels = {0: "Sen", 1: "Sel", 2: "Rab", 3: "Kam", 4: "Jum", 5: "Sab", 6: "Min"}
    return labels[d.weekday()]


def _fmt_barang(b: dict) -> dict:
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


def _fmt_trx(t: dict, kiosk: str) -> dict:
    return {
        "id": t["id"],
        "customer": t.get("customer"),
        "item": t.get("item"),
        "total": t["total"],
        "time": t["waktu"],
        "status": t["status"],
        "kiosk": kiosk,
    }
