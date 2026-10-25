"""
backend/services/purge.py
=========================
Business Data Retention and Purge Service for Kavach DPDP Assistant.
Enforces configurable business retention (KAVACH_RETENTION_DAYS), generates
audit tombstones in data/dropped/<timestamp>.json with head_hash and DB SHA-256,
disposes engine connections to release Windows file locks, and purges SQLite
databases, upload temp directories, and data/out exports.
Zero personal data retained in tombstones.
"""

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.engine import dispose_engine
from backend.db.models import (
    BreachSimulation,
    BusinessState,
    Column,
    Dataset,
    ErasurePlan,
    LedgerEvent,
    Person,
    RightsCase,
)
from backend.services.ledger import get_head_hash


_TEST_CLOCK: Optional[datetime.datetime] = None


def set_test_clock(dt: Optional[datetime.datetime]) -> None:
    """Sets an injectable mock clock for tests."""
    global _TEST_CLOCK
    _TEST_CLOCK = dt


def get_test_clock() -> Optional[datetime.datetime]:
    global _TEST_CLOCK
    return _TEST_CLOCK


def get_now() -> datetime.datetime:
    """Returns current UTC datetime, respecting the injectable clock if set."""
    global _TEST_CLOCK
    if _TEST_CLOCK is not None:
        if _TEST_CLOCK.tzinfo is None:
            return _TEST_CLOCK.replace(tzinfo=datetime.timezone.utc)
        return _TEST_CLOCK
    return datetime.datetime.now(datetime.timezone.utc)


def touch_activity(session: Session, dt: Optional[datetime.datetime] = None) -> datetime.datetime:
    """
    Updates the business last_activity heartbeat timestamp.
    Called on upload, questionnaire answer, case action, and evidence export.
    """
    now = dt or get_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)

    state = session.query(BusinessState).first()
    if not state:
        state = BusinessState(last_activity=now, created_at=now)
        session.add(state)
    else:
        state.last_activity = now
    session.commit()
    return now


def get_business_status(session: Session, now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """
    Returns business retention status:
    - last_activity
    - retention_days
    - expires_at
    - days_left
    - warning (true when days_left <= 3)
    - prompt to export evidence pack when warning is true
    """
    current_time = now or get_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=datetime.timezone.utc)

    retention_days = int(getattr(settings, "kavach_retention_days", 15))

    state = session.query(BusinessState).first()
    if not state or not state.last_activity:
        touch_activity(session, current_time)
        state = session.query(BusinessState).first()

    last_act = state.last_activity if state else current_time
    if last_act.tzinfo is None:
        last_act = last_act.replace(tzinfo=datetime.timezone.utc)

    expires_at = last_act + datetime.timedelta(days=retention_days)

    remaining_seconds = (expires_at - current_time).total_seconds()
    if remaining_seconds <= 0:
        days_left = 0
    else:
        days_left = int(round(remaining_seconds / 86400.0))

    warning = days_left <= 3
    prompt = (
        "Data retention window expiring soon. Please export your compliance evidence pack before business data is purged."
        if warning
        else None
    )

    return {
        "last_activity": last_act.isoformat(),
        "retention_days": retention_days,
        "expires_at": expires_at.isoformat(),
        "days_left": days_left,
        "warning": warning,
        "prompt": prompt,
        "label": "Kavach operational retention setting (not statutory)",
        "note": "Configurable retention period from last activity, not a legal mandate. No legal citation.",
    }


def get_sqlite_db_path() -> Optional[str]:
    """Resolves local absolute SQLite database file path from settings."""
    url = settings.database_url
    if not url or not url.startswith("sqlite"):
        return None
    if url == "sqlite:///:memory:":
        return None
    clean_path = url.replace("sqlite:///", "")
    return os.path.abspath(clean_path)


