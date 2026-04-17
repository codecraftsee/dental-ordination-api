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

    # Email — Mailtrap API
    mailtrap_api_token: str = ""
    mailtrap_inbox_id: str = ""  # sandbox only; leave empty for production sending
    smtp_from: str = "noreply@dentalclinic.com"

    # Frontend base URL used to build invite links
    frontend_url: str = "http://localhost:4200"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
