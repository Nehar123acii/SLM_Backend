import os
import tempfile
import pytest
from sqlalchemy import create_engine, text
from backend.config import settings
from backend.db.engine import engine, dispose_engine, _set_sqlite_pragmas


def test_engine_url_starts_with_sqlite():
    """Verify that backend settings and DB engine use SQLite."""
    assert settings.database_url.startswith("sqlite")
    assert engine.url.drivername.startswith("sqlite")


def test_foreign_keys_pragma_enabled():
    """Verify that foreign keys PRAGMA is enabled (1) on connections."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1


def test_journal_mode_is_wal_on_disk():
    """Verify that journal_mode is WAL for SQLite file databases."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_db_path = os.path.join(tmp_dir, "test_wal.db").replace("\\", "/")
        tmp_engine = create_engine(
            f"sqlite:///{tmp_db_path}",
            connect_args={"check_same_thread": False},
        )
        try:
            with tmp_engine.connect() as conn:
                mode = conn.execute(text("PRAGMA journal_mode")).scalar()
                assert str(mode).lower() == "wal"
        finally:
            tmp_engine.dispose()


def test_tests_do_not_touch_data_kavach_db(engine):
    """Verify that the test engine fixture uses in-memory SQLite, never data/kavach.db."""
    test_db_url = str(engine.url)
    assert "data/kavach.db" not in test_db_url
    assert ":memory:" in test_db_url or "%3Amemory%3A" in test_db_url


def test_dispose_engine():
    """Verify that dispose_engine cleans up connections without error."""
    dispose_engine()
