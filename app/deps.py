from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from app.config import settings
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
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        umkm_id: str = payload.get("sub")
        if not umkm_id:
            raise _credentials_exception
    except JWTError:
        raise _credentials_exception

    resp = db.supabase.table("umkm").select("*").eq("id", umkm_id).maybe_single().execute()
    if not resp.data:
        raise _credentials_exception

    return resp.data
