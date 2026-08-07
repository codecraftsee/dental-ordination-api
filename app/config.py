from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

# Kept as a named constant so the guard below can recognise it. Any deployment
# still carrying this value is signing JWTs with a string that is public in the
# repository, which means anyone can forge an admin token.
DEFAULT_SECRET_KEY = "your-super-secret-key-change-in-production"


class Settings(BaseSettings):
    # Which environment this instance is running as: local | preprod | production
    app_env: str = "local"

    database_url: str = "postgresql://postgres:password@localhost:5432/dental_ordination"
    secret_key: str = DEFAULT_SECRET_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS. Local-dev fallback only — every deployed environment sets this
    # explicitly (see .env.preprod.example). Deployment hostnames are kept out
    # of the default so a retired host cannot keep CORS access by accident.
    allowed_origins: str = "http://localhost:4200"

    # Email — Resend
    resend_api_key: str = ""
    email_from: str = "onboarding@resend.dev"

    # Frontend base URL used to build invite links
    frontend_url: str = "http://localhost:4200"

    # Supabase Storage (for patient document uploads)
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_bucket: str = "patient-documents"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _require_a_real_secret_key_outside_local(self) -> "Settings":
        """Refuse to start a deployed instance with an unset or default signing key.

        Failing loudly at boot is the point: the alternative is an instance that
        looks healthy while accepting forged tokens.
        """
        if self.app_env.lower() == "local":
            return self
        if self.secret_key and self.secret_key != DEFAULT_SECRET_KEY:
            return self
        raise ValueError(
            f"SECRET_KEY is unset or still the built-in default while APP_ENV="
            f"{self.app_env!r}. Anyone could forge an admin token. Generate one with:\n"
            '  python3 -c "import secrets; print(secrets.token_urlsafe(64))"\n'
            "and set SECRET_KEY in this environment's .env (on the server: /opt/dental/.env)."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
