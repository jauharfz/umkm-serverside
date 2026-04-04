from supabase import create_client, Client
from app.config import settings


def get_client() -> Client:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY wajib diisi di environment variables."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


# Singleton client — di-init saat startup
supabase: Client = None


def init_db():
    global supabase
    supabase = get_client()
