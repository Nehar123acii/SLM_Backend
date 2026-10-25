"""
backend/services/rights.py
==========================
Data Principal Rights Desk and Case Lifecycle Engine for Kavach.
Covers:
- Intent classifier: rules first (intents.yaml) covering English, Hinglish, and Kannada-in-Latin;
  ai_client fallback when rules return none (marked inferred).
- WhatsApp intake & chat parsing.
- Sender resolution via HMAC-SHA256 (strong for phone, probable for name-only).
- Zero raw personal data storage (only masked excerpts and sender_masked).
- Statutory SLA clock calculation (30 days with verify flag).
- Occurrence-based checklist generation (one per source holding the person).
- Case lifecycle: received -> identity_check -> plan -> approved -> executed -> closed.
- Erasure engine reuse (compile_plan, approve, execute) with identity gate.
- Tamper-evident ledger logging (case_received, case_identity, case_plan, case_approved, case_executed, case_closed).
"""

import datetime
from datetime import timezone, timedelta
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import yaml
from sqlalchemy.orm import Session

from backend.ai_client.mock_client import get_ai_client
from backend.config import RESPONSE_DAYS, settings
from backend.db.models import (
    Column,
    Dataset,
    ErasurePlan,
    Occurrence,
    Person,
    RightsCase,
    utc_now,
)
from backend.security import normalise, mask, hmac_value
from backend.services.erasure import (
    compile_plan,
    confirm_identity_for_plan,
    approve as erasure_approve,
    execute as erasure_execute,
)
from backend.services.ledger import append_event

logger = logging.getLogger("rights_service")

# ---------------------------------------------------------------------------
# Load intent rules from backend/rules/intents.yaml
# ---------------------------------------------------------------------------
def _load_intents_yaml() -> Dict[str, Any]:
    yaml_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "rules",
        "intents.yaml",
    )
    if not os.path.exists(yaml_path):
        return {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_INTENT_RULES = _load_intents_yaml()


# ---------------------------------------------------------------------------
# Intent Classifier (Rules First, AI Fallback)
# ---------------------------------------------------------------------------
def _check_erase_intent(text_lower: str, rule: dict, matched_kw: str) -> Optional[Dict[str, Any]]:
    """Validate erase intent: personal-data object required, false-positive objects disqualify."""
    false_positive_objs = [o.lower() for o in rule.get("false_positive_objects", [])]
    personal_data_objs = [o.lower() for o in rule.get("personal_data_objects", [])]

    kw_implies_personal = any(p in matched_kw.lower() for p in [
        "number", "detail", "data", "record", "name", "email", "address",
        "nanna", "mera", "meri", "me",
        "erasure", "forgotten", "hata", "maadi", "tegedu", "beda",
    ])

    fp_hit = False
    for fp_obj in false_positive_objs:
        pattern = rf"\b(delete|remove|hata|erase|tegedu)\b[^.!?\n]{{0,30}}\b{re.escape(fp_obj)}\b"
        if re.search(pattern, text_lower):
            has_personal = any(re.search(rf"\b{re.escape(p)}\b", text_lower) for p in personal_data_objs)
            if not has_personal:
                fp_hit = True
                break

    if fp_hit:
        return None

    has_personal = kw_implies_personal or any(
        re.search(rf"\b{re.escape(p)}\b", text_lower) for p in personal_data_objs
    )
    if not has_personal:
        return None

    words_count = len(matched_kw.split())
    confidence = 0.90 if words_count >= 3 else (0.80 if words_count == 2 else 0.70)
    return {
        "intent": "erase",
        "confidence": confidence,
        "reason": f"matched keyword: '{matched_kw}'",
    }


def classify_with_rules(text: str) -> Dict[str, Any]:
    """
    Evaluates message against intents.yaml across English, Hinglish, and Kannada-in-Latin.
    Intents: erase, access, correct, withdraw_consent, complaint.
    """
    rules = _INTENT_RULES.get("intents", {})
    text_lower = text.lower().strip()

    intent_order = ["erase", "access", "correct", "withdraw_consent", "complaint"]

    for intent in intent_order:
        rule = rules.get(intent, {})
        all_keywords = (
            rule.get("keywords_en", []) +
            rule.get("keywords_hinglish", []) +
            rule.get("keywords_kannada_latin", [])
        )
        for kw in all_keywords:
            if kw.lower() in text_lower:
                if intent == "erase":
                    erase_res = _check_erase_intent(text_lower, rule, kw)
                    if erase_res:
                        return erase_res
                    else:
                        continue

                words_count = len(kw.split())
                confidence = 0.90 if words_count >= 3 else (0.80 if words_count == 2 else 0.70)
                return {
                    "intent": intent,
                    "confidence": confidence,
                    "reason": f"matched keyword: '{kw}'",
                }

    return {"intent": "none", "confidence": 0.0, "reason": "no rule matched"}


def classify_message(text: str) -> Dict[str, Any]:
    """
    Classifies a rights request message text:
    1. Rules first (English, Hinglish, Kannada-in-Latin)
    2. Calls ai_client only when rules return none (marked 'inferred')
    """
    rule_result = classify_with_rules(text)
    if rule_result["intent"] != "none":
        return {
            "intent": rule_result["intent"],
            "confidence": rule_result["confidence"],
            "source": "rule",
            "reason": rule_result["reason"],
        }

    # Call AI client fallback
    ai_client = get_ai_client()
    try:
        ai_resp = ai_client.invoke({
            "task": "classify_privacy_request",
            "version": "1",
            "payload": {
                "request_id": "classify_rights_desk",
                "raw_text": text,
                "submission_channel": "chat",
            },
        })
        ai_res = ai_resp.get("result", {})
        ai_types = ai_res.get("request_types", [])
        primary = ai_types[0] if ai_types else "ACCESS"

        intent_map = {
            "ERASURE": "erase",
            "ACCESS": "access",
            "CORRECTION": "correct",
            "WITHDRAW_CONSENT": "withdraw_consent",
            "COMPLAINT": "complaint",
        }
        mapped_intent = intent_map.get(primary.upper(), "access")
        return {
            "intent": mapped_intent,
            "confidence": ai_res.get("confidence", 0.6) or 0.6,
            "source": "inferred",
            "reason": f"AI fallback classified as {primary}",
        }
    except Exception as e:
        logger.warning("AI classification fallback failed: %s", e)
        return {
            "intent": "access",
            "confidence": 0.5,
            "source": "inferred",
            "reason": "AI fallback default",
        }


# ---------------------------------------------------------------------------
# WhatsApp Chat Parser & Excerpt Masker
# ---------------------------------------------------------------------------
WA_REGEXES = [
    re.compile(r"^(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[apAP][mM])?)\s+-\s+"),
    re.compile(r"^\[(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[apAP][mM])?)\]\s+"),
    re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}\s*[apAP][mM])\s*-\s*"),
]

