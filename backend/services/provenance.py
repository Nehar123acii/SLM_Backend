"""
backend/services/provenance.py
==============================
Data provenance and entity resolution engine for Kavach.

Functions:
- classify_column_category: maps schema to (phone, email, aadhaar, pan, name, dob, address, health, other)
- compute_impact_tier: assigns Kavach impact tier (1-3)
- compute_locator: formats provenance locator string (file|sheet|column or file|image_bbox)
- resolve_entities_and_record_occurrences: runs entity resolution and writes occurrences and people rows
- rows_for_field: retrieves masked occurrences for a column
- people_for_dataset: retrieves resolved people for a dataset
- sources_for_person: retrieves all source dataset locations for an individual
"""

import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import pandas as pd
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.engine import SessionLocal
from backend.db.models import Column, Dataset, Occurrence, Person
from backend.security import normalise, mask, hmac_value


# ---------------------------------------------------------------------------
# Category & Impact Tier Classification
# ---------------------------------------------------------------------------

IDENTIFIER_CATEGORIES = {
    "phone", "email", "aadhaar", "pan", "name",
    "bank_account", "gstin", "ifsc", "upi"
}

STRONG_CATEGORIES = {"phone", "email", "aadhaar"}

DEFAULT_OCR_STRONG_THRESHOLD = 0.8


def classify_column_category(
    col_name: str,
    inferred_type: str = "",
    flags: Optional[List[str]] = None,
    ai_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Categorizes column into one of:
    phone, email, aadhaar, pan, name, dob, address, health,
    bank_account, gstin, ifsc, upi, other
    """
    c_lower = col_name.lower().replace("-", "_").strip()
    flags = flags or []
    ai_data = ai_data or {}
    ai_cat = (ai_data.get("category") or "").upper()

    # 1. Phone
    if (
        inferred_type == "PHONE"
        or "PHONE_IN" in flags
        or any(k in c_lower for k in ["phone", "mobile", "contact_no", "contact_number", "telephone"])
    ):
        return "phone"

    # 2. Email
    if (
        inferred_type == "EMAIL"
        or "EMAIL" in flags
        or any(k in c_lower for k in ["email", "e_mail", "mail_id", "email_id"])
    ):
        return "email"

    # 3. Aadhaar
    if (
        "AADHAAR" in flags
        or any(k in c_lower for k in ["aadhaar", "aadhar", "uidai", "uid"])
    ):
        return "aadhaar"

    # 4. PAN
    if (
        "PAN" in flags
        or c_lower == "pan"
        or c_lower.startswith("pan_")
        or c_lower.endswith("_pan")
    ):
        return "pan"

    # 5. Name
    if (
        any(k in c_lower for k in ["patient_name", "customer_name", "doctor_name", "full_name", "first_name", "last_name", "staff_name", "employee_name"])
        or c_lower == "name"
        or c_lower == "sender"
        or ai_cat == "IDENTITY"
    ):
        return "name"

    # 6. DOB
    if (
        any(k in c_lower for k in ["dob", "date_of_birth", "birth_date", "birthdate"])
    ):
        return "dob"

    # 7. Address
    if (
        "PINCODE" in flags
        or any(k in c_lower for k in ["address", "pincode", "postal_code", "zip", "city", "state", "street", "residence"])
    ):
        return "address"

    # 8. Health
    if (
        ai_cat == "HEALTH"
        or any(k in c_lower for k in ["health", "diagnosis", "medical", "symptom", "disease", "prescription", "treatment", "test_name", "notes", "reason"])
    ):
        return "health"

    # 9. Bank Account
    if (
        "BANK_ACCOUNT" in flags
        or any(k in c_lower for k in ["bank_account", "account_no", "account_number", "bank_acc", "acc_no"])
    ):
        return "bank_account"

    # 10. GSTIN
    if (
        "GSTIN" in flags
        or "gstin" in c_lower
        or (c_lower.startswith("gst") and "no" in c_lower)
    ):
        return "gstin"

    # 11. IFSC
    if (
        "IFSC" in flags
        or "ifsc" in c_lower
    ):
        return "ifsc"

    # 12. UPI
    if (
        "UPI" in flags
        or "upi" in c_lower
        or "vpa" in c_lower
    ):
        return "upi"

    return "other"


def compute_impact_tier(category: str) -> str:
    """
    Kavach's own 'impact if leaked' tier (1-3):
    Tier 3: aadhaar, pan, health, bank_account
    Tier 2: phone, email, name, dob, address, gstin, ifsc, upi
    Tier 1: other
    """
    if category in ["aadhaar", "pan", "health", "bank_account"]:
        return "3"
    elif category in ["phone", "email", "name", "dob", "address", "gstin", "ifsc", "upi"]:
        return "2"
    else:
        return "1"


def compute_locator(
    filename: str,
    sheet_name: Optional[str],
    col_name: str,
    source_type: str = "",
    source_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Constructs provenance locator:
    - Standard tabular/sheets: file|sheet|column
    - OCR documents: file|image_bbox
    """
    base_file = os.path.basename(filename)
    if source_type == "document_ocr":
        return f"{base_file}|image_bbox"
    sheet_part = sheet_name or ""
    return f"{base_file}|{sheet_part}|{col_name}"


# ---------------------------------------------------------------------------
# Union-Find for Entity Resolution
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self):
        self.parent: Dict[int, int] = {}

    def find(self, item: int) -> int:
        if item not in self.parent:
            self.parent[item] = item
            return item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, item1: int, item2: int) -> int:
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 != root2:
            self.parent[root2] = root1
            return root1
        return root1


