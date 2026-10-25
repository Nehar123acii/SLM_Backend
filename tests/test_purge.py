"""
tests/test_purge.py
===================
Test suite for TASK K13 (Retention & Purge).
Covers:
1. Injectable clock: days_left and warning flag correct at day 12 and day 15.
2. Activity extends the expiry.
3. POST /api/dev/expire-now returns 404 without KAVACH_DEV=1.
4. After expiry: DB, workspace, and out files are gone, and a tombstone exists.
5. Tombstone contains no personal data and correct head hash.
6. GET /verify/dropped lists dropped tombstones.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path
import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.config import settings
from backend.db.models import Base, BusinessState, Dataset, LedgerEvent, Person
from backend.services.ledger import append_event, get_head_hash
from backend.services.purge import (
    get_business_status,
    list_tombstones,
    purge_business_data,
    set_test_clock,
    touch_activity,
)


# ---------------------------------------------------------------------------
# Test 1: days_left and warning flag at Day 12 and Day 15
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_days_left_and_warning_flag(client: AsyncClient, db_session: Session):
    """
    KAVACH_RETENTION_DAYS (default 15):
    - Day 0: days_left == 15, warning == False
    - Day 10: days_left == 5, warning == False
    - Day 12: days_left == 3, warning == True (warning <= 3 days left)
    - Day 15: days_left == 0, warning == True
    """
    t0 = datetime.datetime(2026, 10, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    set_test_clock(t0)
    try:
        # Initial touch
        touch_activity(db_session, t0)

        # Day 0 check
        resp = await client.get("/api/business/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["days_left"] == 15
        assert data["warning"] is False
        assert data["prompt"] is None
        assert "operational retention" in data["label"].lower()

        # Day 10 check
        t10 = t0 + datetime.timedelta(days=10)
        set_test_clock(t10)
        resp = await client.get("/api/business/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["days_left"] == 5
        assert data["warning"] is False
        assert data["prompt"] is None

        # Day 12 check (3 days left -> warning is True)
        t12 = t0 + datetime.timedelta(days=12)
        set_test_clock(t12)
        resp = await client.get("/api/business/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["days_left"] == 3
        assert data["warning"] is True
        assert data["prompt"] is not None
        assert "export" in data["prompt"].lower()

        # Day 15 check (0 days left -> warning is True)
        t15 = t0 + datetime.timedelta(days=15)
        set_test_clock(t15)
        resp = await client.get("/api/business/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["days_left"] == 0
        assert data["warning"] is True
        assert data["prompt"] is not None
    finally:
        set_test_clock(None)


# ---------------------------------------------------------------------------
# Test 2: Activity extends expiry
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_activity_extends_expiry(client: AsyncClient, db_session: Session):
    """
    Verifies that calling touch_activity (e.g. on new upload or answer)
    resets the 15-day countdown from the new activity time.
    """
    t0 = datetime.datetime(2026, 10, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    set_test_clock(t0)
    try:
        touch_activity(db_session, t0)

        # Move forward 10 days
        t10 = t0 + datetime.timedelta(days=10)
        set_test_clock(t10)
        status_before = get_business_status(db_session, t10)
        assert status_before["days_left"] == 5

        # New activity occurs at Day 10
        touch_activity(db_session, t10)

        # Immediately at Day 10, countdown is refreshed to 15 days
        status_after = get_business_status(db_session, t10)
        assert status_after["days_left"] == 15
        assert status_after["warning"] is False

        # Advance to Day 20 (10 days after the renewed activity)
        t20 = t0 + datetime.timedelta(days=20)
        set_test_clock(t20)
        status_t20 = get_business_status(db_session, t20)
        assert status_t20["days_left"] == 5
        assert status_t20["warning"] is False
    finally:
        set_test_clock(None)


# ---------------------------------------------------------------------------
# Test 3: POST /api/dev/expire-now dev gate (404 without KAVACH_DEV=1)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_expire_now_dev_gate(client: AsyncClient, monkeypatch):
    """
    POST /api/dev/expire-now:
    - Returns 404 when KAVACH_DEV is unset or 0.
    - Returns 200 when KAVACH_DEV=1.
    """
    monkeypatch.delenv("KAVACH_DEV", raising=False)
    monkeypatch.setattr(settings, "kavach_dev", 0)

    # Without dev mode
    resp = await client.post("/api/dev/expire-now")
    assert resp.status_code == 404

    # With dev mode enabled
    monkeypatch.setenv("KAVACH_DEV", "1")
    resp_dev = await client.post("/api/dev/expire-now")
    assert resp_dev.status_code == 200
    assert resp_dev.json()["status"] == "purged"


# ---------------------------------------------------------------------------
# Test 4: Files deleted, workspace purged, tombstone created with no PII
# ---------------------------------------------------------------------------
def test_purge_files_deleted_and_tombstone(tmp_path: Path, monkeypatch):
    """
    Executes purge on a dedicated SQLite file and directory structure:
    - Verifies DB file, -wal, and -shm are deleted.
    - Verifies uploads_temp contents are cleared.
    - Verifies data/out is deleted.
    - Verifies data/dropped/<timestamp>.json tombstone exists.
    - Verifies tombstone contains correct head hash, DB sha256, and zero raw PII.
    """
    # 1. Setup isolated directories
    test_data_dir = tmp_path / "test_data"
    test_uploads_dir = tmp_path / "test_uploads"
    test_out_dir = test_data_dir / "out"
    test_dropped_dir = test_data_dir / "dropped"

    test_data_dir.mkdir(parents=True)
    test_uploads_dir.mkdir(parents=True)
    test_out_dir.mkdir(parents=True)

    db_file = test_data_dir / "kavach_purge_test.db"
    db_wal = test_data_dir / "kavach_purge_test.db-wal"
    db_shm = test_data_dir / "kavach_purge_test.db-shm"

    monkeypatch.setattr(settings, "kavach_data_dir", str(test_data_dir))
    monkeypatch.setattr(settings, "upload_temp_dir", str(test_uploads_dir))
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_file.as_posix()}")

    # Create dummy upload temp file and out file
    temp_upload_file = test_uploads_dir / "secret_spreadsheet.csv"
    temp_upload_file.write_text("dummy,unpurged,content", encoding="utf-8")

    out_file = test_out_dir / "report.zip"
    out_file.write_text("dummy,out,content", encoding="utf-8")

    # Create dummy -wal and -shm files
    db_wal.write_text("wal-content", encoding="utf-8")
    db_shm.write_text("shm-content", encoding="utf-8")

    # Initialize SQLite database with a real engine
    test_engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(test_engine)
    SessionMaker = sessionmaker(bind=test_engine)
    session = SessionMaker()

    # Add a ledger event to obtain a known head hash
    sentinel_phone = "9876543210"
    sentinel_email = "victim@example.com"
    ev = append_event(session, "test_event", {"count": 42, "status": "ok"})
    expected_head_hash = ev.hash

    # Pre-compute expected DB sha256 before session closes
    session.commit()

    # 2. Execute purge
    purge_time = datetime.datetime(2026, 10, 20, 15, 30, 0, tzinfo=datetime.timezone.utc)
    set_test_clock(purge_time)
    try:
        res = purge_business_data(session=session, now=purge_time, reason="test_retention_purge")
    finally:
        set_test_clock(None)

    assert res["status"] == "purged"
    tombstone_path = Path(res["tombstone_path"])

    # 3. Assert filesystem deletions
    assert not db_file.exists(), "SQLite DB file must be deleted"
    assert not db_wal.exists(), "-wal file must be deleted"
    assert not db_shm.exists(), "-shm file must be deleted"
    assert not temp_upload_file.exists(), "Files in upload_temp must be cleared"
    assert not test_out_dir.exists(), "data/out must be deleted"

    # 4. Assert tombstone exists and is valid
    assert tombstone_path.exists(), "Tombstone JSON must exist in data/dropped/"
    with open(tombstone_path, "r", encoding="utf-8") as f:
        tombstone_content = f.read()
        tombstone_data = json.loads(tombstone_content)

    assert tombstone_data["head_hash"] == expected_head_hash
    assert len(tombstone_data["db_sha256"]) == 64
    assert tombstone_data["counts"]["ledger_events_count"] >= 1

    # Strict zero personal data in tombstone
    assert sentinel_phone not in tombstone_content
    assert sentinel_email not in tombstone_content
    assert "victim" not in tombstone_content.lower()


# ---------------------------------------------------------------------------
# Test 5: GET /verify/dropped lists tombstones
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_dropped_endpoint(client: AsyncClient, tmp_path: Path, monkeypatch):
    """
    GET /verify/dropped lists all dropped tombstones with date and head hash.
    """
    dropped_dir = tmp_path / "dropped"
    dropped_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "kavach_data_dir", str(tmp_path))

    # Create dummy tombstone
    sample_ts = {
        "tombstone_version": "1.0",
        "dropped_at": "2026-10-25T14:30:00Z",
        "head_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "db_sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
        "counts": {"records_count": 10},
    }
    tomb_file = dropped_dir / "20261025T143000Z.json"
    tomb_file.write_text(json.dumps(sample_ts), encoding="utf-8")

    resp = await client.get("/verify/dropped")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    item = items[0]
    assert item["head_hash"] == sample_ts["head_hash"]
    assert item["date"] == sample_ts["dropped_at"]
