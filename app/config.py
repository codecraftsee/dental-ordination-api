from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:password@localhost:5432/dental_ordination"
    secret_key: str = "your-super-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS
    allowed_origins: str = "http://localhost:4200,https://codecraftsee.github.io,https://dental-ordination.vercel.app"

    # Email — Resend
    resend_api_key: str = ""
    email_from: str = "onboarding@resend.dev"

    # Frontend base URL used to build invite links
    frontend_url: str = "http://localhost:4200"

    # Supabase Storage (for patient document uploads)
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_bucket: str = "patient-documents"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
