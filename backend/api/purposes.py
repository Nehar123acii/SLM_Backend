from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.db.models import Dataset
from backend.services.purposes import (
    VALID_SEGMENTS,
    generate_questions,
    get_column_purposes_history,
    load_purposes_vocabulary,
    record_answer,
)

router = APIRouter(tags=["purposes"])


class AnswerSubmissionRequest(BaseModel):
    column_id: int
    segment: str
    purpose_ids: Optional[List[Union[str, int]]] = None
    unknown: Optional[bool] = False
    answered_by: Optional[str] = "business_owner"


class SegmentUpdateRequest(BaseModel):
    segment: str


@router.get("/purposes")
def get_purposes_vocabulary():
    """Returns the controlled purpose vocabulary."""
    return load_purposes_vocabulary()


@router.get("/questions")
def get_open_questions(db: Session = Depends(get_db)):
    """
    Returns open questions for columns requiring a confirmed business purpose,
    ordered by impact tier descending then occurrence count descending.
    Includes progress counts (answered, total).
    """
    return generate_questions(db)


@router.post("/answers", status_code=status.HTTP_201_CREATED)
def submit_answer(payload: AnswerSubmissionRequest, db: Session = Depends(get_db)):
    """
    Records an answer for a column and segment.
    Append-only: creates confirmed or unknown purpose links and supersedes prior active links.
    Rejects unknown purpose IDs with HTTP 400.
    """
    return record_answer(
        db=db,
        column_id=payload.column_id,
        segment=payload.segment,
        purpose_ids=payload.purpose_ids,
        unknown=bool(payload.unknown),
        answered_by=payload.answered_by or "business_owner",
    )


@router.get("/columns/{column_id}/purposes")
def get_column_purposes(column_id: int, db: Session = Depends(get_db)):
    """Returns the active purpose answers and complete audit history for a column."""
    return get_column_purposes_history(db, column_id)


@router.patch("/datasets/{dataset_id_or_id}/segment")
def update_dataset_segment(
    dataset_id_or_id: str,
    payload: SegmentUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Updates the business segment (patient|customer|staff) of a dataset.
    """
    target_segment = payload.segment.strip().lower()
    if target_segment not in VALID_SEGMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid segment '{target_segment}'. Allowed segments are: {', '.join(sorted(VALID_SEGMENTS))}.",
        )

    ds = None
    if dataset_id_or_id.isdigit():
        ds = db.query(Dataset).filter(Dataset.id == int(dataset_id_or_id)).first()
    if not ds:
        ds = db.query(Dataset).filter(Dataset.dataset_id == dataset_id_or_id).first()

    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id_or_id}' not found.")

    ds.segment = target_segment
    db.commit()
    db.refresh(ds)

    return {
        "id": ds.id,
        "dataset_id": ds.dataset_id,
        "original_filename": ds.original_filename,
        "segment": ds.segment,
    }
