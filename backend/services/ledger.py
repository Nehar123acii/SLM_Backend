import datetime
import hashlib
import json
import re
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.db.models import LedgerEvent, LedgerTamperBackup

GENESIS_PREV_HASH = "0" * 64

# Regex patterns for payload guard
_PHONE_PATTERN = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{9}\b|\b\d{10}\b")
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_AADHAAR_PATTERN = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")


def canonical_payload_json(payload: dict) -> str:
    """Return canonically serialized JSON (sorted keys, compact separators, UTF-8)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_entry_hash(prev_hash: str, ts: str, event_type: str, payload_json: str) -> str:
    """Compute plain SHA-256 over prev_hash + '|' + ts + '|' + type + '|' + payload_json."""
    raw = f"{prev_hash}|{ts}|{event_type}|{payload_json}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def check_payload_guard(payload: dict) -> None:
    """
    Rejects any payload containing a phone-like, email-like, Aadhaar-like, PAN-like value
    or a free-text field. Payloads may hold only IDs, counts, hashes, enum strings, and timestamps.
    """
    strings_to_check: List[str] = []

    def _collect(val: Any) -> None:
        if isinstance(val, str):
            strings_to_check.append(val)
        elif isinstance(val, dict):
            for k, v in val.items():
                if isinstance(k, str):
                    strings_to_check.append(k)
                _collect(v)
        elif isinstance(val, (list, tuple, set)):
            for item in val:
                _collect(item)

    _collect(payload)

    for s in strings_to_check:
        clean = s.strip()
        if not clean:
            continue

        # Check Aadhaar
        if _AADHAAR_PATTERN.search(clean):
            # Check if it has 12 consecutive/spaced digits
            digits = re.sub(r"\D", "", clean)
            if len(digits) == 12:
                raise ValueError(f"Personal data detected in ledger payload (Aadhaar pattern): '{s}'")

        # Check PAN
        if _PAN_PATTERN.search(clean):
            raise ValueError(f"Personal data detected in ledger payload (PAN pattern): '{s}'")

        # Check Email
        if _EMAIL_PATTERN.search(clean):
            raise ValueError(f"Personal data detected in ledger payload (Email pattern): '{s}'")

        # Check Phone
        if _PHONE_PATTERN.search(clean):
            # Verify if 10 consecutive digits
            digits = re.sub(r"\D", "", clean)
            if len(digits) == 10 or (len(digits) == 12 and digits.startswith("91")):
                raise ValueError(f"Personal data detected in ledger payload (Phone pattern): '{s}'")

        # Check free-text: strings containing multiple words (more than 4 words)
        words = clean.split()
        if len(words) > 4:
            raise ValueError(f"Free-text detected in ledger payload: '{s}'")


def append_event(session: Session, event_type: str, payload: dict) -> LedgerEvent:
    """
    Appends an event to the ledger with hash chaining.
    Genesis block prev_hash is 64 zeros.
    """
    check_payload_guard(payload)

    last_event = session.query(LedgerEvent).order_by(LedgerEvent.seq.desc()).first()
    prev_hash = last_event.hash if (last_event and last_event.hash) else GENESIS_PREV_HASH
    new_seq = (last_event.seq + 1) if (last_event and last_event.seq is not None) else 1

    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    payload_json = canonical_payload_json(payload)
    entry_hash = compute_entry_hash(prev_hash, ts, event_type, payload_json)

    ev = LedgerEvent(
        seq=new_seq,
        ts=ts,
        type=event_type,
        event_type=event_type,
        payload_json=payload_json,
        prev_hash=prev_hash,
        hash=entry_hash,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def verify_chain(session: Session) -> Dict[str, Any]:
    """
    Verifies the integrity of the audit ledger hash chain.
    Returns: {ok, checked, broken_at_seq, broken_event_type, reason}
    """
    events = session.query(LedgerEvent).order_by(LedgerEvent.seq.asc()).all()

    if not events:
        return {
            "ok": True,
            "checked": 0,
            "broken_at_seq": None,
            "broken_event_type": None,
            "reason": None,
        }

    prev_ev = None
    for idx, ev in enumerate(events):
        seq = ev.seq
        ts = ev.ts
        ev_type = ev.type
        payload_json = ev.payload_json
        prev_hash = ev.prev_hash
        stored_hash = ev.hash

        # Check genesis link
        if idx == 0:
            if prev_hash != GENESIS_PREV_HASH:
                return {
                    "ok": False,
                    "checked": idx,
                    "broken_at_seq": seq,
                    "broken_event_type": ev_type,
                    "reason": f"Genesis prev_hash mismatch: expected {GENESIS_PREV_HASH}, got {prev_hash}",
                }
        else:
            if prev_ev is not None:
                if prev_hash != prev_ev.hash:
                    return {
                        "ok": False,
                        "checked": idx,
                        "broken_at_seq": seq,
                        "broken_event_type": ev_type,
                        "reason": f"Hash chain broken at seq #{seq}: prev_hash does not match prior hash",
                    }
                if seq <= prev_ev.seq:
                    return {
                        "ok": False,
                        "checked": idx,
                        "broken_at_seq": seq,
                        "broken_event_type": ev_type,
                        "reason": f"Sequence out of order at seq #{seq}",
                    }

        # Recompute entry hash
        computed_hash = compute_entry_hash(prev_hash, ts, ev_type, payload_json)
        if computed_hash != stored_hash:
            return {
                "ok": False,
                "checked": idx,
                "broken_at_seq": seq,
                "broken_event_type": ev_type,
                "reason": f"Hash mismatch at seq #{seq}: stored {stored_hash[:12]}, computed {computed_hash[:12]}",
            }

        prev_ev = ev

    return {
        "ok": True,
        "checked": len(events),
        "broken_at_seq": None,
        "broken_event_type": None,
        "reason": None,
    }


def get_head_hash(session: Session) -> str:
    """Returns the current head hash of the ledger (or genesis hash if empty)."""
    last_event = session.query(LedgerEvent).order_by(LedgerEvent.seq.desc()).first()
    return last_event.hash if last_event and last_event.hash else GENESIS_PREV_HASH


def tamper_event(session: Session, seq: int) -> Dict[str, Any]:
    """Dev-only: modifies a stored payload without recomputing hash to demonstrate tamper detection."""
    ev = session.query(LedgerEvent).filter(LedgerEvent.seq == seq).first()
    if not ev:
        ev = session.query(LedgerEvent).filter(LedgerEvent.id == seq).first()
    if not ev:
        raise HTTPException(status_code=404, detail=f"Ledger event with seq #{seq} not found")

    # Backup original before tampering
    backup = LedgerTamperBackup(
        id=ev.id,
        payload_json=ev.payload_json,
        prev_hash=ev.prev_hash,
        hash=ev.hash,
        ts=ev.ts,
        type=ev.type,
    )
    session.merge(backup)
    session.flush()

    try:
        data = json.loads(ev.payload_json)
    except Exception:
        data = {}

    data["_tampered"] = True
    data["_tamper_note"] = "simulated unauthorized edit"
    ev.payload_json = canonical_payload_json(data)
    # Do NOT update hash
    session.commit()

    return {
        "ok": True,
        "tampered_seq": ev.seq,
        "event_type": ev.type,
        "message": f"Tampered payload for event seq #{ev.seq} without updating hash",
    }


def repair_event(session: Session, seq: Optional[int] = None) -> Dict[str, Any]:
    """Dev-only: restores tampered ledger rows from the backup copy."""
    if seq is not None:
        ev = session.query(LedgerEvent).filter(LedgerEvent.seq == seq).first()
        backup_id = ev.id if ev else seq
        backups = session.query(LedgerTamperBackup).filter(LedgerTamperBackup.id == backup_id).all()
    else:
        backups = session.query(LedgerTamperBackup).all()

    if not backups:
        return {"ok": True, "repaired_count": 0, "message": "No backups to restore"}

    repaired_seqs = []
    for b in backups:
        ev = session.query(LedgerEvent).filter(LedgerEvent.id == b.id).first()
        if ev:
            ev.payload_json = b.payload_json
            ev.prev_hash = b.prev_hash
            ev.hash = b.hash
            ev.ts = b.ts
            ev.type = b.type
            repaired_seqs.append(ev.seq)
        session.delete(b)

    session.commit()
    return {
        "ok": True,
        "repaired_count": len(repaired_seqs),
        "repaired_seqs": repaired_seqs,
        "message": f"Successfully restored {len(repaired_seqs)} ledger event(s)",
    }
