from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import app.database as db

security = HTTPBearer()

_credentials_exception = HTTPException(
    status_code=401,
    detail={
        "status": "error",
        "message": "Token tidak valid atau telah kadaluarsa. Silakan login kembali.",
    },
)


async def get_current_umkm(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Verifikasi token Bearer via Supabase Auth (sama dengan Gate Backend).
    Tidak ada decode manual JWT — Supabase Auth yang memvalidasi signature & expiry.
    Lookup umkm berdasarkan auth_id (FK ke auth.users.id).
    """
    token = credentials.credentials
    try:
        user_res = db.supabase.auth.get_user(token)
        if not user_res or not user_res.user:
            raise _credentials_exception
        auth_id = user_res.user.id
    except HTTPException:
        raise
    except Exception:
        raise _credentials_exception

    resp = (
        db.supabase.table("umkm")
        .select("*")
        .eq("auth_id", auth_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise _credentials_exception

    return resp.data[0]