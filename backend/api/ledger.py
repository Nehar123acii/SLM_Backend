import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.db.models import LedgerEvent
from backend.services.ledger import repair_event, tamper_event, verify_chain

router = APIRouter(tags=["ledger"])


class TamperRequest(BaseModel):
    seq: int


class RepairRequest(BaseModel):
    seq: Optional[int] = None


@router.get("/api/ledger")
def get_ledger_events(db: Session = Depends(get_db)):
    """Returns all append-only cryptographic ledger events in order."""
    events = db.query(LedgerEvent).order_by(LedgerEvent.seq.asc()).all()
    return [
        {
            "seq": ev.seq,
            "ts": ev.ts,
            "type": ev.type,
            "event_type": ev.event_type,
            "payload_json": ev.payload_json,
            "prev_hash": ev.prev_hash,
            "hash": ev.hash,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in events
    ]


@router.get("/api/ledger/verify")
def get_ledger_verification(db: Session = Depends(get_db)):
    """Verifies the hash chain from Genesis to Head."""
    return verify_chain(db)


@router.post("/api/dev/tamper")
def dev_tamper_ledger(payload: TamperRequest, db: Session = Depends(get_db)):
    """Dev-only: tampers with a ledger event payload without updating hash. Available only when KAVACH_DEV=1."""
    if os.environ.get("KAVACH_DEV") != "1":
        raise HTTPException(status_code=404, detail="Endpoint not found")
    return tamper_event(db, payload.seq)


@router.post("/api/dev/repair")
def dev_repair_ledger(payload: Optional[RepairRequest] = None, db: Session = Depends(get_db)):
    """Dev-only: repairs tampered ledger event(s) from backup. Available only when KAVACH_DEV=1."""
    if os.environ.get("KAVACH_DEV") != "1":
        raise HTTPException(status_code=404, detail="Endpoint not found")
    target_seq = payload.seq if payload else None
    return repair_event(db, target_seq)
