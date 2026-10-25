"""
backend/services/rules.py
========================
Compliance rules evaluation engine, questionnaire service, and fact collection.
Evaluates 14 core DPDP readiness rules returning RuleResult(rule_id, state, evidence_refs)
with states in {GREEN, YELLOW, RED, NOT_ASSESSED}.
Strictly avoids eval() on YAML — predicate evaluations execute through a typed registry.
Absence of data yields NOT_ASSESSED; positive evidence is mandatory for GREEN.
"""

from dataclasses import dataclass
import json
import os
from typing import Any, Callable, Dict, List, Optional, Set
import uuid
from sqlalchemy import func
from sqlalchemy.orm import Session
import yaml

from backend.db.models import (
    Column,
    Dataset,
    FlagResult,
    Occurrence,
    Person,
    PurposeLink,
    QuestionnaireAnswer,
)
from backend.services.ledger import append_event

# ---------------------------------------------------------------------------
# Data Models & Constants
# ---------------------------------------------------------------------------

STATES = {"GREEN", "YELLOW", "RED", "NOT_ASSESSED"}

ALLOWED_FIX_ACTIONS = {
    "answer_question",
    "erasure_plan",
    "breach_checklist",
    "review_columns",
    "questionnaire",
}

QUESTIONNAIRE_KEYS = {
    "cctv",
    "personal_phones",
    "vendors",
    "breach_contact",
    "retention_policy",
    "children_served",
    "shared_folder",
    "collection_notice",
}

QUESTIONNAIRE_QUESTIONS = [
    {
        "key": "cctv",
        "title": "CCTV surveillance on premises",
        "question": "Do you operate CCTV cameras in patient, customer, or office premises? Requires visible collection notice (s.5).",
        "options": ["yes", "no", "not_sure"],
    },
    {
        "key": "personal_phones",
        "title": "Staff personal mobile devices",
        "question": "Do staff, contractors, or doctors store patient or customer records on personal phones? (s.8(5)).",
        "options": ["yes", "no", "not_sure"],
    },
    {
        "key": "vendors",
        "title": "Vendors without written agreements",
        "question": "Do you share personal data with external labs, software providers, or accountants without written DPAs? (s.8(2)).",
        "options": ["yes", "no", "not_sure"],
    },
    {
        "key": "breach_contact",
        "title": "Designated breach point of contact",
        "question": "Have you established a breach notification procedure and published a designated point of contact? (s.8(6)).",
        "options": ["yes", "no", "not_sure"],
    },
    {
        "key": "retention_policy",
        "title": "Documented data retention policy",
        "question": "Do you have a written schedule to periodically delete personal data once purpose has expired? (s.8(7)).",
        "options": ["yes", "no", "not_sure"],
    },
    {
        "key": "children_served",
        "title": "Direct processing of minors' data",
        "question": "Do you knowingly serve or retain data of children under 18 requiring verifiable parental consent? (s.9).",
        "options": ["yes", "no", "not_sure"],
    },
    {
        "key": "shared_folder",
        "title": "Customer files in shared or open folder",
        "question": "Do you keep customer or patient files in a shared or open folder, such as a shared drive or a group chat anyone can open?",
        "options": ["yes", "no", "not_sure"],
    },
    {
        "key": "collection_notice",
        "title": "Notice at collection touchpoints",
        "question": "Do you tell people why you collect their details, for example a sign at the desk or a line on your registration form?",
        "options": ["yes", "no", "not_sure"],
    },
]

# Additional rules defined directly for compliance engine
ADDITIONAL_RULES: List[Dict[str, Any]] = [
    {
        "id": "unknown_purposes",
        "title": "Unconfirmed processing purposes for data columns",
        "citation_hint": "s.4 lawful basis & s.6 consent",
        "severity": "high",
        "verify": True,
        "verified": False,
        "source_url": "",
        "whats_right": "No issue found by Kavach's checks: All detected identifier columns have confirmed processing purposes.",
        "whats_not": "One or more personal data columns lack a confirmed processing purpose.",
        "how_to_fix": "Review the question queue and confirm the legitimate business purpose for each column.",
        "fix_action": "answer_question",
        "trigger": {
            "fact": "has_unconfirmed_purposes",
            "operator": "==",
            "value": True,
        },
    },
    {
        "id": "no_named_contact",
        "title": "No designated breach response point of contact",
        "citation_hint": "s.8(6) breach intimation",
        "severity": "high",
        "verify": True,
        "verified": False,
        "source_url": "",
        "whats_right": "Owner reports designated breach notification officer established (not verified by Kavach).",
        "whats_not": "Organization has not appointed a named contact person responsible for breach intimation.",
        "how_to_fix": "Designate a named contact person and implement the breach response checklist.",
        "fix_action": "breach_checklist",
        "trigger": {
            "fact": "breach_contact",
            "operator": "==",
            "value": "no",
        },
    },
]


@dataclass
class RuleResult:
    rule_id: str
    state: str  # RED | YELLOW | GREEN | NOT_ASSESSED
    evidence_refs: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "state": self.state,
            "evidence_refs": self.evidence_refs,
        }


# ---------------------------------------------------------------------------
# Predicate Registry (Safe Condition Evaluator)
# ---------------------------------------------------------------------------

PREDICATES: Dict[str, Callable[[Any, Any], bool]] = {
    "==": lambda f, t: f == t,
    "!=": lambda f, t: f != t,
    ">": lambda f, t: f is not None and f > t,
    ">=": lambda f, t: f is not None and f >= t,
    "<": lambda f, t: f is not None and f < t,
    "<=": lambda f, t: f is not None and f <= t,
    "in": lambda f, t: f in t if f is not None else False,
    "is_empty": lambda f, t: (len(f) == 0) if hasattr(f, "__len__") else (f is None),
    "is_not_empty": lambda f, t: (len(f) > 0) if hasattr(f, "__len__") else (f is not None),
}


def evaluate_condition(cond: Dict[str, Any], facts: Dict[str, Any]) -> bool:
    """Evaluates a structured condition tree against facts dictionary without eval()."""
    if "any" in cond:
        return any(evaluate_condition(c, facts) for c in cond["any"])
    if "all" in cond:
        return all(evaluate_condition(c, facts) for c in cond["all"])

    fact_name = cond.get("fact")
    op = cond.get("operator", "==")
    target_val = cond.get("value")

    fact_val = facts.get(fact_name)
    predicate = PREDICATES.get(op)
    if not predicate:
        return False
    return predicate(fact_val, target_val)


# ---------------------------------------------------------------------------
# Rule Loading & Metadata Helpers
# ---------------------------------------------------------------------------

def load_rules() -> List[Dict[str, Any]]:
    """Loads rules from backend/rules/rules.yaml and merges additional rules."""
    rules_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "rules",
        "rules.yaml",
    )
    with open(rules_path, "r", encoding="utf-8") as f:
        yaml_rules = yaml.safe_load(f) or []

    existing_ids = {r["id"] for r in yaml_rules}
    all_rules = list(yaml_rules)
    for ar in ADDITIONAL_RULES:
        if ar["id"] not in existing_ids:
            all_rules.append(ar)
    return all_rules


def get_rule_definitions_map() -> Dict[str, Dict[str, Any]]:
    """Returns rule definitions indexed by rule_id."""
    return {r["id"]: r for r in load_rules()}


# ---------------------------------------------------------------------------
# Fact Collection
# ---------------------------------------------------------------------------

def collect_facts(db: Session) -> Dict[str, Any]:
    """Collects aggregated facts from database tables and questionnaire."""
    # 1. Questionnaire answers
    qa_rows = db.query(QuestionnaireAnswer).all()
    qa_map = {row.key: row.answer for row in qa_rows}

    # 2. Datasets
    datasets = db.query(Dataset).all()
    wa_datasets = [
        d for d in datasets
        if d.source_type == "whatsapp"
        or "chat" in (d.original_filename or "").lower()
        or "whatsapp" in (d.original_filename or "").lower()
    ]
    staff_datasets = [
        d for d in datasets
        if d.segment == "staff"
        or "staff" in (d.original_filename or "").lower()
        or "employee" in (d.original_filename or "").lower()
    ]

    # 3. Columns
    columns = db.query(Column).all()
    id_cols = [c for c in columns if c.category != "other"]
    health_cols = [c for c in id_cols if c.category == "health"]
    aadhaar_cols = [c for c in id_cols if c.category == "aadhaar"]
    dob_cols = [c for c in id_cols if c.category == "dob"]

    # 4. Purpose Links
    confirmed_links = db.query(PurposeLink).filter(func.lower(PurposeLink.status) == "confirmed").all()
    confirmed_col_ids = {pl.column_id for pl in confirmed_links}

    # 5. Entity sprawl
    total_people = db.query(Person).count()
    max_person_datasets = 0
    if total_people > 0:
        res = (
            db.query(
                Occurrence.person_id,
                func.count(func.distinct(Column.dataset_id)),
            )
            .join(Column, Occurrence.column_id == Column.id)
            .group_by(Occurrence.person_id)
            .order_by(func.count(func.distinct(Column.dataset_id)).desc())
            .first()
        )
        if res:
            max_person_datasets = res[1]

    # Return structured facts
    return {
        # Questionnaire
        "cctv": qa_map.get("cctv"),
        "personal_phones": qa_map.get("personal_phones"),
        "vendors": qa_map.get("vendors"),
        "breach_contact": qa_map.get("breach_contact"),
        "retention_policy": qa_map.get("retention_policy"),
        "children_served": qa_map.get("children_served"),
        "shared_folder": qa_map.get("shared_folder"),
        "collection_notice": qa_map.get("collection_notice"),
        # Entities & Counts
        "total_datasets": len(datasets),
        "total_columns": len(columns),
        "total_people": total_people,
        "max_person_datasets": max_person_datasets,
        "datasets": datasets,
        "whatsapp_datasets": wa_datasets,
        "staff_datasets": staff_datasets,
        "columns": columns,
        "identifier_columns": id_cols,
        "health_columns": health_cols,
        "aadhaar_columns": aadhaar_cols,
        "dob_columns": dob_cols,
        "confirmed_col_ids": confirmed_col_ids,
    }


# ---------------------------------------------------------------------------
# Rule Evaluation Engine
# ---------------------------------------------------------------------------

def evaluate_rules(db: Session) -> List[RuleResult]:
    """
    Evaluates all DPDP compliance rules against collected facts.
    Returns list of RuleResult objects with states: RED, YELLOW, GREEN, NOT_ASSESSED.
    Absence of input data always returns NOT_ASSESSED.
    GREEN requires positive verification evidence.
    """
    facts = collect_facts(db)
    results: List[RuleResult] = []

    # 1. unknown_purposes
    id_cols = facts["identifier_columns"]
    confirmed_ids = facts["confirmed_col_ids"]
    if len(id_cols) == 0:
        results.append(RuleResult("unknown_purposes", "NOT_ASSESSED", []))
    else:
        unconfirmed = [c for c in id_cols if c.id not in confirmed_ids]
        if len(unconfirmed) == 0:
            results.append(RuleResult("unknown_purposes", "GREEN", [f"col:{c.id}" for c in id_cols]))
        else:
            tier3 = [
                c for c in unconfirmed
                if c.impact_tier == "3" or c.category in ("aadhaar", "pan", "health", "bank_account")
            ]
            if len(tier3) > 0:
                results.append(RuleResult("unknown_purposes", "RED", [f"col:{c.id}" for c in tier3]))
            else:
                results.append(RuleResult("unknown_purposes", "YELLOW", [f"col:{c.id}" for c in unconfirmed]))

    # 2. no_named_contact
    bc = facts["breach_contact"]
    if bc is None or bc == "unanswered":
        results.append(RuleResult("no_named_contact", "NOT_ASSESSED", []))
    elif bc == "yes":
        results.append(RuleResult("no_named_contact", "GREEN", ["questionnaire:breach_contact=yes", "Owner reports designated breach notification officer established (not verified by Kavach)"]))
    elif bc == "no":
        results.append(RuleResult("no_named_contact", "RED", ["questionnaire:breach_contact=no"]))
    else:  # not_sure
        results.append(RuleResult("no_named_contact", "YELLOW", ["questionnaire:breach_contact=not_sure"]))

    # 3. breach_contact_process (synced with breach_contact)
    if bc is None or bc == "unanswered":
        results.append(RuleResult("breach_contact_process", "NOT_ASSESSED", []))
    elif bc == "yes":
        results.append(RuleResult("breach_contact_process", "GREEN", ["questionnaire:breach_contact=yes", "Owner reports a designated breach contact person and notification procedure are established (not verified by Kavach)"]))
    elif bc == "no":
        results.append(RuleResult("breach_contact_process", "RED", ["questionnaire:breach_contact=no"]))
    else:
        results.append(RuleResult("breach_contact_process", "YELLOW", ["questionnaire:breach_contact=not_sure"]))

    # 4. notice_at_collection
    cn = facts.get("collection_notice")
    if cn == "no":
        results.append(RuleResult("notice_at_collection", "YELLOW", ["questionnaire:collection_notice=no"]))
    elif cn == "yes":
        results.append(RuleResult("notice_at_collection", "GREEN", ["questionnaire:collection_notice=yes", "Owner reports a notice is shown (not verified by Kavach)"]))
    else:
        results.append(RuleResult("notice_at_collection", "NOT_ASSESSED", []))

    # 5. unrestricted_shared_source
    sf = facts.get("shared_folder")
    if sf == "yes":
        results.append(RuleResult("unrestricted_shared_source", "RED", ["questionnaire:shared_folder=yes"]))
    elif sf == "no":
        results.append(RuleResult("unrestricted_shared_source", "GREEN", ["questionnaire:shared_folder=no", "Owner reports no shared folders (not verified by Kavach)"]))
    else:
        results.append(RuleResult("unrestricted_shared_source", "NOT_ASSESSED", []))

    # 6. data_on_personal_phones (driven by personal_phones, independent of shared_folder)
    pp = facts.get("personal_phones")
    if pp is None or pp == "unanswered":
        results.append(RuleResult("data_on_personal_phones", "NOT_ASSESSED", []))
    elif pp == "no":
        results.append(RuleResult("data_on_personal_phones", "GREEN", ["questionnaire:personal_phones=no", "Owner reports staff are prohibited from holding customer records on personal phones (not verified by Kavach)"]))
    elif pp == "yes":
        results.append(RuleResult("data_on_personal_phones", "RED", ["questionnaire:personal_phones=yes"]))
    else:
        results.append(RuleResult("data_on_personal_phones", "YELLOW", ["questionnaire:personal_phones=not_sure"]))

    # 7. vendors_unwritten_agreement
    vendors = facts["vendors"]
    if vendors is None or vendors == "unanswered":
        results.append(RuleResult("vendors_unwritten_agreement", "NOT_ASSESSED", []))
    elif vendors == "no":
        results.append(RuleResult("vendors_unwritten_agreement", "GREEN", ["questionnaire:vendors=no", "Owner reports written Data Processing Agreements are executed with all processors (not verified by Kavach)"]))
    elif vendors == "yes":
        results.append(RuleResult("vendors_unwritten_agreement", "RED", ["questionnaire:vendors=yes"]))
    else:
        results.append(RuleResult("vendors_unwritten_agreement", "YELLOW", ["questionnaire:vendors=not_sure"]))

    # 8. retention_policy
    ret = facts["retention_policy"]
    if ret is None or ret == "unanswered":
        results.append(RuleResult("retention_policy", "NOT_ASSESSED", []))
    elif ret == "yes":
        results.append(RuleResult("retention_policy", "GREEN", ["questionnaire:retention_policy=yes", "Owner reports a written data retention and scheduled disposal policy is documented (not verified by Kavach)"]))
    elif ret == "no":
        results.append(RuleResult("retention_policy", "YELLOW", ["questionnaire:retention_policy=no"]))
    else:
        results.append(RuleResult("retention_policy", "YELLOW", ["questionnaire:retention_policy=not_sure"]))

    # 9. minors_parental_consent
    children = facts["children_served"]
    dob_cols = facts["dob_columns"]
    if (children is None or children == "unanswered") and len(dob_cols) == 0:
        results.append(RuleResult("minors_parental_consent", "NOT_ASSESSED", []))
    elif children == "yes":
        results.append(RuleResult("minors_parental_consent", "RED", ["questionnaire:children_served=yes"]))
    elif children == "no":
        results.append(RuleResult("minors_parental_consent", "GREEN", ["questionnaire:children_served=no", "Owner reports no unconsented processing of children's personal data (not verified by Kavach)"]))
    elif children == "not_sure":
        results.append(RuleResult("minors_parental_consent", "YELLOW", ["questionnaire:children_served=not_sure"]))
    else:
        # dob cols exist, but children_served is unanswered
        results.append(RuleResult("minors_parental_consent", "YELLOW", [f"col:{c.id}" for c in dob_cols]))

    # 10. health_data_safeguards
    health_cols = facts["health_columns"]
    if len(health_cols) == 0:
        results.append(RuleResult("health_data_safeguards", "NOT_ASSESSED", []))
    else:
        unconfirmed_health = [c for c in health_cols if c.id not in confirmed_ids]
        if len(unconfirmed_health) == 0:
            results.append(RuleResult("health_data_safeguards", "GREEN", [f"col:{c.id}" for c in health_cols]))
        else:
            results.append(RuleResult("health_data_safeguards", "RED", [f"col:{c.id}" for c in unconfirmed_health]))

    # 11. aadhaar_in_chat
    wa_datasets = facts["whatsapp_datasets"]
    if len(wa_datasets) == 0:
        results.append(RuleResult("aadhaar_in_chat", "NOT_ASSESSED", []))
    else:
        wa_ids = {str(d.id) for d in wa_datasets} | {str(d.dataset_id) for d in wa_datasets if d.dataset_id} | {d.id for d in wa_datasets}
        wa_aadhaar = [c for c in facts["aadhaar_columns"] if c.dataset_id in wa_ids]
        if len(wa_aadhaar) > 0:
            results.append(RuleResult("aadhaar_in_chat", "RED", [f"col:{c.id}" for c in wa_aadhaar]))
        else:
            # Positive scan: WhatsApp dataset exists and has verified confirmed columns
            wa_cols = [c for c in id_cols if c.dataset_id in wa_ids]
            if len(wa_cols) > 0 and all(c.id in confirmed_ids for c in wa_cols):
                results.append(RuleResult("aadhaar_in_chat", "GREEN", [f"dataset:{d.id}" for d in wa_datasets]))
            else:
                results.append(RuleResult("aadhaar_in_chat", "YELLOW", [f"dataset:{d.id}" for d in wa_datasets]))

    # 12. aadhaar_multiple_files
    aadhaar_cols = facts["aadhaar_columns"]
    aadhaar_ds_ids = {c.dataset_id for c in aadhaar_cols}
    if len(aadhaar_ds_ids) == 0:
        results.append(RuleResult("aadhaar_multiple_files", "NOT_ASSESSED", []))
    elif len(aadhaar_ds_ids) > 1:
        results.append(RuleResult("aadhaar_multiple_files", "RED", [f"dataset:{did}" for did in aadhaar_ds_ids]))
    else:
        single_ds_id = list(aadhaar_ds_ids)[0]
        if all(c.id in confirmed_ids for c in aadhaar_cols):
            results.append(RuleResult("aadhaar_multiple_files", "GREEN", [f"dataset:{single_ds_id}"]))
        else:
            results.append(RuleResult("aadhaar_multiple_files", "YELLOW", [f"dataset:{single_ds_id}"]))

    # 13. employee_data_lawful_basis
    staff_datasets = facts["staff_datasets"]
    if len(staff_datasets) == 0:
        results.append(RuleResult("employee_data_lawful_basis", "NOT_ASSESSED", []))
    else:
        staff_ids = {str(d.id) for d in staff_datasets} | {str(d.dataset_id) for d in staff_datasets if d.dataset_id} | {d.id for d in staff_datasets}
        staff_cols = [c for c in id_cols if c.dataset_id in staff_ids]
        if len(staff_cols) > 0 and all(c.id in confirmed_ids for c in staff_cols):
            results.append(RuleResult("employee_data_lawful_basis", "GREEN", [f"dataset:{d.id}" for d in staff_datasets]))
        else:
            results.append(RuleResult("employee_data_lawful_basis", "YELLOW", [f"dataset:{d.id}" for d in staff_datasets]))

    # 14. data_sprawl_files
    total_people = facts["total_people"]
    max_person_ds = facts["max_person_datasets"]
    if total_people == 0:
        results.append(RuleResult("data_sprawl_files", "NOT_ASSESSED", []))
    elif max_person_ds >= 3:
        results.append(RuleResult("data_sprawl_files", "YELLOW", [f"max_person_datasets:{max_person_ds}"]))
    else:
        if len(id_cols) > 0 and all(c.id in confirmed_ids for c in id_cols):
            results.append(RuleResult("data_sprawl_files", "GREEN", [f"max_person_datasets:{max_person_ds}"]))
        else:
            results.append(RuleResult("data_sprawl_files", "YELLOW", [f"max_person_datasets:{max_person_ds}"]))

    return results


# ---------------------------------------------------------------------------
# Questionnaire Persistence & Retrieval
# ---------------------------------------------------------------------------

def get_questionnaire_questions(db: Session) -> List[Dict[str, Any]]:
    """Returns 6 operational questionnaire questions with current saved answers."""
    qa_map = {row.key: row.answer for row in db.query(QuestionnaireAnswer).all()}
    output = []
    for q in QUESTIONNAIRE_QUESTIONS:
        q_copy = dict(q)
        q_copy["answer"] = qa_map.get(q["key"], "unanswered")
        output.append(q_copy)
    return output


def save_questionnaire_answer(db: Session, key: str, answer: str) -> None:
    """Saves answer for a questionnaire key and appends ledger event."""
    key_clean = key.strip().lower()
    if key_clean not in QUESTIONNAIRE_KEYS:
        raise ValueError(f"Unknown questionnaire key: '{key}'")

    ans_clean = answer.strip().lower()
    if ans_clean not in {"yes", "no", "not_sure"}:
        raise ValueError(f"Invalid answer '{answer}'. Must be one of: 'yes', 'no', 'not_sure'.")

    qa = db.query(QuestionnaireAnswer).filter(QuestionnaireAnswer.key == key_clean).first()
    if not qa:
        qa = QuestionnaireAnswer(key=key_clean, answer=ans_clean)
        db.add(qa)
    else:
        qa.answer = ans_clean

    # Append ledger event
    append_event(
        session=db,
        event_type="questionnaire_answer",
        payload={
            "question_key": key_clean,
            "answer": ans_clean,
        },
    )
    db.commit()

    from backend.services.purge import touch_activity
    touch_activity(db)


# ---------------------------------------------------------------------------
# Flags Evaluation Snapshot & Retrieval
# ---------------------------------------------------------------------------

def run_flags(db: Session) -> Dict[str, Any]:
    """
    Evaluates all rules, checks state differences against previous run,
    logs 'flag_change' ledger events for changes, and stores a new snapshot in flag_results.
    """
    results = evaluate_rules(db)
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    # Fetch previous run results
    last_flag = db.query(FlagResult).order_by(FlagResult.id.desc()).first()
    prev_states: Dict[str, str] = {}
    if last_flag:
        last_run_flags = db.query(FlagResult).filter(FlagResult.run_id == last_flag.run_id).all()
        for lf in last_run_flags:
            prev_states[lf.rule_id] = lf.state

    # Compare changes and record snapshot
    for r in results:
        old_state = prev_states.get(r.rule_id, "NOT_ASSESSED")
        if old_state != r.state:
            append_event(
                session=db,
                event_type="flag_change",
                payload={
                    "rule_id": r.rule_id,
                    "old_state": old_state,
                    "new_state": r.state,
                },
            )

        db.add(
            FlagResult(
                run_id=run_id,
                rule_id=r.rule_id,
                state=r.state,
                evidence_refs=json.dumps(r.evidence_refs),
            )
        )

    db.commit()

    return {
        "run_id": run_id,
        "results": [r.to_dict() for r in results],
    }


def get_latest_flags(db: Session) -> List[Dict[str, Any]]:
    """Retrieves latest flag results enriched with rules.yaml metadata."""
    last_flag = db.query(FlagResult).order_by(FlagResult.id.desc()).first()
    if not last_flag:
        # Run flags snapshot if none exists
        run_flags(db)
        last_flag = db.query(FlagResult).order_by(FlagResult.id.desc()).first()

    flags = db.query(FlagResult).filter(FlagResult.run_id == last_flag.run_id).all()
    rule_map = get_rule_definitions_map()

    output = []
    for f in flags:
        r_def = rule_map.get(f.rule_id, {})
        ev_refs = []
        if f.evidence_refs:
            try:
                ev_refs = json.loads(f.evidence_refs)
            except (json.JSONDecodeError, TypeError):
                ev_refs = [f.evidence_refs]

        output.append({
            "rule_id": f.rule_id,
            "state": f.state,
            "title": r_def.get("title", f.rule_id),
            "citation_hint": r_def.get("citation_hint", ""),
            "verify": r_def.get("verify", True),
            "verified": r_def.get("verified", False),
            "whats_right": r_def.get("whats_right", "No issue found by Kavach's checks."),
            "whats_not": r_def.get("whats_not", ""),
            "how_to_fix": r_def.get("how_to_fix", ""),
            "fix_action": r_def.get("fix_action", "review_columns"),
            "evidence_refs": ev_refs,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        })

    return output