_PHONE_RE = re.compile(r"(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9]\d{9}\b|\b\d{10}\b")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")
_AADHAAR_RE = re.compile(r"\b\d{4}[\s-]\d{4}[\s-]\d{4}\b|\b\d{12}\b")
_PAN_RE = re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")


def parse_whatsapp_text(text: str) -> List[Dict[str, str]]:
    """
    Parses WhatsApp export text into list of {sender, text, timestamp} dicts.
    Ignores system encryption and media omitted lines.
    """
    messages: List[Dict[str, str]] = []
    current_msg: Optional[Dict[str, str]] = None

    for line in text.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        matched = False
        for pat in WA_REGEXES:
            m = pat.match(line_clean)
            if m:
                matched = True
                if current_msg:
                    messages.append(current_msg)

                ts = m.group(0).rstrip(" -").strip("[] ")
                rest = line_clean[m.end():]

                if ":" in rest:
                    sender_part, msg_text = rest.split(":", 1)
                    sender = sender_part.strip()
                    msg_text = msg_text.strip()
                else:
                    sender = "SYSTEM"
                    msg_text = rest.strip()

                current_msg = {
                    "sender": sender,
                    "text": msg_text,
                    "timestamp": ts,
                }
                break

        if not matched and current_msg:
            # Continuation line
            current_msg["text"] += " " + line_clean

    if current_msg:
        messages.append(current_msg)

    # Filter out system notices
    filtered = []
    for m in messages:
        sender_upper = m["sender"].upper()
        if sender_upper in ("SYSTEM", "MESSAGES AND CALLS"):
            continue
        if "end-to-end encrypted" in m["text"].lower():
            continue
        filtered.append(m)

    return filtered


def mask_message_excerpt(text: str, max_len: int = 200) -> str:
    """Masks PII patterns in message excerpts before persistence."""
    res = _PHONE_RE.sub("[PHONE]", text)
    res = _EMAIL_RE.sub("[EMAIL]", res)
    res = _AADHAAR_RE.sub("[AADHAAR]", res)
    res = _PAN_RE.sub("[PAN]", res)
    if len(res) > max_len:
        res = res[:max_len] + "..."
    return res


