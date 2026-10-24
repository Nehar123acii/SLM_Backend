import re
from typing import Any, Dict, List
import pandas as pd

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
