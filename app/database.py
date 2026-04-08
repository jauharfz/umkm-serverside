from supabase import Client, create_client
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class SupabaseProxy:
    """
    Proxy tipis agar seluruh pemanggilan existing `db.supabase.*` tetap kompatibel.

    Desain ini sengaja mengambil client fresh pada setiap akses atribut. Di deployment
    Hugging Face / container yang sering idle, pendekatan ini jauh lebih stabil
    dibanding mempertahankan singleton lama yang rawan stale connection.
    """

    def __getattr__(self, name):
        return getattr(get_client(), name)


supabase = SupabaseProxy()


def _create_client() -> Client:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY wajib diisi di environment variables."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def init_db() -> Client:
    """Smoke-test koneksi saat startup."""
    client = _create_client()
    logger.info("Supabase client initialized successfully.")
    return client


def get_client(force_refresh: bool = False) -> Client:
    """
    Kembalikan Supabase client baru.

    `force_refresh` dipertahankan untuk kompatibilitas pemanggil lama, walau secara
    implementasi kedua mode sama-sama menghasilkan client baru demi menghindari
    stale connection pada koneksi yang lama idle.
    """
    _ = force_refresh
    return _create_client()


def reconnect() -> Client:
    """Alias eksplisit untuk mendapatkan client baru."""
    logger.warning("Recreating fresh Supabase client...")
    return _create_client()