# ---------------------------------------------------------------------------
# Occurrence Extraction & Entity Resolution Pipeline
# ---------------------------------------------------------------------------

# Patterns for extracting identifiers from free text or OCR lines
RE_PHONE = re.compile(r"(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9](?:[\-\s]?\d){9}")
RE_EMAIL = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
RE_AADHAAR = re.compile(r"\b\d{4}[\s-]\d{4}[\s-]\d{4}\b|\b\d{12}\b")
RE_PAN = re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")


def resolve_entities_and_record_occurrences(
    db: Session,
    dataset_id: str,
    cleaned_df: pd.DataFrame,
    col_objs: Dict[str, Column],
    source_type: str = "csv",
    ocr_threshold: float = DEFAULT_OCR_STRONG_THRESHOLD,
) -> None:
    """
    Identifies identifier occurrences in cleaned_df, resolves entities across records,
    and writes people and occurrences rows into SQLite.
    Never persists raw values — only masked_sample and value_hmac.
    """
    is_ocr = (source_type == "document_ocr")
    origin = "ocr" if is_ocr else "rule"

    # Pre-index existing strong occurrences from DB: (category, value_hmac) -> person_id
    existing_strong_occs = (
        db.query(Occurrence.value_hmac, Occurrence.person_id)
        .join(Column, Occurrence.column_id == Column.id)
        .filter(
            Column.category.in_(list(STRONG_CATEGORIES)),
            Occurrence.person_id.isnot(None),
            # OCR occurrences only count as strong if ocr_conf >= threshold
            (Occurrence.origin != "ocr") | (Occurrence.ocr_conf >= ocr_threshold),
        )
        .all()
    )
    hmac_to_person: Dict[str, int] = {}
    for hmac_val, pid in existing_strong_occs:
        if hmac_val and pid:
            hmac_to_person[hmac_val] = pid

    uf = UnionFind()
    for pid in hmac_to_person.values():
        uf.find(pid)

    # Temporary row-level data structure before persisting
    row_occurrences_batch = []

    # Identify which columns are identifier columns
    id_cols = [c for c in cleaned_df.columns if c in col_objs and col_objs[c].category in IDENTIFIER_CATEGORIES]

    for idx in range(len(cleaned_df)):
        line_num = cleaned_df.at[idx, "line_number"] if "line_number" in cleaned_df.columns else None
        if is_ocr and "bbox_locator" in cleaned_df.columns and pd.notna(cleaned_df.at[idx, "bbox_locator"]):
            row_ref = str(cleaned_df.at[idx, "bbox_locator"])
        else:
            row_ref = str(line_num) if line_num is not None else str(idx)

        # Confidence for OCR rows
        ocr_conf = None
        if is_ocr and "confidence" in cleaned_df.columns:
            try:
                ocr_conf = float(cleaned_df.at[idx, "confidence"])
            except (ValueError, TypeError):
                ocr_conf = 1.0

        row_strong_hmacs: Set[str] = set()
        row_occs = []

        # 1. Check structured identifier columns
        for cname in id_cols:
            col_obj = col_objs[cname]
            category = col_obj.category
            raw_val = cleaned_df.at[idx, cname]
            if raw_val is None or pd.isna(raw_val):
                continue
            str_val = str(raw_val).strip()
            if not str_val:
                continue
            # Skip system notices in WhatsApp sender column
            if category == "name" and str_val.upper() in ["SYSTEM", "MESSAGES AND CALLS"]:
                continue

            v_norm = normalise(category, str_val)
            if not v_norm:
                continue

            v_hmac = hmac_value(category, str_val)
            v_masked = mask(category, str_val)

            # Determine if this occurrence qualifies as a strong match link
            is_strong = (category in STRONG_CATEGORIES) and (not is_ocr or (ocr_conf is not None and ocr_conf >= ocr_threshold))
            if is_strong:
                row_strong_hmacs.add(v_hmac)

            row_occs.append({
                "column_id": col_obj.id,
                "category": category,
                "row_ref": row_ref,
                "masked_sample": v_masked,
                "value_hmac": v_hmac,
                "origin": origin,
                "ocr_conf": ocr_conf,
            })

        # 2. For free-text columns in OCR or chat, extract inline identifier occurrences
        free_text_cols = [
            c for c in cleaned_df.columns
            if c in col_objs and col_objs[c].category in ["health", "other"]
            and c in ["text_content", "message_text"]
        ]
        for cname in free_text_cols:
            col_obj = col_objs[cname]
            raw_body = cleaned_df.at[idx, cname]
            if not raw_body or pd.isna(raw_body):
                continue
            body_str = str(raw_body)

            # Inline Aadhaar
            for match in RE_AADHAAR.finditer(body_str):
                matched_val = match.group(0)
                v_hmac = hmac_value("aadhaar", matched_val)
                v_masked = mask("aadhaar", matched_val)
                if not is_ocr or (ocr_conf is not None and ocr_conf >= ocr_threshold):
                    row_strong_hmacs.add(v_hmac)
                row_occs.append({
                    "column_id": col_obj.id,
                    "category": "aadhaar",
                    "row_ref": row_ref,
                    "masked_sample": v_masked,
                    "value_hmac": v_hmac,
                    "origin": origin,
                    "ocr_conf": ocr_conf,
                })

            # Inline Phone
            for match in RE_PHONE.finditer(body_str):
                matched_val = match.group(0)
                v_hmac = hmac_value("phone", matched_val)
                v_masked = mask("phone", matched_val)
                if not is_ocr or (ocr_conf is not None and ocr_conf >= ocr_threshold):
                    row_strong_hmacs.add(v_hmac)
                row_occs.append({
                    "column_id": col_obj.id,
                    "category": "phone",
                    "row_ref": row_ref,
                    "masked_sample": v_masked,
                    "value_hmac": v_hmac,
                    "origin": origin,
                    "ocr_conf": ocr_conf,
                })

            # Inline Email
            for match in RE_EMAIL.finditer(body_str):
                matched_val = match.group(0)
                v_hmac = hmac_value("email", matched_val)
                v_masked = mask("email", matched_val)
                if not is_ocr or (ocr_conf is not None and ocr_conf >= ocr_threshold):
                    row_strong_hmacs.add(v_hmac)
                row_occs.append({
                    "column_id": col_obj.id,
                    "category": "email",
                    "row_ref": row_ref,
                    "masked_sample": v_masked,
                    "value_hmac": v_hmac,
                    "origin": origin,
                    "ocr_conf": ocr_conf,
                })

        if not row_occs:
            continue

        # -------------------------------------------------------------
        # Entity Resolution Decision for this Row
        # -------------------------------------------------------------
        # Check if any strong identifier matches existing persons
        matched_person_ids = set()
        for h in row_strong_hmacs:
            if h in hmac_to_person:
                matched_person_ids.add(uf.find(hmac_to_person[h]))

        assigned_person_id: Optional[int] = None

        if matched_person_ids:
            # Merge all matched persons into one using Union-Find
            sorted_pids = sorted(matched_person_ids)
            primary_pid = sorted_pids[0]
            for other_pid in sorted_pids[1:]:
                uf.union(primary_pid, other_pid)
            assigned_person_id = uf.find(primary_pid)

            # Ensure resolution is strong and confidence is 1.0
            person_obj = db.get(Person, assigned_person_id)
            if person_obj:
                person_obj.resolution = "strong"
                person_obj.confidence = 1.0
        else:
            # No existing match. Check if this row has strong identifiers
            if row_strong_hmacs:
                new_person = Person(resolution="strong", confidence=1.0)
            else:
                # Name-only or weak match -> probable, never merged
                new_person = Person(resolution="probable", confidence=0.6)

            db.add(new_person)
            db.flush()
            assigned_person_id = new_person.id
            uf.find(assigned_person_id)

        # Register all strong HMACs in this row with the assigned person
        if row_strong_hmacs:
            for h in row_strong_hmacs:
                hmac_to_person[h] = assigned_person_id

        # Attach occurrences to batch
        for occ_data in row_occs:
            occ_data["person_id"] = assigned_person_id
            row_occurrences_batch.append(occ_data)

    # If any persons were merged in the Union-Find, reconcile them in SQLite
    # 1. Update batch occurrences
    for occ_dict in row_occurrences_batch:
        if occ_dict["person_id"]:
            occ_dict["person_id"] = uf.find(occ_dict["person_id"])

    # 2. Persist new occurrences
    for occ_dict in row_occurrences_batch:
        occ = Occurrence(
            person_id=occ_dict["person_id"],
            column_id=occ_dict["column_id"],
            row_ref=occ_dict["row_ref"],
            masked_sample=occ_dict["masked_sample"],
            value_hmac=occ_dict["value_hmac"],
            origin=occ_dict["origin"],
            ocr_conf=occ_dict["ocr_conf"],
        )
        db.add(occ)

    db.flush()

    # 3. Update any older occurrences in SQLite if their person was merged into a canonical root
    for pid in list(uf.parent.keys()):
        root_pid = uf.find(pid)
        if root_pid != pid:
            db.query(Occurrence).filter(Occurrence.person_id == pid).update(
                {"person_id": root_pid}, synchronize_session=False
            )
            # Remove redundant merged Person entity
            merged_person = db.get(Person, pid)
            if merged_person:
                db.delete(merged_person)

    db.flush()


