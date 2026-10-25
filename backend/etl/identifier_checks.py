import datetime
from datetime import date
import re
from typing import Any, Dict, List, Optional, Union
import pandas as pd

# ---------------------------------------------------------------------------
# Existing Legacy Check Patterns (Preserved for Backward Compatibility)
# ---------------------------------------------------------------------------
PATTERNS = {
    "EMAIL": re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"),
    "PHONE_IN": re.compile(r"^(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9]\d{9}$"),
    "PAN": re.compile(r"^[A-Za-z]{5}\d{4}[A-Za-z]$"),
    "AADHAAR": re.compile(r"^\d{12}$"),
    "PINCODE": re.compile(r"^[1-9]\d{5}$"),
}

CAVEAT_TEXT = (
    "Pattern match only. A regex match does not constitute identity verification "
    "or a legal conclusion about the nature of the data."
)


def run_identifier_checks(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Scans each column against deterministic patterns:
    EMAIL, PHONE_IN, PAN, AADHAAR, PINCODE.

    Returns findings only when match_count >= 3 AND match_rate >= 0.5.
    Always attaches disclaimer caveat.
    """
    findings: List[Dict[str, Any]] = []

    for col in df.columns:
        series = df[col].dropna().astype(str).str.strip()
        total_non_null = len(series)
        if total_non_null < 3:
            continue

        for p_name, regex in PATTERNS.items():
            if p_name == "AADHAAR":
                # Support 12 digits with spaces or hyphens stripped
                match_count = sum(
                    bool(regex.match(re.sub(r"[\s\-]", "", v))) for v in series
                )
            elif p_name == "PHONE_IN":
                match_count = sum(
                    bool(regex.match(re.sub(r"[\s\-]", "", v))) for v in series
                )
            else:
                match_count = sum(bool(regex.match(v)) for v in series)

            match_rate = match_count / total_non_null
            if match_count >= 3 and match_rate >= 0.5:
                findings.append({
                    "column_name": col,
                    "pattern_type": p_name,
                    "match_count": int(match_count),
                    "caveat": CAVEAT_TEXT,
                })

    return findings


# ---------------------------------------------------------------------------
# Verhoeff Algorithm for Aadhaar Checksum Validation
# ---------------------------------------------------------------------------
_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]

_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_validate(num_str: str) -> bool:
    """Validate a number string using the Verhoeff checksum algorithm."""
    if not num_str or not num_str.isdigit():
        return False
    c = 0
    for i, ch in enumerate(reversed(num_str)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


# ---------------------------------------------------------------------------
# Constants & Header Sets
# ---------------------------------------------------------------------------
_BANK_HEADERS = {
    "bank_account", "bank account", "account_no", "account no",
    "account_number", "account number", "bank_acc", "acc_no"
}

_DOB_HEADERS = {
    "dob", "date_of_birth", "date of birth", "birthday", "birth_date", "birth date"
}

_NAME_HEADERS = {
    "name", "patient_name", "patient name", "staff_name", "staff name",
    "full_name", "full name", "sender", "customer_name", "customer name",
    "applicant", "applicant_name", "applicant name", "candidate", "candidate_name",
}

HEALTH_TERMS = sorted([
    "diabetes", "hiv positive", "hiv negative", "hiv", "thyroid disorder", "thyroid",
    "pregnancy test", "pregnancy", "hepatitis b", "hepatitis", "hypertension",
    "cancer screening", "cancer", "blood sugar high", "blood sugar",
], key=len, reverse=True)

_TITLE_NAME_RE = re.compile(
    r"\b(Dr\.|Mr\.|Mrs\.|Ms\.|Shri|Smt\.|Prof\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"
)

_INTRO_NAME_RE = re.compile(
    r"(?:\b(?:this is|i am|i'm|my name is|patient name\s*[:\-]?|mera naam)\s+)([A-Za-z]+(?:\s+[A-Za-z]+){1,3})\b",
    re.IGNORECASE,
)

_NAME_STOPWORDS = {
    "and", "my", "who", "with", "for", "hai", "tha", "a", "an", "the", "is",
    "has", "had", "have", "was", "were",
    "number", "phone", "email", "contact", "from", "here", "please",
    "call", "send", "submitted", "confirmed", "today", "tomorrow",
    "dr", "mr", "mrs", "ms",
}

_GSTIN_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9])([0-9]{2}[A-Za-z0-9]{13})(?![A-Za-z0-9])"
)

_GSTIN_STRUCTURE_RE = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[A-Z0-9]$",
    re.IGNORECASE
)

_IFSC_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{4}\d[A-Za-z0-9]{6})(?![A-Za-z0-9])"
)

_UPI_RE = re.compile(
    r"(?<![a-zA-Z0-9_.+-])([a-zA-Z0-9_.+-]+@(okaxis|oksbi|okhdfc|okicici|ybl|paytm|ibl|upi|apl|freecharge|[a-zA-Z0-9_-]{2,}))(?![a-zA-Z0-9_.+-])",
    re.IGNORECASE
)
_EMAIL_TLD_RE = re.compile(r"\.(com|in|org|net|edu|gov|io|co|ai|info|biz|me)$", re.IGNORECASE)

_DOB_RE = re.compile(
    r"(?<!\d)"
    r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{2})"
    r"(?!\d)"
)


def _get_header(args: tuple, kwargs: dict) -> Optional[str]:
    header = kwargs.get("header")
    if header:
        return str(header)
    meta = kwargs.get("meta")
    if isinstance(meta, dict) and meta.get("header"):
        return str(meta["header"])
    if len(args) >= 3 and isinstance(args[2], dict) and args[2].get("header"):
        return str(args[2]["header"])
    return None


# ---------------------------------------------------------------------------
# Individual Deterministic Detectors
# Return CONTRACT:
# Returns list of dicts with ONLY:
# - category: str
# - start: int
# - end: int
# - validated: bool
# For dob only:
# - is_minor: bool
# NEVER returns the matched value or text slice.
# ---------------------------------------------------------------------------

def detect_aadhaar(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """
    Detect Aadhaar numbers. Validates using Verhoeff checksum.
    Returns category, start, end, and validated (True/False).
    Never returns the matched number.
    """
    header = _get_header(args, kwargs)
    if header and header.lower() in {
        "phone", "mobile", "contact", "phone_number", "mobile_number",
        "contact_number", "phone number", "mobile number"
    }:
        return []

    findings = []
    # Match candidate 12-digit patterns
    for m in re.finditer(r"(?<!\d)(\d{4})[\s\-\.]?(\d{4})[\s\-\.]?(\d{4})(?!\d)", text):
        start = m.start()
        prefix = text[max(0, start - 4):start].strip()
        if prefix.endswith("+91") or prefix.endswith("+") or prefix.endswith("91"):
            continue
        stripped = re.sub(r"[\s\-+.]", "", text)
        if re.match(r"^(91|0)?[6-9]\d{9}$", stripped):
            continue

        digits = m.group(1) + m.group(2) + m.group(3)
        # Indian Aadhaar numbers never start with 0 or 1
        if digits[0] in "01":
            is_valid = False
        else:
            is_valid = verhoeff_validate(digits)

        findings.append({
            "category": "aadhaar",
            "start": m.start(),
            "end": m.end(),
            "validated": is_valid,
        })
    return findings


def validate_gstin(code: str) -> bool:
    """Validate 15-character GSTIN structure."""
    code = code.strip().upper()
    if len(code) != 15:
        return False
    state_str = code[:2]
    if not state_str.isdigit():
        return False
    state = int(state_str)
    if not ((1 <= state <= 37) or state in (97, 99)):
        return False
    return bool(_GSTIN_STRUCTURE_RE.match(code))


def detect_gstin(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """
    Detect Indian GSTIN identifiers.
    Returns category, start, end, validated.
    """
    findings = []
    for m in _GSTIN_CANDIDATE_RE.finditer(text):
        val = m.group(1)
        is_valid = validate_gstin(val)
        findings.append({
            "category": "gstin",
            "start": m.start(),
            "end": m.end(),
            "validated": is_valid,
        })
    return findings


def validate_ifsc(code: str) -> bool:
    """Validate Indian Financial System Code (IFSC) structure."""
    code = code.strip().upper()
    if len(code) != 11:
        return False
    return bool(re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", code))


def detect_ifsc(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """
    Detect Indian IFSC codes.
    Returns category, start, end, validated.
    """
    findings = []
    # Avoid overlapping matches with GSTIN
    gstin_spans = [(m.start(), m.end()) for m in _GSTIN_CANDIDATE_RE.finditer(text)]

    for m in _IFSC_CANDIDATE_RE.finditer(text):
        start, end = m.start(), m.end()
        if any(g_s <= start and end <= g_e for g_s, g_e in gstin_spans):
            continue
        val = m.group(1)
        is_valid = validate_ifsc(val)
        findings.append({
            "category": "ifsc",
            "start": start,
            "end": end,
            "validated": is_valid,
        })
    return findings


def validate_upi(handle: str) -> bool:
    """Validate UPI Virtual Payment Address handle."""
    handle = handle.strip()
    if "@" not in handle:
        return False
    parts = handle.split("@")
    if len(parts) != 2:
        return False
    user, domain = parts[0], parts[1]
    if not user or not domain:
        return False
    # If domain looks like an email TLD (e.g. gmail.com, company.in), not UPI
    if _EMAIL_TLD_RE.search(domain):
        return False
    known_providers = {
        "okaxis", "oksbi", "okhdfc", "okicici", "ybl", "paytm",
        "ibl", "upi", "apl", "freecharge", "axl"
    }
    if domain.lower() in known_providers or re.match(r"^[a-zA-Z0-9_-]{2,}$", domain):
        return True
    return False


def detect_upi(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """
    Detect UPI ID / Virtual Payment Address.
    Returns category, start, end, validated.
    """
    findings = []
    for m in _UPI_RE.finditer(text):
        val = m.group(1)
        if validate_upi(val):
            findings.append({
                "category": "upi",
                "start": m.start(),
                "end": m.end(),
                "validated": True,
            })
    return findings


def parse_dob(dob_str: str) -> Optional[datetime.date]:
    """Parse date of birth string across standard formats."""
    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d",
        "%d-%m-%Y", "%d/%m/%Y",
        "%m/%d/%Y", "%m-%d-%Y",
        "%d/%m/%y", "%d-%m-%y",
    ):
        try:
            return datetime.datetime.strptime(dob_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def compute_is_minor(
    bdate: datetime.date,
    reference_date: Optional[Union[datetime.date, datetime.datetime, str]] = None,
) -> bool:
    """Check under-18 relative to a fixed reference date (defaults to today)."""
    if isinstance(reference_date, str):
        ref_d = datetime.datetime.strptime(reference_date, "%Y-%m-%d").date()
    elif isinstance(reference_date, datetime.datetime):
        ref_d = reference_date.date()
    elif isinstance(reference_date, datetime.date):
        ref_d = reference_date
    else:
        ref_d = datetime.date.today()

    age = (
        ref_d.year
        - bdate.year
        - ((ref_d.month, ref_d.day) < (bdate.month, bdate.day))
    )
    return age < 18


def detect_dob(
    text: str,
    reference_date: Optional[Union[datetime.date, datetime.datetime, str]] = None,
    *args,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Detect Date of Birth (DOB).
    Computes is_minor relative to reference_date.
    NEVER stores or returns the raw date value.
    """
    if reference_date is None:
        reference_date = kwargs.get("reference_date")
    meta = kwargs.get("meta") or (args[2] if len(args) >= 3 and isinstance(args[2], dict) else {})
    if reference_date is None and isinstance(meta, dict):
        reference_date = meta.get("reference_date")

    findings = []
    for m in _DOB_RE.finditer(text):
        val = m.group(1)
        bdate = parse_dob(val)
        if bdate:
            is_minor = compute_is_minor(bdate, reference_date)
            findings.append({
                "category": "dob",
                "start": m.start(),
                "end": m.end(),
                "validated": True,
                "is_minor": is_minor,
            })
        else:
            findings.append({
                "category": "dob",
                "start": m.start(),
                "end": m.end(),
                "validated": False,
                "is_minor": False,
            })
    return findings


def detect_bank_account(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """
    Detect Bank Account numbers using 9-18 digit length rule.
    Returns category, start, end, validated.
    """
    findings = []
    for m in re.finditer(r"(?<!\d)(\d{4,24})(?!\d)", text):
        digits = m.group(1)
        if 9 <= len(digits) <= 18:
            findings.append({
                "category": "bank_account",
                "start": m.start(),
                "end": m.end(),
                "validated": True,
            })
        else:
            findings.append({
                "category": "bank_account",
                "start": m.start(),
                "end": m.end(),
                "validated": False,
            })
    return findings


def detect_health(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """
    Detect health terms with negation guard.
    Returns category, start, end, validated.
    """
    findings = []
    text_lower = text.lower()
    matched_spans = []
    for term in HEALTH_TERMS:
        pattern = r"\b" + re.escape(term) + r"\b"
        for m in re.finditer(pattern, text_lower):
            start_idx, end_idx = m.start(), m.end()
            # If this span overlaps with a longer phrase already matched, skip
            if any(s <= start_idx and end_idx <= e for s, e in matched_spans):
                continue
            prefix = text_lower[:start_idx].strip()
            # Negation guard: skip if negated
            if re.search(r"\b(?:no|not|without|denies|negative for)\s*$", prefix):
                continue
            matched_spans.append((start_idx, end_idx))
            findings.append({
                "category": "health",
                "start": start_idx,
                "end": end_idx,
                "validated": True,
            })
    return findings

# Alias for compatibility with reference implementation
detect_health_term = detect_health


def detect_name(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """
    Detect names via title prefixes (Dr., Mr., etc.) or intro phrases.
    Returns category, start, end, validated.
    """
    findings = []
    header = _get_header(args, kwargs)
    if header and header.lower() in _NAME_HEADERS:
        if text and not text.replace(" ", "").isdigit():
            findings.append({
                "category": "name",
                "start": 0,
                "end": len(text),
                "validated": True,
            })
            return findings

    for m in _TITLE_NAME_RE.finditer(text):
        findings.append({
            "category": "name",
            "start": m.start(),
            "end": m.end(),
            "validated": True,
        })

    for m in _INTRO_NAME_RE.finditer(text):
        raw_tail = m.group(1).strip()
        tail_clean = re.split(r"[,;!?\n\r]", raw_tail)[0].strip()
        words = tail_clean.split()
        cand_words = []
        for w in words:
            w_clean = w.strip(".").lower()
            if w_clean in _NAME_STOPWORDS or not w_clean.isalpha():
                break
            cand_words.append(w.strip("."))
            if len(cand_words) == 3:
                break
        if cand_words:
            matched_name = " ".join(cand_words)
            idx = text.find(matched_name, m.start())
            if idx != -1:
                start, end = idx, idx + len(matched_name)
                if not any(f["start"] <= start and end <= f["end"] for f in findings):
                    findings.append({
                        "category": "name",
                        "start": start,
                        "end": end,
                        "validated": True,
                    })
    return findings


def detect_phone(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """Detect Indian mobile phone numbers."""
    header = _get_header(args, kwargs)
    if header and header.lower() in _BANK_HEADERS:
        return []
    findings = []
    for m in re.finditer(r"(?<!\d)(?:(?:\+91|0091|91|0)[\s\-\.]?)?([6-9]\d{9})(?!\d)", text):
        findings.append({
            "category": "phone",
            "start": m.start(),
            "end": m.end(),
            "validated": True,
        })
    return findings


def detect_email(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """Detect email addresses."""
    findings = []
    for m in re.finditer(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text):
        findings.append({
            "category": "email",
            "start": m.start(),
            "end": m.end(),
            "validated": True,
        })
    return findings


def detect_pan(text: str, *args, **kwargs) -> List[Dict[str, Any]]:
    """Detect Indian PAN identifiers."""
    findings = []
    for m in re.finditer(r"(?<![A-Za-z0-9])([A-Za-z]{5}\d{4}[A-Za-z])(?![A-Za-z0-9])", text):
        start = m.start()
        if start >= 2 and text[start - 2:start].isdigit():
            continue
        findings.append({
            "category": "pan",
            "start": m.start(),
            "end": m.end(),
            "validated": True,
        })
    return findings


ALL_DETECTORS = [
    detect_phone,
    detect_email,
    detect_aadhaar,
    detect_pan,
    detect_gstin,
    detect_ifsc,
    detect_upi,
    detect_dob,
    detect_bank_account,
    detect_health,
    detect_name,
]


def detect_all(
    text: str,
    reference_date: Optional[Union[datetime.date, datetime.datetime, str]] = None,
    *args,
    **kwargs
) -> List[Dict[str, Any]]:
    """Runs all detectors on input text and returns findings."""
    all_findings = []
    for detector in ALL_DETECTORS:
        if detector == detect_dob:
            all_findings.extend(detector(text, reference_date=reference_date, *args, **kwargs))
        else:
            all_findings.extend(detector(text, *args, **kwargs))
    return all_findings

