from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import app.database as db
import logging

logger = logging.getLogger(__name__)
security = HTTPBearer()

_credentials_exception = HTTPException(
    status_code=401,
    detail={
        "status": "error",
        "message": "Token tidak valid atau telah kadaluarsa. Silakan login kembali.",
    },
)


def _get_user_from_token(token: str):
    """
    Verifikasi token via Supabase Auth.
    Jika gagal karena koneksi stale, coba reconnect sekali lalu retry.
    """
    client = db.get_client()
    try:
        user_res = client.auth.get_user(token)
        return user_res
    except Exception as e:
        err_str = str(e).lower()
        # Deteksi error yang bisa diselesaikan dengan reconnect
        reconnectable = any(kw in err_str for kw in [
            "connection", "timeout", "reset", "broken pipe", "eof",
            "network", "socket", "closed", "unreachable", "refused",
        ])
        if reconnectable:
            logger.warning(f"Supabase auth error (reconnectable): {e}. Attempting reconnect...")
            try:
                client = db.reconnect()
                user_res = client.auth.get_user(token)
                return user_res
            except Exception as retry_err:
                logger.error(f"Reconnect retry failed: {retry_err}")
                raise _credentials_exception
        # Non-reconnectable error (bad token, expired, etc.)
        raise _credentials_exception


async def get_current_umkm(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Verifikasi token Bearer via Supabase Auth.
    Tidak ada decode manual JWT — Supabase Auth yang memvalidasi signature & expiry.
    Lookup umkm berdasarkan auth_id (FK ke auth.users.id).
    Jika koneksi ke Supabase stale, reconnect otomatis.
    """
    token = credentials.credentials
    try:
        user_res = _get_user_from_token(token)
        if not user_res or not user_res.user:
            raise _credentials_exception
        auth_id = user_res.user.id
    except HTTPException:
        raise
    except Exception:
        raise _credentials_exception

    client = db.get_client()
    try:
        resp = (
            client.table("umkm")
            .select("*")
            .eq("auth_id", auth_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.warning(f"DB lookup failed during auth: {e}. Attempting reconnect...")
        try:
            client = db.reconnect()
            resp = (
                client.table("umkm")
                .select("*")
                .eq("auth_id", auth_id)
                .limit(1)
                .execute()
            )
        except Exception:
            raise _credentials_exception

    if not resp.data:
        raise _credentials_exception

    return resp.data[0]