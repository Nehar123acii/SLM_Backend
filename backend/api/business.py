"""
backend/api/business.py
=======================
FastAPI endpoints for Business Retention Status, Purge, and Dropped Tombstones:
- GET  /api/business/status
- POST /api/business/reset
- POST /api/dev/expire-now
- GET  /verify/dropped
- GET  /api/verify/dropped
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.config import is_kavach_dev
from backend.db.engine import engine
from backend.db.models import Base
from backend.services.purge import (
    get_business_status,
    list_tombstones,
    purge_business_data,
)

business_router = APIRouter(tags=["business"])


@business_router.get("/api/business/status", status_code=status.HTTP_200_OK)
def get_status_endpoint(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns business retention status:
    - last_activity, expires_at, days_left, warning (true when days_left <= 3)
    - prompt to export evidence pack when warning is true
    - labeled as Kavach operational retention setting (not statutory)
    """
    return get_business_status(db)


@business_router.post("/api/dev/expire-now", status_code=status.HTTP_200_OK)
def expire_now_endpoint(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Developer fast-path: immediately expires business retention and purges data.
    Works ONLY when KAVACH_DEV=1 (or setting kavach_dev=1), else returns 404.
    """
    if not is_kavach_dev():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint available only in developer mode (KAVACH_DEV=1).",
        )

    res = purge_business_data(session=db, reason="dev_expire_now")
    # Re-create empty schema so subsequent requests succeed
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass
    return res


@business_router.post("/api/business/reset", status_code=status.HTTP_200_OK)
def reset_business_endpoint(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    New business reset behavior: purges current business data, generates a tombstone,
    and re-initializes fresh empty database tables.
    """
    res = purge_business_data(session=db, reason="business_reset")
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass
    return res


@business_router.get("/verify/dropped", status_code=status.HTTP_200_OK)
@business_router.get("/api/verify/dropped", status_code=status.HTTP_200_OK)
def list_dropped_tombstones() -> List[Dict[str, Any]]:
    """
    Lists tombstones from data/dropped/ including date and ledger head hash.
    No personal data is retained.
    """
    return list_tombstones()
