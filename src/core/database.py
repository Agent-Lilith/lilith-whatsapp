from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings
from core.models import Base

_db_url = settings.DATABASE_URL or ""
if _db_url.startswith("postgresql://") and "psycopg" not in _db_url:
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)

if _db_url:
    engine = create_engine(
        _db_url,
        pool_size=10,
        max_overflow=20,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    engine = None  # type: ignore[assignment]
    SessionLocal = None  # type: ignore[assignment]


def get_db() -> Generator[Session, None, None]:
    if engine is None or SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not set. Set it in .env or environment.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    if engine is None or SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not set. Set it in .env or environment.")
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
