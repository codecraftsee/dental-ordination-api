from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_settings

settings = get_settings()

connect_args = {}
engine_kwargs = {"pool_pre_ping": True}

if settings.database_url.startswith("postgresql"):
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
    finally:
        db.close()
