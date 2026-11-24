"""SQLAlchemy engine/session lifecycle."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from .config import get_settings

_engine = None
_SessionLocal: sessionmaker | None = None


def _make_engine():
    s = get_settings()
    url = s.database_url
    kwargs: dict = {"echo": s.sql_echo, "future": True}
    if url.startswith("sqlite"):
        if ":///" in url:
            path = url.split(":///", 1)[1]
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
    eng = create_engine(url, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _set_pragma(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return eng


def get_engine():
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


def get_db() -> Iterator[OrmSession]:
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401

    models.Base.metadata.create_all(bind=get_engine())
    _migrate_sqlite()


def _migrate_sqlite() -> None:
    """Minimal additive migration for existing per-user SQLite databases.

    This project intentionally keeps a tiny, deterministic migration layer
    instead of shipping Alembic in the desktop bundle. It only adds columns
    and normalizes the legacy "none" real-name status.
    """
    from sqlalchemy import text

    url = get_settings().database_url
    if not url.startswith("sqlite"):
        return
    additions = {
        "domains": {
            "kind": "VARCHAR(16) DEFAULT 'external'",
            "stage": "VARCHAR(24) DEFAULT 'pending'",
            "provider": "VARCHAR(16) DEFAULT 'cloudflare'",
            "cloudflare_zone_id": "VARCHAR(64)",
            "cloudflare_record_id": "VARCHAR(64)",
            "tunnel_id": "VARCHAR(64)",
            "upstream_url": "VARCHAR(255) DEFAULT 'http://127.0.0.1:8080'",
            "ns_nameservers_json": "JSON DEFAULT '[]'",
            "ns_last_checked_at": "DATETIME",
            "last_error": "VARCHAR(500)",
        }
    }
    with get_engine().begin() as conn:
        for table, columns in additions.items():
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            }
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        # Old local-mode builds wrote "none"; the new public status is
        # "unverified". Do not touch active accounts here: activation must be
        # an explicit human-review action.
        conn.execute(text("UPDATE users SET realname_status='unverified' WHERE realname_status='none'"))


def reset_engine() -> None:
    """Test helper: drop cached engine (call after changing env)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def db_path_from_url(url: str) -> str | None:
    if url.startswith("sqlite:///"):
        return url.split(":///", 1)[1]
    return None
