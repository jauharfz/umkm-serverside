from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_ANON_KEY: str = ""

    SECRET_KEY: str = "change-this-secret-key-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24

    STORAGE_BUCKET_DOKUMEN: str = "dokumen-umkm"
    STORAGE_BUCKET_POSTER: str = "poster-promo"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
