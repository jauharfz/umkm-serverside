from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging

from app.config import settings
import app.database as db
from app.routers import auth, dashboard, stok, kas, promo, transaksi, notifikasi, profil, public
from app.routers import admin          # Router manajemen pendaftaran (Gate → UMKM)
from app.routers import member_lookup  # ← NEW: Proxy member lookup ke Gate Backend

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────
    logger.info("🚀 Menginisialisasi koneksi Supabase...")
    try:
        db.init_db()
        # Smoke test — pastikan koneksi berhasil
        db.supabase.table("umkm").select("id").limit(1).execute()
        logger.info("✅ Koneksi Supabase berhasil.")
    except RuntimeError as e:
        logger.error(f"❌ {e}")
        logger.warning("⚠️  Server tetap berjalan, namun endpoint database tidak akan berfungsi. Isi SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY.")
    except Exception as e:
        logger.error(f"❌ Gagal terhubung ke Supabase: {e}")

    yield

    # ── Shutdown ──────────────────────────────────────────────
    logger.info("👋 Server berhenti.")


app = FastAPI(
    title="API Sistem UMKM – Peken Banyumas 2026",
    description="""
RESTful API untuk Sistem Manajemen UMKM Peken Banyumas 2026.

Dibangun dengan **FastAPI (Python)** dan **Supabase (PostgreSQL)**.

## Autentikasi
Semua endpoint (kecuali `/api/auth/*` dan `/api/public/*`) memerlukan
JWT Token via header `Authorization: Bearer <token>`.

## Autentikasi Admin (Service-to-Service)
Endpoint `/api/admin/*` menggunakan `X-Admin-Key` header.
Key ini hanya diketahui oleh Gate Backend dan dikonfigurasi via env var
`ADMIN_SECRET_KEY`.

## Integrasi Gate
Endpoint `/api/public/tenant` dan `/api/public/diskon` adalah endpoint
**publik tanpa auth** yang dipanggil oleh backend Gate (REQ-INTEG-001).

Endpoint `/api/member/lookup` mem-proxy request verifikasi member ke Gate Backend.
UMKM user wajib login (JWT) untuk mengakses endpoint ini.
    """,
    version="1.0.0",
    contact={"name": "Tim Pengembang UMKM Peken Banyumas"},
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────
# Untuk produksi, ganti "*" dengan domain frontend yang spesifik
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://umkm-development.vercel.app",  # ← URL Vercel
        "http://localhost:5173",                  # untuk dev lokal
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global Exception Handler ──────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Terjadi kesalahan pada server. Silakan coba lagi."},
    )


# ── Routers ───────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(stok.router)
app.include_router(kas.router)
app.include_router(promo.router)
app.include_router(transaksi.router)
app.include_router(notifikasi.router)
app.include_router(profil.router)
app.include_router(public.router)
app.include_router(admin.router)          # Admin router (manajemen pendaftaran)
app.include_router(member_lookup.router)  # ← NEW: Member lookup proxy


# ── Health Check ──────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "ok",
        "service": "Backend UMKM – Peken Banyumas 2026",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    db_ok = False
    try:
        db.supabase.table("umkm").select("id").limit(1).execute()
        db_ok = True
    except Exception:
        pass
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
    }