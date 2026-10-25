import datetime
import hashlib
import json
import os
import zipfile
from typing import Any, Dict, Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.db.models import EvidencePack, FlagResult, LedgerEvent, PurposeLink
from backend.services.ledger import canonical_payload_json, verify_chain

LIMITATIONS_TEXT = """# Kavach Compliance Evidence Pack — Limitations & Scope

1. **Pseudonymisation, Not Anonymisation**: Personal data within the Kavach system is pseudonymised using keyed HMAC-SHA256; it is not irreversibly anonymised.
2. **External Head Hash Requirement**: The cryptographic tamper-evidence of this evidence pack holds only if the ledger head hash is preserved outside the database or independently timestamped.
3. **Out of Scope**: Off-site backups, secondary cold storage, and third-party data processor copies are out of scope of this local evidence snapshot.
4. **Statutory Citations**: Statutory citations in rules and retention schedules are unverified hints provided for human review and verification.
5. **Regulatory Disclaimer**: This platform and evidence pack serve as an operational readiness aid and technical compliance audit trail, not formal legal advice.
6. **Deletion vs. Forensic Wiping**: Data purging is standard filesystem deletion, not DoD-grade forensic wiping or cryptographic zeroization of physical disk sectors.
7. **Backups Out of Scope**: Business-level purge removes local SQLite storage and workspace output files; secondary backups, external cold storage, and snapshots are out of scope.
"""


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_evidence_pack(session: Session, base_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds and writes a compliance evidence pack ZIP to data/out/evidence/{pack_id}.zip.
    Stores metadata row in EvidencePack table and returns export info including head_hash.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    ts_str = now.isoformat()

    if base_dir is None:
        # Use workspace data directory
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    out_dir = os.path.join(base_dir, "data", "out", "evidence")
    os.makedirs(out_dir, exist_ok=True)

    # 1. Gather ledger events
    events = session.query(LedgerEvent).order_by(LedgerEvent.seq.asc()).all()
    head_hash = events[-1].hash if events else ("0" * 64)
    ledger_records = [
        {
            "seq": ev.seq,
            "ts": ev.ts,
            "type": ev.type,
            "payload": json.loads(ev.payload_json) if ev.payload_json else {},
            "prev_hash": ev.prev_hash,
            "hash": ev.hash,
        }
        for ev in events
    ]
    ledger_bytes = json.dumps(ledger_records, indent=2, sort_keys=True).encode("utf-8")

    # 2. Gather latest flag results
    flag_results = session.query(FlagResult).all()
    flags_records = [
        {
            "rule_id": f.rule_id,
            "run_id": f.run_id,
            "state": f.state,
            "evidence_refs": f.evidence_refs,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in flag_results
    ]
    flags_bytes = json.dumps(flags_records, indent=2, sort_keys=True).encode("utf-8")

    # 3. Gather active purposes (masked)
    purpose_links = (
        session.query(PurposeLink)
        .filter(PurposeLink.superseded_by.is_(None))
        .all()
    )
    purposes_records = [
        {
            "column_id": p.column_id,
            "segment": p.segment,
            "purpose_id": p.purpose_id,
            "status": p.status,
            "answered_by_masked": (p.answered_by[:2] + "****") if p.answered_by else None,
            "answered_at": p.answered_at.isoformat() if p.answered_at else None,
        }
        for p in purpose_links
    ]
    purposes_bytes = json.dumps(purposes_records, indent=2, sort_keys=True).encode("utf-8")

    # 4. Limitations markdown
    limitations_bytes = LIMITATIONS_TEXT.encode("utf-8")

    # 5. Manifest calculation
    file_hashes = {
        "ledger.json": compute_sha256(ledger_bytes),
        "flags.json": compute_sha256(flags_bytes),
        "purposes.json": compute_sha256(purposes_bytes),
        "limitations.md": compute_sha256(limitations_bytes),
    }

    manifest_obj = {
        "generated_at": ts_str,
        "head_hash": head_hash,
        "files": file_hashes,
    }
    manifest_bytes = json.dumps(manifest_obj, indent=2, sort_keys=True).encode("utf-8")
    manifest_sha256 = compute_sha256(manifest_bytes)
    pack_id = manifest_sha256[:12]

    # 6. Write ZIP file
    zip_path = os.path.join(out_dir, f"{pack_id}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ledger.json", ledger_bytes)
        zf.writestr("flags.json", flags_bytes)
        zf.writestr("purposes.json", purposes_bytes)
        zf.writestr("limitations.md", limitations_bytes)
        zf.writestr("manifest.json", manifest_bytes)

    # 7. Check chain status
    chain_check = verify_chain(session)
    chain_ok_int = 1 if chain_check["ok"] else 0

    # 8. Persist row to EvidencePack
    evidence_pack_row = EvidencePack(
        pack_id=pack_id,
        created_at=ts_str,
        head_hash=head_hash,
        manifest_sha256=manifest_sha256,
        score=100,
        chain_ok=chain_ok_int,
        path=zip_path,
    )
    session.merge(evidence_pack_row)
    session.commit()

    return {
        "pack_id": pack_id,
        "created_at": ts_str,
        "head_hash": head_hash,
        "manifest_sha256": manifest_sha256,
        "path": zip_path,
        "chain_ok": chain_check["ok"],
    }


def verify_evidence_pack(session: Session, pack_id: str) -> Dict[str, Any]:
    """
    Public verification: inspects stored evidence pack ZIP, re-computes file hashes
    against manifest.json, and checks ledger chain integrity.
    """
    pack = session.query(EvidencePack).filter(EvidencePack.pack_id == pack_id).first()
    if not pack:
        raise HTTPException(status_code=404, detail=f"Evidence pack '{pack_id}' not found.")

    if not os.path.exists(pack.path):
        raise HTTPException(status_code=404, detail=f"Evidence pack archive not found at path '{pack.path}'.")

    # Read zip and verify file hashes
    try:
        with zipfile.ZipFile(pack.path, "r") as zf:
            if "manifest.json" not in zf.namelist():
                return {
                    "pack_id": pack_id,
                    "ok": False,
                    "reason": "manifest.json missing from evidence pack archive",
                    "status": "tampered",
                }

            manifest_bytes = zf.read("manifest.json")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            expected_files = manifest.get("files", {})

            for filename, expected_hash in expected_files.items():
                if filename not in zf.namelist():
                    return {
                        "pack_id": pack_id,
                        "ok": False,
                        "reason": f"File '{filename}' missing from archive",
                        "status": "mismatched",
                    }
                content = zf.read(filename)
                actual_hash = compute_sha256(content)
                if actual_hash != expected_hash:
                    return {
                        "pack_id": pack_id,
                        "ok": False,
                        "reason": f"Hash mismatch for '{filename}': expected {expected_hash}, got {actual_hash}",
                        "status": "mismatched",
                    }

    except Exception as e:
        return {
            "pack_id": pack_id,
            "ok": False,
            "reason": f"Failed to read archive: {str(e)}",
            "status": "corrupted",
        }

    # Verify ledger chain
    chain_result = verify_chain(session)
    if not chain_result["ok"]:
        return {
            "pack_id": pack_id,
            "ok": False,
            "broken_at_seq": chain_result.get("broken_at_seq"),
            "broken_event_type": chain_result.get("broken_event_type"),
            "reason": chain_result.get("reason"),
            "status": "chain_broken",
        }

    return {
        "pack_id": pack_id,
        "ok": True,
        "head_hash": pack.head_hash,
        "manifest_sha256": pack.manifest_sha256,
        "status": "chain intact",
    }
