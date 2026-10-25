import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
import yaml
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import Column, Dataset, Occurrence, Purpose, PurposeLink

_PURPOSES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "purposes")
_PURPOSES_FILE = os.path.join(_PURPOSES_DIR, "purposes.yaml")
_PRESET_FILE = os.path.join(_PURPOSES_DIR, "clinic_preset.yaml")

VALID_SEGMENTS = {"patient", "customer", "staff"}


def load_purposes_vocabulary() -> List[Dict[str, Any]]:
    """Loads the controlled purposes vocabulary from purposes.yaml."""
    if not os.path.exists(_PURPOSES_FILE):
        return []
    with open(_PURPOSES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or []


def load_clinic_preset() -> Dict[str, Any]:
    """Loads clinic preset mappings from clinic_preset.yaml."""
    if not os.path.exists(_PRESET_FILE):
        return {}
    with open(_PRESET_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def get_allowed_purpose_ids() -> set:
    """Returns set of all allowed purpose string IDs from purposes.yaml."""
    vocab = load_purposes_vocabulary()
    ids = set()
    for item in vocab:
        if "id" in item:
            ids.add(str(item["id"]))
        if "label_key" in item:
            ids.add(str(item["label_key"]))
    return ids


def infer_segment_from_filename(filename: str) -> Optional[str]:
    """Infers default dataset segment from filename keywords."""
    if not filename:
        return None
    fn = filename.lower()
    if "patient" in fn:
        return "patient"
    elif "billing" in fn or "customer" in fn:
        return "customer"
    elif "staff" in fn or "employee" in fn:
        return "staff"
    return None


def ensure_purposes_seeded(db: Session) -> Dict[str, Purpose]:
    """Ensures purposes defined in purposes.yaml exist in the purposes DB table."""
    vocab = load_purposes_vocabulary()
    purpose_map = {}
    
    existing = db.query(Purpose).all()
    existing_by_key = {p.label_key: p for p in existing}
    
    for item in vocab:
        key = item.get("label_key") or item.get("id")
        if not key:
            continue
        if key in existing_by_key:
            purpose_map[key] = existing_by_key[key]
        else:
            p_obj = Purpose(label_key=key)
            db.add(p_obj)
            db.flush()
            purpose_map[key] = p_obj
            existing_by_key[key] = p_obj
            
    db.commit()
    return purpose_map


def generate_questions(db: Session) -> Dict[str, Any]:
    """
    Generates open purpose questions for columns with a category (not 'other')
    and no CONFIRMED purpose_link for their segment.
    
    Ordered by impact_tier descending, then number of occurrences descending.
    """
    vocab = load_purposes_vocabulary()
    preset = load_clinic_preset()

    # Options include all vocabulary items plus 'I don't know'
    options = [
        {"id": item["id"], "label_key": item.get("label_key", item["id"]), "label": item["label"]}
        for item in vocab
    ]
    options.append({"id": "unknown", "label_key": "unknown", "label": "I don't know"})

    # Query eligible columns (category not None, not empty, not 'other')
    eligible_cols = (
        db.query(Column, Dataset)
        .join(Dataset, Column.dataset_id == Dataset.dataset_id)
        .filter(
            Column.category.isnot(None),
            Column.category != "",
            Column.category != "other",
        )
        .all()
    )

    open_questions = []
    answered_count = 0
    total_count = len(eligible_cols)

    for col, dataset in eligible_cols:
        segment = dataset.segment or infer_segment_from_filename(dataset.original_filename) or "customer"

        # Check active (non-superseded) links for this column and segment
        active_links = (
            db.query(PurposeLink)
            .filter(
                PurposeLink.column_id == col.id,
                PurposeLink.segment == segment,
                PurposeLink.superseded_by.is_(None),
            )
            .all()
        )

        has_confirmed = any(l.status == "confirmed" for l in active_links)

        if has_confirmed:
            answered_count += 1
            continue

        # Count occurrences for ordering
        occ_count = db.query(func.count(Occurrence.id)).filter(Occurrence.column_id == col.id).scalar() or 0
        impact_tier_int = int(col.impact_tier) if (col.impact_tier and col.impact_tier.isdigit()) else 1

        # Suggested default from preset (hint only, never auto-confirmed)
        suggested = preset.get(segment, {}).get(col.category)
        if not suggested and col.category in preset.get(segment, {}):
            suggested = preset[segment][col.category]

        q_text = (
            f"What business purpose does your organisation collect {col.column_name} "
            f"({col.category}) for {segment}s?"
        )

        open_questions.append({
            "column_id": col.id,
            "dataset_name": dataset.original_filename,
            "category": col.category,
            "segment": segment,
            "question_text": q_text,
            "options": options,
            "suggested_default": suggested or None,
            "impact_tier": impact_tier_int,
            "occurrences_count": occ_count,
        })

    # Order by impact_tier descending, then occurrences_count descending, then column_id ascending
    open_questions.sort(key=lambda q: (q["impact_tier"], q["occurrences_count"], -q["column_id"]), reverse=True)

    return {
        "questions": open_questions,
        "progress": {
            "answered": answered_count,
            "total": total_count,
        },
        "answered": answered_count,
        "total": total_count,
    }


def record_answer(
    db: Session,
    column_id: int,
    segment: str,
    purpose_ids: Optional[List[Union[str, int]]] = None,
    unknown: bool = False,
    answered_by: Optional[str] = "business_owner",
) -> List[Dict[str, Any]]:
    """
    Submits an answer for a column and segment.
    Append-only: creates new purpose_links rows and sets superseded_by on existing active rows.
    Rejects unknown purpose IDs with HTTP 400.
    """
    col = db.query(Column).filter(Column.id == column_id).first()
    if not col:
        raise HTTPException(status_code=404, detail=f"Column with ID {column_id} not found.")

    if segment not in VALID_SEGMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid segment '{segment}'. Allowed segments are: {', '.join(sorted(VALID_SEGMENTS))}.",
        )

    allowed_ids = get_allowed_purpose_ids()
    now = datetime.now(timezone.utc)

    # Find existing active (non-superseded) links for this column and segment
    old_links = (
        db.query(PurposeLink)
        .filter(
            PurposeLink.column_id == column_id,
            PurposeLink.segment == segment,
            PurposeLink.superseded_by.is_(None),
        )
        .all()
    )

    created_records = []

    if unknown:
        # Create row with status 'unknown' and null purpose_id
        new_link = PurposeLink(
            column_id=column_id,
            segment=segment,
            purpose_id=None,
            status="unknown",
            answered_by=answered_by,
            answered_at=now,
        )
        db.add(new_link)
        db.flush()

        for old in old_links:
            old.superseded_by = new_link.id

        created_records.append({
            "id": new_link.id,
            "column_id": column_id,
            "segment": segment,
            "purpose_id": None,
            "status": "unknown",
            "answered_by": answered_by,
            "answered_at": now.isoformat(),
        })

    else:
        if not purpose_ids:
            raise HTTPException(
                status_code=400,
                detail="Must provide at least one purpose_id or set unknown=true.",
            )

        # Validate that all purpose IDs are known in purposes.yaml
        for pid in purpose_ids:
            pid_str = str(pid)
            if pid_str not in allowed_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown purpose id: '{pid_str}'. Allowed: {sorted(list(allowed_ids))}",
                )

        purpose_map = ensure_purposes_seeded(db)
        new_link_ids = []

        for pid in purpose_ids:
            pid_str = str(pid)
            p_obj = purpose_map.get(pid_str)
            if not p_obj:
                # Look up by id if passed as int
                if pid_str.isdigit():
                    p_obj = db.query(Purpose).filter(Purpose.id == int(pid_str)).first()
            if not p_obj:
                p_obj = Purpose(label_key=pid_str)
                db.add(p_obj)
                db.flush()
                purpose_map[pid_str] = p_obj

            new_link = PurposeLink(
                column_id=column_id,
                segment=segment,
                purpose_id=p_obj.id,
                status="confirmed",
                answered_by=answered_by,
                answered_at=now,
            )
            db.add(new_link)
            db.flush()
            new_link_ids.append(new_link.id)

            created_records.append({
                "id": new_link.id,
                "column_id": column_id,
                "segment": segment,
                "purpose_id": p_obj.id,
                "purpose_key": p_obj.label_key,
                "status": "confirmed",
                "answered_by": answered_by,
                "answered_at": now.isoformat(),
            })

        # Set superseded_by on old links pointing to the first new link
        if new_link_ids:
            first_new_id = new_link_ids[0]
            for old in old_links:
                old.superseded_by = first_new_id

    db.commit()
    return created_records


def get_column_purposes_history(db: Session, column_id: int) -> Dict[str, Any]:
    """Returns current active purpose answers and full audit history for a column."""
    col = db.query(Column).filter(Column.id == column_id).first()
    if not col:
        raise HTTPException(status_code=404, detail=f"Column with ID {column_id} not found.")

    all_links = (
        db.query(PurposeLink)
        .filter(PurposeLink.column_id == column_id)
        .order_by(PurposeLink.id.asc())
        .all()
    )

    current = []
    history = []

    for l in all_links:
        pkey = l.purpose.label_key if l.purpose else None
        item = {
            "id": l.id,
            "column_id": l.column_id,
            "segment": l.segment,
            "purpose_id": l.purpose_id,
            "purpose_key": pkey,
            "status": l.status,
            "answered_by": l.answered_by,
            "answered_at": l.answered_at.isoformat() if l.answered_at else None,
            "superseded_by": l.superseded_by,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        history.append(item)
        if l.superseded_by is None:
            current.append(item)

    return {
        "column_id": column_id,
        "column_name": col.column_name,
        "category": col.category,
        "current": current,
        "history": history,
    }