# ---------------------------------------------------------------------------
# Sender Resolution (HMAC Matching)
# ---------------------------------------------------------------------------
def resolve_sender(session: Session, sender: str, text: str) -> Tuple[Optional[int], str]:
    """
    Resolves sender to an existing person_id:
    - Strong match via normalized phone found in sender string or message text.
    - Probable match via normalized name in sender string.
    Never merges on name alone.
    """
    # 1. Check for phone in sender
    phone_candidates: List[str] = []
    if _PHONE_RE.search(sender):
        phone_candidates.append(sender)

    # Also check message body for phone
    for m in _PHONE_RE.finditer(text):
        phone_candidates.append(m.group(0))

    for p_str in phone_candidates:
        norm_p = normalise("phone", p_str)
        if norm_p:
            p_hmac = hmac_value("phone", norm_p)
            occ = (
                session.query(Occurrence)
                .join(Column, Occurrence.column_id == Column.id)
                .filter(Column.category == "phone", Occurrence.value_hmac == p_hmac)
                .first()
            )
            if not occ:
                occ = session.query(Occurrence).filter(Occurrence.value_hmac == p_hmac).first()

            if occ and occ.person_id:
                return occ.person_id, "strong"

    # 2. Check for name in sender
    if sender and not _PHONE_RE.match(sender.strip()):
        norm_name = normalise("name", sender)
        if norm_name:
            n_hmac = hmac_value("name", norm_name)
            occ = (
                session.query(Occurrence)
                .join(Column, Occurrence.column_id == Column.id)
                .filter(Column.category == "name", Occurrence.value_hmac == n_hmac)
                .first()
            )
            if not occ:
                occ = session.query(Occurrence).filter(Occurrence.value_hmac == n_hmac).first()

            if occ and occ.person_id:
                return occ.person_id, "probable"

    return None, "none"


# ---------------------------------------------------------------------------
# Checklist Generation (One Per Source Holding the Person)
# ---------------------------------------------------------------------------
def generate_case_checklist(session: Session, person_id: Optional[int]) -> List[Dict[str, Any]]:
    """
    Generates operational response checklist items for a person.
    Exactly one item per distinct source dataset that holds their occurrences.
    """
    if not person_id:
        return []

    occs = session.query(Occurrence).filter(Occurrence.person_id == person_id).all()
    col_ids = [o.column_id for o in occs if o.column_id is not None]
    if not col_ids:
        return []

    columns = session.query(Column).filter(Column.id.in_(col_ids)).all()
    dataset_ids = list({c.dataset_id for c in columns if c.dataset_id})
    if not dataset_ids:
        return []

    datasets = session.query(Dataset).filter(Dataset.dataset_id.in_(dataset_ids)).all()

    checklist: List[Dict[str, Any]] = []
    for idx, ds in enumerate(datasets, start=1):
        checklist.append({
            "step": idx,
            "source_id": ds.dataset_id,
            "filename": ds.original_filename,
            "task": f"Process records in {ds.original_filename} ({ds.dataset_id})",
            "completed": False,
        })
    return checklist


def generate_case_ref(session: Session) -> str:
    today_str = datetime.datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"case_{today_str}_"
    count = session.query(RightsCase).filter(RightsCase.case_ref.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:03d}"


