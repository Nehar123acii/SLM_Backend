"""
backend/api/rules.py
===================
API router for DPDP operational questionnaire and compliance flags engine:
- GET  /api/questionnaire
- POST /api/questionnaire
- POST /api/flags/run
- GET  /api/flags
"""

from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.engine import get_db
from backend.services.rules import (
    get_latest_flags,
    get_questionnaire_questions,
    run_flags,
    save_questionnaire_answer,
    QUESTIONNAIRE_KEYS,
)

router = APIRouter(tags=["rules_and_flags"])


class SingleQuestionnaireAnswerRequest(BaseModel):
    key: Optional[str] = None
    answer: Optional[str] = None
    answers: Optional[Dict[str, str]] = None


# ---------------------------------------------------------------------------
# Questionnaire Endpoints
# ---------------------------------------------------------------------------

@router.get("/api/questionnaire", response_model=List[Dict[str, Any]])
def get_questionnaire(lang: str = "en", db: Session = Depends(get_db)):
    """Retrieve the operational DPDP readiness questions with current answers."""
    return get_questionnaire_questions(db, lang=lang)


@router.post("/api/questionnaire", status_code=status.HTTP_200_OK)
def post_questionnaire(
    payload: Union[SingleQuestionnaireAnswerRequest, Dict[str, Any], List[Dict[str, Any]]],
    db: Session = Depends(get_db),
):
    """
    Submit questionnaire response (yes/no/not_sure).
    Append-only recording via ledger event 'questionnaire_answer'.
    """
    to_save: List[tuple[str, str]] = []

    if isinstance(payload, list):
        for item in payload:
            k = item.get("key")
            a = item.get("answer")
            if k and a:
                to_save.append((str(k), str(a)))
    elif isinstance(payload, SingleQuestionnaireAnswerRequest):
        if payload.answers:
            for k, a in payload.answers.items():
                to_save.append((str(k), str(a)))
        elif payload.key and payload.answer:
            to_save.append((str(payload.key), str(payload.answer)))
    elif isinstance(payload, dict):
        if "answers" in payload and isinstance(payload["answers"], dict):
            for k, a in payload["answers"].items():
                to_save.append((str(k), str(a)))
        elif "key" in payload and "answer" in payload:
            to_save.append((str(payload["key"]), str(payload["answer"])))

    if not to_save:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload must specify 'key' and 'answer', or an 'answers' dictionary.",
        )

    saved_results = {}
    for k, a in to_save:
        key_clean = k.strip().lower()
        if key_clean not in QUESTIONNAIRE_KEYS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown questionnaire key '{k}'. Allowed: {sorted(QUESTIONNAIRE_KEYS)}",
            )
        ans_clean = a.strip().lower()
        if ans_clean not in {"yes", "no", "not_sure"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid answer '{a}'. Must be one of: 'yes', 'no', 'not_sure'.",
            )
        try:
            save_questionnaire_answer(db, key_clean, ans_clean)
            saved_results[key_clean] = ans_clean
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    return {"status": "ok", "saved": saved_results}


# ---------------------------------------------------------------------------
# Flags Engine Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/flags/run")
def evaluate_and_snapshot_flags(db: Session = Depends(get_db)):
    """
    Evaluates all DPDP rules, stores a snapshot in flag_results with a new run_id,
    compares against previous run, and records 'flag_change' ledger events for changes.
    """
    return run_flags(db)


@router.get("/api/flags", response_model=List[Dict[str, Any]])
def get_flags(lang: str = "en", db: Session = Depends(get_db)):
    """
    Retrieve latest compliance flags snapshot with full metadata:
    whats_right, whats_not, how_to_fix, citation chip data, and fix_action.
    """
    return get_latest_flags(db, lang=lang)
