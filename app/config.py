from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_ANON_KEY: str = ""

    STORAGE_BUCKET_DOKUMEN: str = "dokumen-umkm"
    STORAGE_BUCKET_POSTER: str = "poster-promo"

    # ── Integrasi Gate Backend (untuk sinkronisasi event countdown) ──────────
    # Base URL Gate Backend, misal: https://xxx-gate-backend.hf.space
    # Endpoint /api/events/public akan di-append otomatis.
    # Kosongkan jika tidak ada integrasi → countdown tidak tampil.
    GATE_API_BASE_URL: str = ""

    # ── Admin Secret Key (service-to-service auth) ───────────────────────────
    # Digunakan oleh Gate Backend untuk memanggil endpoint admin UMKM.
    # Harus sama dengan UMKM_ADMIN_SECRET_KEY di Gate Backend (.env).
    # Buat dengan: python -c "import secrets; print(secrets.token_hex(32))"
    ADMIN_SECRET_KEY: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()