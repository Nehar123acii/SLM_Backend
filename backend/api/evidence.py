import os
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.db.models import EvidencePack
from backend.services.evidence import export_evidence_pack, verify_evidence_pack

router = APIRouter(tags=["evidence"])


@router.post("/api/evidence/export")
def create_evidence_pack(db: Session = Depends(get_db)):
    """Exports a tamper-evident compliance audit package and registers its head hash."""
    return export_evidence_pack(db)


@router.get("/api/evidence/download/{pack_id}")
def download_evidence_pack(pack_id: str, db: Session = Depends(get_db)):
    """Downloads the compliance evidence pack ZIP file."""
    pack = db.query(EvidencePack).filter(EvidencePack.pack_id == pack_id).first()
    if not pack or not os.path.exists(pack.path):
        raise HTTPException(status_code=404, detail=f"Evidence pack '{pack_id}' not found.")
    return FileResponse(
        path=pack.path,
        filename=f"evidence_pack_{pack_id}.zip",
        media_type="application/zip",
    )


@router.get("/verify/{pack_id}")
def public_verify_evidence_pack(pack_id: str, db: Session = Depends(get_db)):
    """
    Public verification endpoint: checks stored pack manifest hash and ledger chain,
    returning 'chain intact' or identifying any mismatch or broken event.
    """
    return verify_evidence_pack(db, pack_id)
