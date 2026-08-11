from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

connect_args = {}
engine_kwargs = {"pool_pre_ping": True}

if settings.database_url.startswith("postgresql"):
    host = (urlparse(settings.database_url).hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        connect_args["sslmode"] = "require"
    engine_kwargs.update({"pool_size": 5, "max_overflow": 10})

if connect_args:
    engine_kwargs["connect_args"] = connect_args

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # Roll back once, here, instead of in every endpoint that writes.
        # Without this a failed write leaves the session in a broken state for
        # whatever else runs in the same request.
        db.rollback()
        raise
    finally:
        db.close()