# ---------------------------------------------------------------------------
# Helpers for Part C
# ---------------------------------------------------------------------------

def rows_for_field(
    column_id: Any,
    db: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    """
    Returns masked occurrences only for the given column.
    Never returns raw personal data.
    """
    if isinstance(column_id, Session):
        db, column_id = column_id, db

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        col_id_int = int(column_id)
        occs = (
            db.query(Occurrence)
            .filter(Occurrence.column_id == col_id_int)
            .order_by(Occurrence.id.asc())
            .all()
        )
        results = []
        for o in occs:
            results.append({
                "id": o.id,
                "person_id": o.person_id,
                "column_id": o.column_id,
                "row_ref": o.row_ref,
                "masked_sample": o.masked_sample,
                "value_hmac": o.value_hmac,
                "origin": o.origin,
                "ocr_conf": o.ocr_conf,
            })
        return results
    finally:
        if close_db:
            db.close()


def people_for_dataset(
    dataset_id: Any,
    db: Optional[Session] = None,
) -> List[Person]:
    """
    Returns all resolved/probable people entities associated with a dataset.
    """
    if isinstance(dataset_id, Session):
        db, dataset_id = dataset_id, db

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        ds_id_str = str(dataset_id)
        people = (
            db.query(Person)
            .join(Occurrence, Occurrence.person_id == Person.id)
            .join(Column, Occurrence.column_id == Column.id)
            .filter(Column.dataset_id == ds_id_str)
            .distinct()
            .all()
        )
        return people
    finally:
        if close_db:
            db.close()


def sources_for_person(
    person_id: Any,
    db: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    """
    Returns all source datasets and column locations where a person occurs.
    """
    if isinstance(person_id, Session):
        db, person_id = person_id, db

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        pid_int = int(person_id)
        rows = (
            db.query(Occurrence, Column, Dataset)
            .join(Column, Occurrence.column_id == Column.id)
            .join(Dataset, Column.dataset_id == Dataset.dataset_id)
            .filter(Occurrence.person_id == pid_int)
            .all()
        )
        results = []
        for occ, col, ds in rows:
            results.append({
                "dataset_id": ds.dataset_id,
                "original_filename": ds.original_filename,
                "source_type": ds.source_type,
                "sheet_name": ds.sheet_name,
                "column_name": col.column_name,
                "locator": col.locator,
                "category": col.category,
                "row_ref": occ.row_ref,
                "masked_sample": occ.masked_sample,
                "origin": occ.origin,
            })
        return results
    finally:
        if close_db:
            db.close()
