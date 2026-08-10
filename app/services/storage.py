from functools import lru_cache
from supabase import create_client, Client
from app.config import get_settings


@lru_cache
def _client() -> Client:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env"
        )
    return create_client(s.supabase_url, s.supabase_service_key)


def upload_bytes(path: str, data: bytes, content_type: str) -> None:
    s = get_settings()
    _client().storage.from_(s.supabase_bucket).upload(
        path=path,
        file=data,
        file_options={"content-type": content_type, "upsert": "false"},
    )


def create_signed_url(path: str, expires_in: int = 3600) -> str:
    s = get_settings()
    res = _client().storage.from_(s.supabase_bucket).create_signed_url(path, expires_in)
    url = (res or {}).get("signedURL")
    if not url:
        # An error response has a different shape; indexing it blind raised a
        # bare KeyError that told nobody anything.
        raise RuntimeError(
            f"Supabase returned no signed URL for {path!r} in bucket "
            f"{s.supabase_bucket!r}: {res!r}"
        )
    return url


def delete(path: str) -> None:
    s = get_settings()
    _client().storage.from_(s.supabase_bucket).remove([path])
