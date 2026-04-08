from supabase import create_client, Client
from app.config import settings
import logging
import threading

logger = logging.getLogger(__name__)

# Singleton client + lock untuk thread safety
supabase: Client = None
_lock = threading.Lock()


def _create_client() -> Client:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY wajib diisi di environment variables."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def init_db():
    """Inisialisasi singleton Supabase client. Dipanggil saat startup."""
    global supabase
    with _lock:
        supabase = _create_client()


def get_client() -> Client:
    """
    Kembalikan singleton Supabase client.
    Jika client None (belum init atau setelah reconnect), buat baru.
    Ini adalah safety-net — seharusnya init_db() sudah dipanggil saat startup.
    """
    global supabase
    if supabase is None:
        with _lock:
            if supabase is None:
                logger.warning("Supabase client None — reinitializing...")
                try:
                    supabase = _create_client()
                    logger.info("Supabase client reinitialized successfully.")
                except Exception as e:
                    logger.error(f"Failed to reinitialize Supabase client: {e}")
                    raise
    return supabase


def reconnect() -> Client:
    """
    Paksa buat ulang koneksi Supabase. Dipanggil saat koneksi terdeteksi stale/error.
    Return client baru.
    """
    global supabase
    with _lock:
        logger.warning("Reconnecting to Supabase...")
        try:
            supabase = _create_client()
            logger.info("Supabase reconnected successfully.")
            return supabase
        except Exception as e:
            logger.error(f"Supabase reconnect failed: {e}")
            raise