def purge_business_data(
    session: Optional[Session] = None,
    now: Optional[datetime.datetime] = None,
    reason: str = "retention_expired",
) -> Dict[str, Any]:
    """
    Executes a complete business-level purge:
    1. Collects summary counts and ledger head_hash from the active session.
    2. Writes data/dropped/<timestamp>.json tombstone with counts, DB SHA-256, and head_hash.
    3. Calls dispose_engine() to release Windows file locks.
    4. Deletes the SQLite database file and associated -wal and -shm files.
    5. Empties uploads_temp directory and removes data/out.
    6. Leaves data/.key intact unless requested.
    """
    now_utc = now or get_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)
    ts_str = now_utc.strftime("%Y%m%dT%H%M%SZ")

    # Step 1: Collect counts and head_hash
    datasets_count = 0
    records_count = 0
    columns_count = 0
    people_count = 0
    cases_count = 0
    plans_count = 0
    breach_simulations_count = 0
    ledger_events_count = 0
    head_hash = "0" * 64

    bind_engine = None
    if session:
        try:
            datasets_count = session.query(Dataset).count()
            records_count = sum(d.row_count or 0 for d in session.query(Dataset).all())
            columns_count = session.query(Column).count()
            people_count = session.query(Person).count()
            cases_count = session.query(RightsCase).count()
            plans_count = session.query(ErasurePlan).count()
            breach_simulations_count = session.query(BreachSimulation).count()
            ledger_events_count = session.query(LedgerEvent).count()
            head_hash = get_head_hash(session)
        except Exception:
            pass

        try:
            session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        except Exception:
            pass

        try:
            bind_engine = getattr(session, "bind", None)
        except Exception:
            pass

        try:
            session.close()
        except Exception:
            pass

    if bind_engine is not None and hasattr(bind_engine, "dispose"):
        try:
            bind_engine.dispose()
        except Exception:
            pass

    dispose_engine()
    import gc
    import time
    gc.collect()

    # Step 2: Compute DB SHA-256 before deletion
    db_path = get_sqlite_db_path()
    db_sha256 = ""
    if db_path and os.path.exists(db_path):
        try:
            h = hashlib.sha256()
            with open(db_path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            db_sha256 = h.hexdigest()
        except Exception:
            db_sha256 = ""

    # Step 3: Write tombstone JSON
    dropped_dir = os.path.join(settings.kavach_data_dir, "dropped")
    os.makedirs(dropped_dir, exist_ok=True)
    tombstone_filename = f"{ts_str}.json"
    tombstone_path = os.path.join(dropped_dir, tombstone_filename)

    tombstone = {
        "tombstone_version": "1.0",
        "dropped_at": now_utc.isoformat(),
        "reason": reason,
        "counts": {
            "datasets_count": datasets_count,
            "records_count": records_count,
            "columns_count": columns_count,
            "people_count": people_count,
            "cases_count": cases_count,
            "plans_count": plans_count,
            "breach_simulations_count": breach_simulations_count,
            "ledger_events_count": ledger_events_count,
        },
        "db_sha256": db_sha256,
        "head_hash": head_hash,
        "ledger_head_hash": head_hash,
        "note": "Operational tombstone. Zero personal data retained.",
    }

    with open(tombstone_path, "w", encoding="utf-8") as f:
        json.dump(tombstone, f, indent=2)

    # Step 4: Dispose SQLAlchemy engine to release locks
    dispose_engine()

    # Step 5: Delete SQLite database file, -wal, and -shm
    if db_path and os.path.exists(db_path):
        for _ in range(10):
            try:
                os.remove(db_path)
                break
            except Exception:
                time.sleep(0.05)

        for extra_ext in ("-wal", "-shm"):
            extra_file = db_path + extra_ext
            if os.path.exists(extra_file):
                for _ in range(5):
                    try:
                        os.remove(extra_file)
                        break
                    except Exception:
                        time.sleep(0.05)

    # Step 6: Clear uploads_temp contents
    if os.path.exists(settings.upload_temp_dir):
        for item in os.listdir(settings.upload_temp_dir):
            item_path = os.path.join(settings.upload_temp_dir, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
            except Exception:
                pass

    # Step 7: Clear data/out contents
    out_dir = os.path.join(settings.kavach_data_dir, "out")
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)

    return {
        "status": "purged",
        "tombstone": tombstone,
        "tombstone_path": tombstone_path,
        "tombstone_filename": tombstone_filename,
    }


def check_and_purge_if_expired(
    session: Session,
    now: Optional[datetime.datetime] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Checks if business retention has expired (days_left <= 0).
    If expired, purges data and returns (True, tombstone_path).
    Otherwise returns (False, None).
    """
    current_time = now or get_now()
    status = get_business_status(session, current_time)
    if status["days_left"] <= 0:
        res = purge_business_data(session=session, now=current_time, reason="retention_expired")
        return True, res.get("tombstone_path")
    return False, None


def list_tombstones() -> List[Dict[str, Any]]:
    """Lists dropped tombstones with date and head hash."""
    dropped_dir = os.path.join(settings.kavach_data_dir, "dropped")
    if not os.path.exists(dropped_dir):
        return []

    items = []
    for fn in sorted(os.listdir(dropped_dir), reverse=True):
        if fn.endswith(".json"):
            p = os.path.join(dropped_dir, fn)
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items.append({
                    "filename": fn,
                    "date": data.get("dropped_at"),
                    "dropped_at": data.get("dropped_at"),
                    "head_hash": data.get("head_hash") or data.get("ledger_head_hash"),
                    "db_sha256": data.get("db_sha256"),
                    "counts": data.get("counts", {}),
                })
            except Exception:
                pass
    return items
