"""
Autoanosis Exams Module — Database Session Factory
Supports PostgreSQL (Neon/Supabase, production) and SQLite (local dev).
DATABASE_URL env var controls which backend is used.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Connection URL — falls back to local SQLite for local dev / CI
# ---------------------------------------------------------------------------
_RAW_URL = os.environ.get("DATABASE_URL", "sqlite:///./autoanosis_exams.db")

# asyncpg URLs are not compatible with psycopg2 — rewrite driver scheme
if _RAW_URL.startswith("postgresql+asyncpg://"):
    _RAW_URL = _RAW_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    _RAW_URL = _RAW_URL.replace("?ssl=true", "?sslmode=require")

DATABASE_URL = _RAW_URL
_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        future=True,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        future=True,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    """Yields a SQLAlchemy session; closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Create all ORM-mapped tables (safe no-op if they already exist).
    For PostgreSQL the canonical schema lives in
    database/001_create_exams_tables.sql — this is a safety net for SQLite dev.
    """
    from exams_module.db.base import Base  # noqa: F401
    import exams_module.models.exam_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