# ---------------------------------------------------------------------------
# Intake Processing
# ---------------------------------------------------------------------------
def process_intake(session: Session, messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Processes parsed WhatsApp messages:
    - Classifies intent using rules first, AI fallback if none.
    - Resolves sender to person_id (strong via phone, probable via name).
    - Masks sender and excerpts (zero raw personal data).
    - Computes 30-day statutory SLA clock with UNVERIFIED verify flag.
    - Creates RightsCase row and logs case_received to ledger.
    """
    now = datetime.datetime.now(timezone.utc)
    created_cases: List[Dict[str, Any]] = []

    for msg in messages:
        sender_raw = msg.get("sender", "").strip()
        text_raw = msg.get("text", "").strip()
        if not text_raw:
            continue

        classification = classify_message(text_raw)
        intent = classification["intent"]
        if intent == "none":
            continue

        confidence = classification["confidence"]
        intent_source = classification.get("source", "rule")

        person_id, resolution = resolve_sender(session, sender_raw, text_raw)

        # Mask sender
        if _PHONE_RE.search(sender_raw):
            sender_masked = mask("phone", sender_raw)
        else:
            sender_masked = mask("name", sender_raw) if sender_raw else "[unknown]"

        # Mask excerpt
        excerpt_masked = mask_message_excerpt(text_raw)

        # Statutory 30-day SLA deadline (UNVERIFIED, verify flag)
        received_at = now
        due_at = received_at + datetime.timedelta(days=RESPONSE_DAYS)

        # Checklist from occurrences
        checklist = generate_case_checklist(session, person_id)

        case_ref = generate_case_ref(session)
        case_obj = RightsCase(
            case_ref=case_ref,
            person_id=person_id,
            sender_masked=sender_masked,
            intent=intent,
            intent_source=intent_source,
            confidence=confidence,
            resolution=resolution,
            identity_confirmed=(resolution == "strong"),
            status="received",
            received_at=received_at,
            due_at=due_at,
            due_verify=True,
            message_excerpt_masked=excerpt_masked,
            checklist_json=json.dumps(checklist),
        )
        session.add(case_obj)
        session.flush()

        # Log case_received to ledger (ids and enums only)
        append_event(
            session=session,
            event_type="case_received",
            payload={
                "case_id": case_obj.id,
                "case_ref": case_ref,
                "intent": intent,
                "resolution": resolution,
            },
        )
        session.commit()
        session.refresh(case_obj)

        created_cases.append(serialize_case(case_obj))

    return created_cases


# ---------------------------------------------------------------------------
# Case Lifecycle State Machine
# ---------------------------------------------------------------------------
VALID_TRANSITIONS = {
    "received": {"identity_check", "plan"},
    "identity_check": {"plan"},
    "plan": {"approved"},
    "approved": {"executed"},
    "executed": {"closed"},
    "closed": set(),
}


def get_case(session: Session, case_id_or_ref: Union[int, str]) -> Optional[RightsCase]:
    if isinstance(case_id_or_ref, int) or (isinstance(case_id_or_ref, str) and case_id_or_ref.isdigit()):
        c = session.query(RightsCase).filter_by(id=int(case_id_or_ref)).first()
        if c:
            return c
    return session.query(RightsCase).filter_by(case_ref=str(case_id_or_ref)).first()


def confirm_identity_for_case(session: Session, case_id_or_ref: Union[int, str]) -> RightsCase:
    """
    Confirms identity of data principal for the case.
    Transitions status to identity_check and unblocks probable execution.
    Logs case_identity to ledger.
    """
    case = get_case(session, case_id_or_ref)
    if not case:
        raise ValueError(f"Case '{case_id_or_ref}' not found")

    case.identity_confirmed = True
    if case.status == "received":
        case.status = "identity_check"

    if case.plan_id:
        try:
            confirm_identity_for_plan(session, case.plan_id)
        except Exception:
            pass

    append_event(
        session=session,
        event_type="case_identity",
        payload={
            "case_id": case.id,
            "case_ref": case.case_ref,
            "resolution": case.resolution,
            "confirmed": True,
        },
    )
    session.commit()
    session.refresh(case)
    return case


def create_plan_for_case(session: Session, case_id_or_ref: Union[int, str]) -> RightsCase:
    """
    Compiles field-level erasure plan for the case via erasure engine.
    Transitions status from received/identity_check to plan.
    Logs case_plan to ledger.
    """
    case = get_case(session, case_id_or_ref)
    if not case:
        raise ValueError(f"Case '{case_id_or_ref}' not found")

    if case.status not in ("received", "identity_check", "plan"):
        raise ValueError(f"Cannot compile plan in status '{case.status}'; must be 'received', 'identity_check' or 'plan'")

    if not case.person_id:
        raise ValueError(f"Case '{case.case_ref}' has no linked person_id to compile a plan for.")

    # Re-evaluate checklist
    checklist = generate_case_checklist(session, case.person_id)
    case.checklist_json = json.dumps(checklist)

    # Compile erasure plan
    plan_dict = compile_plan(session, case.person_id)
    plan_id = plan_dict.get("plan_id") or plan_dict.get("id")
    plan_hash = plan_dict["plan_hash"]

    # If identity is already confirmed, propagate confirmation to plan
    if case.identity_confirmed:
        try:
            confirmed_plan = confirm_identity_for_plan(session, plan_id)
            plan_hash = confirmed_plan.get("plan_hash", plan_hash)
        except Exception:
            pass

    case.plan_id = plan_id
    case.plan_hash = plan_hash
    case.status = "plan"

    append_event(
        session=session,
        event_type="case_plan",
        payload={
            "case_id": case.id,
            "case_ref": case.case_ref,
            "plan_id": plan_id,
            "plan_hash": plan_hash,
        },
    )
    session.commit()
    session.refresh(case)
    return case


def approve_case(session: Session, case_id_or_ref: Union[int, str], confirm_hash: str) -> RightsCase:
    """
    Approves the case plan using the confirmed SHA-256 plan hash.
    Transitions status from plan to approved.
    Logs case_approved to ledger.
    """
    case = get_case(session, case_id_or_ref)
    if not case:
        raise ValueError(f"Case '{case_id_or_ref}' not found")

    if case.status != "plan":
        raise ValueError(f"Cannot approve case in status '{case.status}'; must be 'plan'")

    if not case.plan_id or not case.plan_hash:
        raise ValueError("Case does not have an active erasure plan to approve.")

    if confirm_hash != case.plan_hash:
        raise ValueError(f"confirm_hash does not match stored plan_hash! Stored: {case.plan_hash[:12]}...")

    # Approve plan in erasure engine
    erasure_approve(session, case.plan_id, confirm_hash)

    case.status = "approved"

    append_event(
        session=session,
        event_type="case_approved",
        payload={
            "case_id": case.id,
            "case_ref": case.case_ref,
            "plan_id": case.plan_id,
        },
    )
    session.commit()
    session.refresh(case)
    return case


def execute_case(session: Session, case_id_or_ref: Union[int, str]) -> RightsCase:
    """
    Executes the approved erasure plan.
    Enforces identity gate: probable identity blocks execution until confirmed by owner.
    Never auto-executes.
    Transitions status from approved to executed.
    Logs case_executed to ledger.
    """
    case = get_case(session, case_id_or_ref)
    if not case:
        raise ValueError(f"Case '{case_id_or_ref}' not found")

    if case.status != "approved":
        raise ValueError(f"Cannot execute case in status '{case.status}'; must be 'approved'")

    # Identity Gate: Probable match blocks execution until confirmed
    if (case.resolution or "").lower() == "probable" and not case.identity_confirmed:
        raise ValueError(
            "Execution refused: Person identity resolution is 'probable' (name-only). "
            "The owner must confirm identity before execution is permitted."
        )

    if not case.plan_id:
        raise ValueError("Case has no plan_id for execution.")

    # Execute redaction in erasure engine
    erasure_execute(session, case.plan_id)

    # Mark checklist items as completed
    if case.checklist_json:
        try:
            items = json.loads(case.checklist_json)
            for it in items:
                it["completed"] = True
            case.checklist_json = json.dumps(items)
        except Exception:
            pass

    case.status = "executed"

    append_event(
        session=session,
        event_type="case_executed",
        payload={
            "case_id": case.id,
            "case_ref": case.case_ref,
            "plan_id": case.plan_id,
        },
    )
    session.commit()
    session.refresh(case)
    return case


def close_case(session: Session, case_id_or_ref: Union[int, str]) -> RightsCase:
    """
    Closes the case after execution or resolution.
    Logs case_closed to ledger.
    """
    case = get_case(session, case_id_or_ref)
    if not case:
        raise ValueError(f"Case '{case_id_or_ref}' not found")

    if case.status not in ("executed", "approved", "received", "identity_check"):
        raise ValueError(f"Cannot close case in status '{case.status}'")

    case.status = "closed"

    append_event(
        session=session,
        event_type="case_closed",
        payload={
            "case_id": case.id,
            "case_ref": case.case_ref,
            "status": "closed",
        },
    )
    session.commit()
    session.refresh(case)
    return case


# ---------------------------------------------------------------------------
# Serializer Helper
# ---------------------------------------------------------------------------
def serialize_case(case: RightsCase) -> Dict[str, Any]:
    checklist = []
    if case.checklist_json:
        try:
            checklist = json.loads(case.checklist_json)
        except Exception:
            checklist = []

    return {
        "id": case.id,
        "case_ref": case.case_ref,
        "person_id": case.person_id,
        "sender_masked": case.sender_masked,
        "intent": case.intent,
        "intent_source": case.intent_source,
        "confidence": case.confidence,
        "resolution": case.resolution,
        "identity_confirmed": case.identity_confirmed,
        "status": case.status,
        "plan_id": case.plan_id,
        "plan_hash": case.plan_hash,
        "received_at": case.received_at.isoformat() if case.received_at else None,
        "due_at": case.due_at.isoformat() if case.due_at else None,
        "due_verify": {
            "due_at": case.due_at.isoformat() if case.due_at else None,
            "response_days": RESPONSE_DAYS,
            "verify": True,
            "verified": False,
        },
        "message_excerpt_masked": case.message_excerpt_masked,
        "checklist": checklist,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }
