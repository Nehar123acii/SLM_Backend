"""
backend/services/breach.py
==========================
Breach blast-radius simulation and statutory DPDP readiness module for Kavach.
Module label: "readiness for obligations from May 2027"

Provides:
- Blast-radius calculation across occurrences and resolved people
- Explainable severity ordering (low/medium/high) that NEVER decides notification duties
- Statutory notification clocks (DPDP Rule 7; Stage 1 without delay, Stage 2 within 72h)
- Statutory draft generation keyed to required clauses, watermarked DRAFT SIMULATION
- 6-stage response checklist with IT advisor advice and other-law reporting checks
- Logging to tamper-evident ledger (breach_simulated, incident_opened, incident_step, notice_sent)
"""

import datetime
from datetime import timezone
import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import yaml
from sqlalchemy import or_, cast, String
from sqlalchemy.orm import Session

from backend.config import (
    BREACH_STAGE_1_DESCRIPTION,
    BREACH_STAGE_2_HOURS,
    settings,
)
from backend.db.models import (
    BreachSimulation,
    Column,
    Dataset,
    Incident,
    NoticeSent,
    Occurrence,
    Person,
    utc_now,
)
from backend.services.ledger import append_event
from backend.services.i18n import t

MODULE_LABEL = "readiness for obligations from May 2027"
TIER_3_HIGH_IMPACT = {"aadhaar", "pan", "bank_account", "health", "health_term"}

# PII Regex patterns for intake guard (matching K5 payload guard)
_PHONE_PATTERN = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{9}\b|\b\d{10}\b")
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_AADHAAR_PATTERN = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")


def validate_incident_text(text: Optional[str]) -> None:
    """
    Validates that free-text summary or report contains no raw personal data values
    (Phone, Email, Aadhaar, PAN) before storing.
    """
    if not text:
        return
    clean = text.strip()

    # Check Aadhaar
    if _AADHAAR_PATTERN.search(clean):
        digits = re.sub(r"\D", "", clean)
        if len(digits) == 12:
            raise ValueError(f"Personal data detected in incident text (Aadhaar pattern): '{text[:30]}...'")

    # Check PAN
    if _PAN_PATTERN.search(clean):
        raise ValueError(f"Personal data detected in incident text (PAN pattern): '{text[:30]}...'")

    # Check Email
    if _EMAIL_PATTERN.search(clean):
        raise ValueError(f"Personal data detected in incident text (Email pattern): '{text[:30]}...'")

    # Check Phone
    if _PHONE_PATTERN.search(clean):
        digits = re.sub(r"\D", "", clean)
        if len(digits) == 10 or (len(digits) == 12 and digits.startswith("91")):
            raise ValueError(f"Personal data detected in incident text (Phone pattern): '{text[:30]}...'")


def load_scenarios() -> List[Dict[str, Any]]:
    """Load breach simulation scenarios from rules/breach_scenarios.yaml."""
    yaml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules", "breach_scenarios.yaml")
    if not os.path.exists(yaml_path):
        return []
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or []


def get_scenario_by_id(scenario_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single breach scenario definition by id."""
    scenarios = load_scenarios()
    for s in scenarios:
        if s.get("id") == scenario_id:
            return s
    return None


def format_time_elapsed(seconds: int) -> str:
    """Format elapsed seconds into human-readable string."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m elapsed"
    if minutes > 0:
        return f"{minutes}m {secs}s elapsed"
    return f"{secs}s elapsed"


# ---------------------------------------------------------------------------
# Part A: Blast Radius
# ---------------------------------------------------------------------------

def blast_radius(session: Session, source_ids: List[Union[str, int]]) -> Dict[str, Any]:
    """
    Computes blast radius from occurrences and people for the given source datasets.
    Returns:
    - confirmed_people: count of individuals with strong resolution
    - possible_people: count of individuals with probable/unresolved resolution
    - total_people: sum of confirmed and possible
    - category_breakdown: counts of occurrences and distinct people per category
    - high_impact_categories: tier 3 categories present (aadhaar, pan, bank_account, health)
    - minors_involved: count of minors identified
    - only_channel_warnings: list of warnings for people whose only registered channel is in the leaked source(s)
    Counts only; zero personal values.
    """
    if not source_ids:
        return {
            "source_ids": [],
            "dataset_ids": [],
            "records_count": 0,
            "confirmed_people": 0,
            "possible_people": 0,
            "total_people": 0,
            "people_range": "0 - 0",
            "category_breakdown": {},
            "high_impact_categories": [],
            "minors_involved": 0,
            "minors_count": 0,
            "is_minor_count": 0,
            "only_channel_warnings": [],
        }

    str_sources = [str(s) for s in source_ids]

    # Resolve datasets by dataset_id, original_filename, or integer id
    datasets = (
        session.query(Dataset)
        .filter(
            or_(
                Dataset.dataset_id.in_(str_sources),
                Dataset.original_filename.in_(str_sources),
                cast(Dataset.id, String).in_(str_sources),
            )
        )
        .all()
    )

    if not datasets:
        # Fallback: if no direct dataset found, search columns where locator contains any source name
        matching_columns = (
            session.query(Column)
            .filter(or_(*[Column.locator.like(f"%{s}%") for s in str_sources]))
            .all()
        )
        dataset_ids = list({c.dataset_id for c in matching_columns})
        datasets = session.query(Dataset).filter(Dataset.dataset_id.in_(dataset_ids)).all()

    resolved_dataset_ids = [d.dataset_id for d in datasets]
    total_records = sum(d.row_count for d in datasets)

    # Find columns for affected datasets
    columns = session.query(Column).filter(Column.dataset_id.in_(resolved_dataset_ids)).all()
    col_ids = [c.id for c in columns]
    col_map = {c.id: c for c in columns}

    if not col_ids:
        return {
            "source_ids": str_sources,
            "dataset_ids": resolved_dataset_ids,
            "records_count": total_records,
            "confirmed_people": 0,
            "possible_people": 0,
            "total_people": 0,
            "people_range": "0 - 0",
            "category_breakdown": {},
            "high_impact_categories": [],
            "minors_involved": 0,
            "minors_count": 0,
            "is_minor_count": 0,
            "only_channel_warnings": [],
        }

    # Fetch occurrences belonging to these columns
    occurrences = session.query(Occurrence).filter(Occurrence.column_id.in_(col_ids)).all()

    # Identify unique affected people
    affected_pids = {occ.person_id for occ in occurrences if occ.person_id is not None}
    people = session.query(Person).filter(Person.id.in_(list(affected_pids))).all() if affected_pids else []
    person_map = {p.id: p for p in people}

    confirmed_pids = {pid for pid in affected_pids if person_map.get(pid) and person_map[pid].resolution.lower() == "strong"}
    possible_pids = {pid for pid in affected_pids if pid not in confirmed_pids}

    confirmed_count = len(confirmed_pids)
    possible_count = len(possible_pids)
    total_people = len(affected_pids)
    people_range_str = f"{confirmed_count} - {total_people}"

    # Breakdown by category
    cat_occ_counts: Dict[str, int] = {}
    cat_people: Dict[str, Set[int]] = {}
    minor_occs_count = 0
    minor_pids: Set[int] = set()

    for occ in occurrences:
        col = col_map.get(occ.column_id)
        cat = (col.category if col and col.category else "other").lower()
        cat_occ_counts[cat] = cat_occ_counts.get(cat, 0) + 1

        if occ.person_id is not None:
            cat_people.setdefault(cat, set()).add(occ.person_id)

        # Check minor status
        if getattr(occ, "is_minor", False) is True:
            minor_occs_count += 1
            if occ.person_id is not None:
                minor_pids.add(occ.person_id)

    category_breakdown = {}
    high_impact_found = []
    for cat, count in sorted(cat_occ_counts.items()):
        is_hi = cat in TIER_3_HIGH_IMPACT
        if is_hi:
            high_impact_found.append(cat)
        category_breakdown[cat] = {
            "category": cat,
            "occurrence_count": count,
            "people_count": len(cat_people.get(cat, set())),
            "is_high_impact": is_hi,
        }

    minors_involved_count = max(minor_occs_count, len(minor_pids))

    # Check for persons whose ONLY registered contact channel is in the leaked source(s)
    only_channel_warnings: List[str] = []
    contact_categories = {"phone", "email"}
    for pid in sorted(affected_pids):
        # Query all contact occurrences across the entire database for this person
        all_contact_occs = (
            session.query(Occurrence)
            .join(Column, Occurrence.column_id == Column.id)
            .filter(
                Occurrence.person_id == pid,
                Column.category.in_(list(contact_categories)),
            )
            .all()
        )
        if all_contact_occs:
            # Check if every contact occurrence is inside the breached columns
            all_in_breach = all(occ.column_id in col_ids for occ in all_contact_occs)
            if all_in_breach:
                only_channel_warnings.append(
                    f"Person #{pid}: only registered contact channel is in the affected data source."
                )

    return {
        "source_ids": str_sources,
        "dataset_ids": resolved_dataset_ids,
        "records_count": total_records,
        "confirmed_people": confirmed_count,
        "possible_people": possible_count,
        "total_people": total_people,
        "people_range": people_range_str,
        "category_breakdown": category_breakdown,
        "high_impact_categories": sorted(list(set(high_impact_found))),
        "minors_involved": minors_involved_count,
        "minors_count": minors_involved_count,
        "is_minor_count": minors_involved_count,
        "only_channel_warnings": only_channel_warnings,
    }


# Severity (low/medium/high) only orders the work. It must never decide whether to notify.
def calculate_severity(
    blast_data: Dict[str, Any],
    exposure_types: Optional[List[str]] = None,
    device_protected: str = "unknown",
) -> Tuple[str, int, List[Dict[str, Any]]]:
    """
    Computes explainable severity score and level (low/medium/high).
    NOTE: Severity only orders and prioritizes operational incident triage;
    it must NEVER decide whether statutory notification to the Board or data principals is required.
    """
    exposure_types = exposure_types or ["confidentiality"]
    norm_prot = (device_protected or "unknown").strip().lower()

    factors: List[Dict[str, Any]] = []

    # High-impact categories
    hi_cats = blast_data.get("high_impact_categories", [])
    for c in hi_cats:
        if c in ["aadhaar", "pan", "bank_account"]:
            factors.append({
                "factor": f"high_impact_{c}",
                "points": 15,
                "reason": f"High-impact category present: {c.replace('_', ' ').upper()} exposed in affected data.",
            })
        elif c in ["health", "health_term"]:
            factors.append({
                "factor": "health_data",
                "points": 20,
                "reason": "Health and clinical records exposed (sensitive personal data).",
            })

    # Minors
    if blast_data.get("minors_involved", 0) > 0:
        factors.append({
            "factor": "minors",
            "points": 20,
            "reason": f"Children's data involved: {blast_data.get('minors_involved')} minor record(s) flagged.",
        })

    # Volume
    total_people = blast_data.get("total_people", 0)
    if total_people >= 100:
        factors.append({
            "factor": "volume",
            "points": 30,
            "reason": f"High volume: {total_people} individuals affected (>= 100 threshold).",
        })
    elif total_people >= 50:
        factors.append({
            "factor": "volume",
            "points": 20,
            "reason": f"Moderate volume: {total_people} individuals affected (>= 50 threshold).",
        })
    elif total_people >= 10:
        factors.append({
            "factor": "volume",
            "points": 10,
            "reason": f"Standard volume: {total_people} individuals affected (>= 10 threshold).",
        })
    else:
        factors.append({
            "factor": "volume",
            "points": 5,
            "reason": f"Low volume: {total_people} individuals affected (< 10 threshold).",
        })

    # Availability loss (ransomware)
    if "availability" in exposure_types:
        factors.append({
            "factor": "availability_loss",
            "points": 20,
            "reason": "Availability loss: disruption or encryption of operational records.",
        })

    # Device protection
    if norm_prot == "no":
        factors.append({
            "factor": "device_unprotected",
            "points": 15,
            "reason": "Device unprotected: lacked verified full-disk encryption or access credentials (+15 pts).",
        })
    elif norm_prot == "yes":
        factors.append({
            "factor": "device_protected",
            "points": -10,
            "reason": "Device protected: active encryption and access credentials verified (-10 pts).",
        })
    else:
        factors.append({
            "factor": "device_protection_unknown",
            "points": 10,
            "reason": "Device protection unknown: treated as unverified (+10 pts).",
        })

    total_score = sum(f["points"] for f in factors)
    if total_score < 25:
        severity_level = "low"
    elif total_score < 45:
        severity_level = "medium"
    else:
        severity_level = "high"

    return severity_level, total_score, factors


# ---------------------------------------------------------------------------
# Part B: Clocks (DPDP Rule 7)
# ---------------------------------------------------------------------------

def calculate_clocks(
    aware_at: Union[str, datetime.datetime],
    board_extension_requested: bool = False,
    current_time: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """
    Computes statutory DPDP Rule 7 countdown and elapsed time clocks.
    Module label: "readiness for obligations from May 2027" (the rules come into force 13 May 2027).

    - Board first intimation: "without delay", elapsed time since aware_at; no deadline invented.
    - Board detailed report: due at aware_at + BREACH_STAGE_2_HOURS (72h).
      When board_extension_requested is True, status is "extension requested" instead of "overdue".
    - Individuals intimation: "without delay", elapsed time only.
    - Citation chips: verify: true, verified: false.
    """
    if isinstance(aware_at, str):
        clean_aware = aware_at.replace("Z", "+00:00")
        aware_dt = datetime.datetime.fromisoformat(clean_aware)
    elif isinstance(aware_at, datetime.datetime):
        aware_dt = aware_at
    else:
        aware_dt = datetime.datetime.now(timezone.utc)

    if aware_dt.tzinfo is None:
        aware_dt = aware_dt.replace(tzinfo=timezone.utc)
    else:
        aware_dt = aware_dt.astimezone(timezone.utc)

    now_dt = current_time or datetime.datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    else:
        now_dt = now_dt.astimezone(timezone.utc)

    elapsed_seconds = max(0, int((now_dt - aware_dt).total_seconds()))
    elapsed_display = format_time_elapsed(elapsed_seconds)

    stage_2_due_dt = aware_dt + datetime.timedelta(hours=BREACH_STAGE_2_HOURS)
    seconds_remaining = int((stage_2_due_dt - now_dt).total_seconds())

    if board_extension_requested:
        stage_2_status = "extension requested"
    elif now_dt > stage_2_due_dt:
        stage_2_status = "overdue"
    else:
        stage_2_status = "countdown"

    citation_chips = [
        {"source": "DPDP Rule 7", "verify": True, "verified": False}
    ]

    return {
        "module_label": MODULE_LABEL,
        "aware_at": aware_dt.isoformat(),
        "current_time": now_dt.isoformat(),
        "board_first_intimation": {
            "title": "Stage 1: Preliminary Intimation to Board",
            "requirement": BREACH_STAGE_1_DESCRIPTION,
            "elapsed_seconds": elapsed_seconds,
            "elapsed_display": elapsed_display,
            "deadline": None,
            "note": "Fiduciary must inform the Board without delay; no statutory deadline is invented.",
            "chips": citation_chips,
        },
        "board_detailed_report": {
            "title": "Stage 2: Detailed Incident Report to Board",
            "requirement": f"Within {BREACH_STAGE_2_HOURS} hours of awareness",
            "due_at": stage_2_due_dt.isoformat(),
            "deadline": stage_2_due_dt.isoformat(),
            "hours_limit": BREACH_STAGE_2_HOURS,
            "seconds_remaining": seconds_remaining,
            "board_extension_requested": board_extension_requested,
            "status": stage_2_status,
            "note": "Extendable upon written request submitted to the Data Protection Board.",
            "chips": citation_chips,
        },
        "individual_notice": {
            "title": "Intimation to Affected Individuals",
            "requirement": "without delay",
            "elapsed_seconds": elapsed_seconds,
            "elapsed_display": elapsed_display,
            "deadline": None,
            "note": "Data principals must be intimated without delay in plain language.",
            "chips": citation_chips,
        },
    }


# ---------------------------------------------------------------------------
# Part D: Notices Keyed to Clauses (Marked "DRAFT SIMULATION")
# ---------------------------------------------------------------------------

def generate_individual_notice(
    scenario_title: str,
    scenario_desc: str,
    categories: List[str],
    aware_at_dt: datetime.datetime,
    lang: str = "en",
) -> str:
    """
    Generates draft notice for affected individuals structured with clauses (a) to (e).
    Marked strictly with DRAFT SIMULATION. Zero raw PII; placeholders only.
    """
    cats_title = [c.replace("_", " ").title() for c in categories] or ["Personal Contact Details"]
    categories_list_str = "\n".join(f"- {c}" for c in cats_title)

    consequences = []
    if any(c in categories for c in ["pan", "bank_account", "aadhaar"]):
        consequences.append("- Potential financial phishing, unauthorized impersonation, or credential misuse.")
    if any(c in categories for c in ["health", "health_term"]):
        consequences.append("- Confidentiality exposure of diagnostic or appointment notes.")
    if any(c in categories for c in ["phone", "email"]):
        consequences.append("- Unsolicited marketing communications, spam, or phishing attempts.")
    if not consequences:
        consequences.append("- Potential privacy intrusion or unsolicited contact.")
    consequences_str = "\n".join(consequences)

    date_str = aware_at_dt.strftime("%d %B %Y")
    
    header = str(t("notices.notice_header", lang=lang))
    cl_a = str(t("notices.clause_a_title", lang=lang))
    cl_b = str(t("notices.clause_b_title", lang=lang))
    cl_c = str(t("notices.clause_c_title", lang=lang))
    cl_d = str(t("notices.clause_d_title", lang=lang))
    cl_e = str(t("notices.clause_e_title", lang=lang))
    watermark = str(t("notices.draft_watermark", lang=lang))

    return f"""# {watermark}

## {header}

**Date:** [DATE_TIME]
**From:** [BUSINESS_NAME]
**Contact:** [CONTACT_PERSON] ([PHONE_OR_EMAIL])

Dear Patron,

We are writing to provide transparent notification of a recent security incident that may have involved information related to you.

### {cl_a}
On {date_str}, an incident was identified involving {scenario_title.lower()}: {scenario_desc}. Prompt containment steps were initiated to secure the environment.

### {cl_b}
Based on our assessment of the records involved, potential implications include:
{consequences_str}

### {cl_c}
We have taken the following mitigation steps:
- Isolated affected repositories and revoked compromised access tokens.
- Initiated required regulatory reporting to the Data Protection Board of India.
- Conducted integrity checks across backups and tightened access controls.

### {cl_d}
To safeguard your privacy and account security:
- Remain vigilant against unexpected calls, SMS, or emails asking for OTPs, passwords, or personal credentials.
- Remember that [BUSINESS_NAME] will NEVER contact you to ask for payment PINs or banking passwords.
- Report any suspicious or unsolicited communication referencing our services to our response contact below.

### {cl_e}
If you have any questions or require support, please contact our designated response desk:
- **Designated Person:** [CONTACT_PERSON]
- **Phone / Email:** [PHONE_OR_EMAIL]
- **Organization:** [BUSINESS_NAME]

---
*Notice watermark: DRAFT SIMULATION generated by Kavach for fiduciary review prior to dispatch.*
"""


def generate_board_first_intimation(
    scenario_title: str,
    scenario_desc: str,
    exposure_types: List[str],
    affected_sources: List[str],
    records_count: int,
    confirmed_people: int,
    possible_people: int,
    categories: List[str],
    aware_at_dt: datetime.datetime,
) -> str:
    """
    Generates preliminary Stage 1 intimation to the Data Protection Board of India.
    Includes: nature, extent, timing, location, likely impact.
    Marked strictly with DRAFT SIMULATION. Zero raw personal data.
    """
    exposure_str = ", ".join(t.capitalize() for t in exposure_types)
    sources_str = ", ".join(affected_sources) if affected_sources else "[AFFECTED_REPOSITORIES]"
    cats_str = ", ".join(c.replace("_", " ").title() for c in categories) or "None detected"

    return f"""# DRAFT SIMULATION - DPDP Act Readiness (May 2027)

## DPDP Rule 7 Preliminary Breach Intimation to Data Protection Board of India

**Intimation Type:** Stage 1 Preliminary Notice ("without delay")
**Awareness Timestamp:** {aware_at_dt.isoformat()}

### 1. Fiduciary Details
- **Business Name:** [BUSINESS_NAME]
- **Authorized Contact:** [CONTACT_PERSON]
- **Contact Details:** [PHONE_OR_EMAIL]
- **Intimation Date:** [DATE_TIME]

### 2. Nature of the Incident
- **Summary:** {scenario_title} - {scenario_desc}
- **Exposure Type(s):** {exposure_str}
- **Affected Systems / Datasets:** {sources_str}

### 3. Extent of Exposure
- **Total Records Compromised:** {records_count}
- **Estimated Individuals:** {confirmed_people} confirmed, {possible_people} possible matches ({confirmed_people + possible_people} total range)
- **Data Categories Involved:** {cats_str}

### 4. Timing
- **Awareness Date & Time:** {aware_at_dt.strftime("%Y-%m-%d %H:%M:%S UTC")}
- **Statutory Standard:** Submitted without delay under Section 8(6) & Rule 7.

### 5. Location
- **Data Storage Location:** {sources_str}

### 6. Likely Impact
- Operational and personal privacy impact under active containment and assessment.

---
*Notice watermark: DRAFT SIMULATION generated by Kavach for fiduciary review prior to dispatch.*
"""


def generate_board_detailed_report(
    scenario_title: str,
    scenario_desc: str,
    exposure_types: List[str],
    affected_sources: List[str],
    records_count: int,
    confirmed_people: int,
    possible_people: int,
    categories: List[str],
    aware_at_dt: datetime.datetime,
    notices_sent_summary: Dict[str, Any],
    device_protected: str = "unknown",
) -> str:
    """
    Generates Stage 2 detailed breach report skeleton for 72-hour filing to the Board.
    Includes items (i) to (vi):
      (i) facts and reasons
      (ii) mitigation
      (iii) findings about cause
      (iv) remedial measures
      (v) attribution / perpetrators (if known)
      (vi) report on intimations sent to individuals auto-filled from notices_sent (counts by channel and date, zero contact values).
    Marked strictly with DRAFT SIMULATION. Zero raw personal data.
    """
    exposure_str = ", ".join(t.capitalize() for t in exposure_types)
    sources_str = ", ".join(affected_sources) if affected_sources else "[AFFECTED_REPOSITORIES]"
    deadline_dt = aware_at_dt + datetime.timedelta(hours=BREACH_STAGE_2_HOURS)

    # Format notices sent summary for item (vi)
    channel_counts = notices_sent_summary.get("counts_by_channel", {})
    total_notices = notices_sent_summary.get("total_sent", 0)
    dates_list = notices_sent_summary.get("dates", [])
    dates_str = ", ".join(dates_list) if dates_list else "[DATE_RANGE]"

    channel_lines = []
    if channel_counts:
        for ch, count in channel_counts.items():
            channel_lines.append(f"  * {ch.capitalize()}: {count} sent")
        channels_summary_str = "\n".join(channel_lines)
    else:
        channels_summary_str = "  * No individual intimations recorded yet in system."

    return f"""# DRAFT SIMULATION - DPDP Act Readiness (May 2027)

## DPDP Rule 7 Detailed Breach Incident Report Skeleton (72-Hour Filing)

**Awareness Timestamp:** {aware_at_dt.isoformat()}
**72-Hour Deadline:** {deadline_dt.isoformat()}

### Item (i) Facts and Reasons
- **Incident Summary:** {scenario_title} - {scenario_desc}
- **Exposure Type(s):** {exposure_str}
- **Affected Datasets / Systems:** {sources_str}
- **Extent:** {records_count} records affected ({confirmed_people} confirmed, {possible_people} possible individuals).
- **Categories:** {', '.join(c.replace('_', ' ').title() for c in categories) or 'None detected'}.

### Item (ii) Mitigation Measures
- Immediate containment initiated upon awareness.
- Affected network access severed; exposed credentials revoked.
- First-hour response checklist executed.

### Item (iii) Findings About Cause
- **Vector:** [PLACEHOLDER: Document root cause analysis, technical vulnerability, or operational lapse].
- **Device Safeguards:** Device protection status verified as '{device_protected}'.

### Item (iv) Remedial Measures
- Remediation steps implemented to eliminate recurrence.
- Technical safeguard enhancements and staff training scheduled.
- Backup integrity verified.

### Item (v) Attribution / Perpetrators (If Known)
- **Actor / Perpetrator:** [PLACEHOLDER: State whether actor is known, internal employee, third party, or undetermined].

### Item (vi) Report on Intimations Sent to Individuals
- **Total Notices Sent:** {total_notices}
- **Dispatch Dates:** {dates_str}
- **Breakdown by Channel:**
{channels_summary_str}
- **Contact Values Note:** Zero raw contact values stored or included in this report (aggregate counts only).

---
*Notice watermark: DRAFT SIMULATION generated by Kavach for fiduciary review prior to dispatch.*
"""


# ---------------------------------------------------------------------------
# Part E: Ordered Checklist
# ---------------------------------------------------------------------------

def get_ordered_checklist(lang: str = "en") -> List[Dict[str, Any]]:
    """
    Returns ordered response checklist across the 6 core stages:
    1. Contain
    2. Preserve Evidence
    3. Assess
    4. Notify
    5. Recover
    6. Review
    Includes 'ask your IT adviser' for generic technical steps, and
    'check other-law reporting duties (to verify)'.
    Contains NO claims of automated detection, tracing, or legal determination.
    """
    stages = [
        ("contain", "Contain the Incident", "Isolate affected machines and disconnect from network. Do not power down unthinkingly (ask your IT adviser). Revoke compromised user credentials, active tokens, and admin sessions."),
        ("preserve_evidence", "Preserve Evidence", "Do not wipe or reformat affected machines. Photograph ransom note or error screen if ransomware. Export and archive system access logs, firewalls, and audit trails. Record exact timestamps of discovery and containment."),
        ("assess", "Assess Blast Radius & Obligations", "Assess blast radius: estimate affected data categories, number of data principals, and minor records involved. Check other-law reporting duties (to verify) (e.g. CERT-In reporting obligations, sectoral guidelines)."),
        ("notify", "Statutory & Principal Notifications", "Submit Stage 1 preliminary intimation to the Data Protection Board of India without delay. Intimate affected data principals without delay with clear protective advice. Prepare Stage 2 detailed report within 72 hours (or submit written extension request)."),
        ("recover", "Business Recovery", "Address core business recovery questions: 1) How long can the business run without the system? 2) How much data can it lose? Restore systems from clean, isolated offline backups (ask your IT adviser)."),
        ("review", "Post-Incident Review", "Conduct thorough post-incident review. Document findings, patch identified vulnerabilities, update access control policies, and provide refresher privacy safeguards training."),
    ]
    items = []
    for step_num, (stg, def_title, def_task) in enumerate(stages, 1):
        loc_title = t(f"checklist.{stg}.title", lang=lang)
        loc_task = t(f"checklist.{stg}.task", lang=lang)
        items.append({
            "step": step_num,
            "stage": stg,
            "title": str(loc_title) if loc_title else def_title,
            "task": str(loc_task) if loc_task else def_task,
            "completed": False,
            "machine_translated": getattr(loc_task, "machine_translated", False),
        })
    return items


# ---------------------------------------------------------------------------
# Part F: Simulation Execution & Summaries
# ---------------------------------------------------------------------------

def get_notices_sent_summary(session: Session, incident_id: Optional[int] = None, incident_ref: Optional[str] = None) -> Dict[str, Any]:
    """
    Summarizes notices sent for an incident without revealing contact values.
    Returns counts by channel, dates, and total sent.
    """
    query = session.query(NoticeSent)
    if incident_id is not None:
        query = query.filter(NoticeSent.incident_id == incident_id)
    elif incident_ref is not None:
        query = query.filter(NoticeSent.incident_ref == incident_ref)

    rows = query.all()
    channel_counts: Dict[str, int] = {}
    dates: Set[str] = set()

    for r in rows:
        channel_counts[r.channel] = channel_counts.get(r.channel, 0) + 1
        if r.sent_at:
            dates.add(r.sent_at.strftime("%Y-%m-%d"))

    return {
        "total_sent": len(rows),
        "counts_by_channel": channel_counts,
        "dates": sorted(list(dates)),
    }


def simulate_breach(
    session: Session,
    scenario: str,
    aware_at: Optional[Union[str, datetime.datetime]] = None,
    sources: Optional[List[str]] = None,
    device_protected: str = "unknown",
    board_extension_requested: bool = False,
    current_time: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """
    Runs end-to-end breach blast-radius simulation.
    Persists to breach_simulations and logs breach_simulated to ledger.
    """
    scenario_def = get_scenario_by_id(scenario)
    if not scenario_def and scenario != "custom":
        raise ValueError(f"Unknown breach scenario: '{scenario}'")

    if scenario == "custom":
        if not sources or not isinstance(sources, list) or len(sources) == 0:
            raise ValueError("Custom scenario requires a non-empty list of source filenames or dataset IDs.")
        affected_sources = list(sources)
        scenario_title = "Custom breach scenario"
        scenario_desc = f"Custom simulation involving {len(affected_sources)} user-specified source files."
        exposure_types = ["confidentiality"]
    else:
        affected_sources = scenario_def.get("affected_sources", []) if not sources else list(sources)
        scenario_title = scenario_def.get("title", scenario)
        scenario_desc = scenario_def.get("description", "")
        exposure_types = scenario_def.get("exposure_types", ["confidentiality"])

    # 1. Blast Radius
    blast = blast_radius(session, affected_sources)

    # 2. Clocks
    if aware_at is None:
        aware_dt = datetime.datetime.now(timezone.utc)
    elif isinstance(aware_at, str):
        aware_dt = datetime.datetime.fromisoformat(aware_at.replace("Z", "+00:00"))
    else:
        aware_dt = aware_at

    clocks = calculate_clocks(
        aware_at=aware_dt,
        board_extension_requested=board_extension_requested,
        current_time=current_time,
    )

    # 3. Severity
    severity_level, total_score, factors = calculate_severity(
        blast_data=blast,
        exposure_types=exposure_types,
        device_protected=device_protected,
    )

    # 4. Draft Notices
    notices_sent_summary = {"total_sent": 0, "counts_by_channel": {}, "dates": []}
    categories_list = list(blast.get("category_breakdown", {}).keys())

    drafts = {
        "individual_notice": generate_individual_notice(
            scenario_title=scenario_title,
            scenario_desc=scenario_desc,
            categories=categories_list,
            aware_at_dt=aware_dt,
        ),
        "board_first_intimation": generate_board_first_intimation(
            scenario_title=scenario_title,
            scenario_desc=scenario_desc,
            exposure_types=exposure_types,
            affected_sources=affected_sources,
            records_count=blast.get("records_count", 0),
            confirmed_people=blast.get("confirmed_people", 0),
            possible_people=blast.get("possible_people", 0),
            categories=categories_list,
            aware_at_dt=aware_dt,
        ),
        "board_detailed_report": generate_board_detailed_report(
            scenario_title=scenario_title,
            scenario_desc=scenario_desc,
            exposure_types=exposure_types,
            affected_sources=affected_sources,
            records_count=blast.get("records_count", 0),
            confirmed_people=blast.get("confirmed_people", 0),
            possible_people=blast.get("possible_people", 0),
            categories=categories_list,
            aware_at_dt=aware_dt,
            notices_sent_summary=notices_sent_summary,
            device_protected=device_protected,
        ),
    }

    # 5. Checklist
    checklist = get_ordered_checklist()

    # 6. Save BreachSimulation record
    counts_payload = {
        "records_count": blast.get("records_count", 0),
        "people_count": blast.get("total_people", 0),
        "confirmed_count": blast.get("confirmed_people", 0),
        "possible_count": blast.get("possible_people", 0),
        "range": blast.get("people_range", "0 - 0"),
        "categories": blast.get("category_breakdown", {}),
        "high_impact_categories": blast.get("high_impact_categories", []),
        "minors_involved": blast.get("minors_involved", 0),
        "affected_sources": affected_sources,
        "only_channel_warnings": blast.get("only_channel_warnings", []),
    }

    sim_record = BreachSimulation(
        scenario=scenario,
        aware_at=aware_dt,
        device_protected=device_protected,
        severity=severity_level,
        counts_json=json.dumps(counts_payload, ensure_ascii=False),
        drafts_json=json.dumps(drafts, ensure_ascii=False),
    )
    session.add(sim_record)
    session.flush()

    # 7. Append Ledger Event (ids, counts, enums only - passes check_payload_guard)
    ledger_payload = {
        "simulation_id": sim_record.id,
        "scenario": scenario,
        "severity": severity_level,
        "confirmed_count": blast.get("confirmed_people", 0),
        "possible_count": blast.get("possible_people", 0),
        "records_count": blast.get("records_count", 0),
    }
    append_event(session, "breach_simulated", ledger_payload)
    session.commit()

    return {
        "id": sim_record.id,
        "scenario": scenario,
        "scenario_title": scenario_title,
        "scenario_description": scenario_desc,
        "exposure_types": exposure_types,
        "affected_sources": affected_sources,
        "aware_at": aware_dt.isoformat(),
        "device_protected": device_protected,
        "severity": severity_level,
        "severity_score": total_score,
        "severity_factors": factors,
        "counts": counts_payload,
        "clocks": clocks,
        "drafts": drafts,
        "checklist": checklist,
        "only_channel_warnings": blast.get("only_channel_warnings", []),
        "disclaimer": "All outputs are marked DRAFT SIMULATION for regulatory readiness under DPDP (May 2027).",
    }
