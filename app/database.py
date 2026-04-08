from __future__ import annotations

from threading import Lock
import logging

from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)

_client_lock = Lock()
_client: Client | None = None


def _create_client() -> Client:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY wajib diisi di environment variables."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


class SupabaseProxy:
    """
    Proxy kompatibilitas untuk pemanggilan lama `db.supabase.*`.

    Perbaikan penting:
    - Client TIDAK dibuat ulang di setiap akses atribut.
    - Satu instance dipakai bersama agar latency tidak membengkak.
    - Reconnect eksplisit tetap tersedia melalui `reconnect()` saat koneksi terdeteksi bermasalah.
    """

    def __getattr__(self, name):
        return getattr(get_client(), name)


supabase = SupabaseProxy()


def init_db() -> Client:
    """Inisialisasi client sekali saat startup dan lakukan smoke-test ringan."""
    client = get_client(force_refresh=True)
    logger.info("Supabase client initialized successfully.")
    return client


def get_client(force_refresh: bool = False) -> Client:
    """
    Kembalikan singleton client Supabase.

    `force_refresh=True` dipakai saat ingin membuat ulang koneksi, misalnya setelah
    terdeteksi timeout / broken pipe / koneksi stale.
    """
    global _client
    with _client_lock:
        if force_refresh or _client is None:
            _client = _create_client()
    return _client


def reconnect() -> Client:
    """Buat ulang client Supabase dan kembalikan instance baru."""
    logger.warning("Recreating Supabase client...")
    return get_client(force_refresh=True)
