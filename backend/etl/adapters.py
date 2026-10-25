"""
backend/etl/adapters.py
=======================
Source-specific ingestion adapters for:
- CSV
- Excel (XLSX / XLS) with multi-sheet support
- Google Forms response exports (CSV / XLSX)
- WhatsApp exported chat text (.txt)
- JSON exports (arrays and nested objects with dotted-path preservation)

Safety constraints:
- Never log raw personal data or unredacted chat messages.
- Never silently drop records, sheets, or parsing errors.
- Preserve source lineage (original field names, sheets, line numbers).
- Preserve identifiers as text (leading zeros).
"""

import csv
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd


# ---------------------------------------------------------------------------
# Supported Source Definitions
# ---------------------------------------------------------------------------
SUPPORTED_SOURCES = [
    {
        "source_type": "csv",
        "label": "Comma-Separated Values (CSV)",
        "file_extensions": [".csv"],
        "description": "Tabular CSV files with UTF-8/BOM and Latin-1 fallback support.",
        "options": ["delimiter", "encoding"],
    },
    {
        "source_type": "excel",
        "label": "Microsoft Excel (XLSX / XLS)",
        "file_extensions": [".xlsx", ".xls"],
        "description": "Excel workbooks supporting single or multi-sheet ingestion.",
        "options": ["sheet_name"],
    },
    {
        "source_type": "google_forms",
        "label": "Google Forms Response Export",
        "file_extensions": [".csv", ".xlsx"],
        "description": "Exported responses from Google Forms. Preserves full question titles and submission timestamps.",
        "options": [],
    },
    {
        "source_type": "whatsapp",
        "label": "WhatsApp Exported Chat Text",
        "file_extensions": [".txt"],
        "description": "WhatsApp chat export (.txt) with support for multiline messages, timestamps, attachment markers, and system notices.",
        "options": [],
    },
    {
        "source_type": "json",
        "label": "JSON Document Export",
        "file_extensions": [".json"],
        "description": "JSON array of objects or nested JSON objects with dotted path preservation (e.g. kyc.pan).",
        "options": [],
    },
    {
        "source_type": "document_ocr",
        "label": "Scanned Document and Image OCR",
        "file_extensions": [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"],
        "description": "PDF files (selectable text or scanned) and image files (PNG, JPG, TIFF) with two-stage native text extraction and local Tesseract OCR.",
        "options": ["language"],
    },
]


def normalize_column_name(col: Any, idx: int, seen: Dict[str, int]) -> Tuple[str, Optional[str]]:
    """
    Normalizes a column name safely:
    - Strips whitespace and BOM
    - Converts to lowercase
    - Replaces spaces and hyphens with underscores
    - Handles empty/unnamed columns
    - Detects collisions and disambiguates with suffix, returning a collision warning if applicable.
    """
    col_str = str(col).strip().lstrip("\ufeff")
    normalized = col_str.lower().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"[^\w_]", "", normalized)
    if not normalized:
        normalized = f"col_{idx}"

    warning: Optional[str] = None
    if normalized in seen:
        seen[normalized] += 1
        disambiguated = f"{normalized}_{seen[normalized]}"
        warning = f"Column normalization collision: '{col_str}' normalized to already existing '{normalized}'. Disambiguated as '{disambiguated}'."
        return disambiguated, warning
    else:
        seen[normalized] = 0
        return normalized, None


# ---------------------------------------------------------------------------
# 1. CSV Adapter
# ---------------------------------------------------------------------------
def read_csv_adapter(
    file_path: str,
    max_rows: int = 50000,
    max_cols: int = 200,
) -> Tuple[pd.DataFrame, List[str], Dict[str, str]]:
    """
    Ingests CSV file.
    Returns: (df, warnings, original_to_normalized_mapping)
    """
    warnings: List[str] = []
    try:
        df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str)
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding="latin-1", dtype=str)
        warnings.append("CSV was not UTF-8 encoded; fell back to latin-1 encoding.")

    if len(df) > max_rows:
        raise ValueError(f"CSV row count ({len(df)}) exceeds limit of {max_rows} rows.")
    if len(df.columns) > max_cols:
        raise ValueError(f"CSV column count ({len(df.columns)}) exceeds limit of {max_cols} columns.")

    mapping: Dict[str, str] = {}
    new_cols: List[str] = []
    seen: Dict[str, int] = {}

    for idx, col in enumerate(df.columns):
        orig = str(col).strip()
        norm, warn = normalize_column_name(col, idx, seen)
        if warn:
            warnings.append(warn)
        new_cols.append(norm)
        mapping[norm] = orig

    df.columns = new_cols
    return df, warnings, mapping


# ---------------------------------------------------------------------------
# 2. Excel (XLSX/XLS) Multi-Sheet Adapter
# ---------------------------------------------------------------------------
def inspect_excel_sheets(file_path: str) -> List[str]:
    """Returns list of sheet names present in an Excel file."""
    excel_file = pd.ExcelFile(file_path)
    return excel_file.sheet_names


def read_excel_adapter(
    file_path: str,
    sheet_name: Optional[str] = None,
    max_rows: int = 50000,
    max_cols: int = 200,
) -> Tuple[pd.DataFrame, List[str], Dict[str, str], str, List[str]]:
    """
    Ingests an Excel file with explicit or default sheet selection.
    Returns:
        (df, warnings, mapping, processed_sheet_name, all_available_sheets)
    """
    excel_file = pd.ExcelFile(file_path)
    available_sheets = excel_file.sheet_names

    if not available_sheets:
        raise ValueError("Excel file contains no worksheets.")

    target_sheet = sheet_name or available_sheets[0]
    if target_sheet not in available_sheets:
        raise ValueError(f"Sheet '{target_sheet}' not found in Excel file. Available sheets: {available_sheets}")

    warnings: List[str] = []
    if len(available_sheets) > 1 and sheet_name is None:
        warnings.append(
            f"Excel file contains multiple worksheets {available_sheets}. Processed first sheet '{target_sheet}'. "
            "Pass 'sheet_name' to select a different sheet."
        )

    df = pd.read_excel(excel_file, sheet_name=target_sheet, dtype=str)

    if len(df) > max_rows:
        raise ValueError(f"Sheet '{target_sheet}' row count ({len(df)}) exceeds limit of {max_rows} rows.")
    if len(df.columns) > max_cols:
        raise ValueError(f"Sheet '{target_sheet}' column count ({len(df.columns)}) exceeds limit of {max_cols} columns.")

    mapping: Dict[str, str] = {}
    new_cols: List[str] = []
    seen: Dict[str, int] = {}

    for idx, col in enumerate(df.columns):
        orig = str(col).strip()
        norm, warn = normalize_column_name(col, idx, seen)
        if warn:
            warnings.append(warn)
        new_cols.append(norm)
        mapping[norm] = orig

    df.columns = new_cols
    return df, warnings, mapping, target_sheet, available_sheets


# ---------------------------------------------------------------------------
# 3. Google Forms Response Export Adapter
# ---------------------------------------------------------------------------
def read_google_forms_adapter(
    file_path: str,
    max_rows: int = 50000,
    max_cols: int = 200,
) -> Tuple[pd.DataFrame, List[str], Dict[str, str], Dict[str, Any]]:
    """
    Ingests Google Forms exported response CSV or XLSX.
    Preserves:
    - Full original question text in mapping
    - Submission timestamps
    - Blank response tracking
    - Repeated submission signals
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in [".xlsx", ".xls"]:
        df, warnings, mapping, _, _ = read_excel_adapter(file_path, max_rows=max_rows, max_cols=max_cols)
    else:
        df, warnings, mapping = read_csv_adapter(file_path, max_rows=max_rows, max_cols=max_cols)

    # Detect timestamp column
    timestamp_cols = [c for c in df.columns if any(k in c.lower() for k in ["timestamp", "submitted_at", "date_time"])]
    timestamp_col = timestamp_cols[0] if timestamp_cols else None

    # Calculate form completeness metrics
    total_responses = len(df)
    question_completeness: Dict[str, float] = {}
    for col in df.columns:
        valid_count = df[col].dropna().apply(lambda v: str(v).strip() != "").sum()
        rate = round(float(valid_count / total_responses), 3) if total_responses > 0 else 0.0
        question_completeness[mapping.get(col, col)] = rate

    forms_metadata = {
        "is_google_forms": True,
        "total_responses": total_responses,
        "timestamp_column": mapping.get(timestamp_col, timestamp_col) if timestamp_col else None,
        "question_completeness_rates": question_completeness,
        "question_count": len(df.columns),
    }

    return df, warnings, mapping, forms_metadata


# ---------------------------------------------------------------------------
# 4. WhatsApp Exported Chat Text (.txt) Adapter
# ---------------------------------------------------------------------------
# Regex patterns for common WhatsApp export formats:
# 12-hour: 01/09/26, 12:33 pm - Sender: Message
# 24-hour: 01/09/2026, 14:33 - Sender: Message
# Bracketed: [01/09/26, 12:33:00 PM] Sender: Message
WA_PATTERNS = [
    re.compile(r"^(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[apAP][mM])?)\s+-\s+"),
    re.compile(r"^\[(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[apAP][mM])?)\]\s+"),
]
ATTACHMENT_MARKERS = ["<media omitted>", "image omitted", "video omitted", "audio omitted", "document omitted", "sticker omitted"]


def read_whatsapp_adapter(
    file_path: str,
    max_messages: int = 50000,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Any]]:
    """
    Parses a WhatsApp exported chat .txt file into structured message records.
    Handles:
    - Multiline continuation messages
    - System/encryption notices
    - Attachment placeholders
    - Aggregate sender metrics (never exposing individual identities in summary)
    """
    warnings: List[str] = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    messages: List[Dict[str, Any]] = []
    current_msg: Optional[Dict[str, Any]] = None
    unparsed_line_count = 0
    system_message_count = 0
    attachment_count = 0
    senders_set = set()

    for line_idx, line in enumerate(lines):
        line_clean = line.rstrip("\r\n")
        if not line_clean.strip():
            continue

        # Check if line starts with a timestamp pattern
        matched = False
        for pat in WA_PATTERNS:
            m = pat.match(line_clean)
            if m:
                # Flush previous message if exists
                if current_msg:
                    messages.append(current_msg)

                date_part = m.group(1)
                time_part = m.group(2)
                rest = line_clean[m.end():]

                # Check if there is a sender: "Sender: Message"
                if ":" in rest:
                    sender_part, msg_text = rest.split(":", 1)
                    sender = sender_part.strip()
                    text = msg_text.strip()
                    is_system = False
                    senders_set.add(sender)
                else:
                    sender = "SYSTEM"
                    text = rest.strip()
                    is_system = True
                    system_message_count += 1

                has_attachment = any(att in text.lower() for att in ATTACHMENT_MARKERS)
                if has_attachment:
                    attachment_count += 1

                current_msg = {
                    "message_ref": f"MSG-{len(messages)+1:05d}",
                    "timestamp": f"{date_part} {time_part}",
                    "sender": sender,
                    "message_text": text,
                    "is_system": "true" if is_system else "false",
                    "has_attachment": "true" if has_attachment else "false",
                    "char_length": len(text),
                    "line_number": line_idx + 1,
                }
                matched = True
                break

        if not matched:
            # Continuation line of previous message
            if current_msg:
                current_msg["message_text"] += f"\n{line_clean}"
                current_msg["char_length"] = len(current_msg["message_text"])
            else:
                unparsed_line_count += 1

    if current_msg:
        messages.append(current_msg)

    if not messages:
        raise ValueError("No recognizable WhatsApp message timestamps found in the file.")

    if len(messages) > max_messages:
        warnings.append(f"WhatsApp chat message count ({len(messages)}) exceeds recommended threshold of {max_messages}.")

    df = pd.DataFrame(messages)

    # Compute source-specific metadata (strictly aggregated, zero PII)
    whatsapp_metadata = {
        "total_messages": len(messages),
        "user_messages": len(messages) - system_message_count,
        "system_messages": system_message_count,
        "unparsed_lines": unparsed_line_count,
        "attachment_placeholders": attachment_count,
        "unique_senders_count": len(senders_set),
        "earliest_timestamp": messages[0]["timestamp"] if messages else None,
        "latest_timestamp": messages[-1]["timestamp"] if messages else None,
    }

    return df, warnings, whatsapp_metadata


# ---------------------------------------------------------------------------
# 5. JSON Adapter
# ---------------------------------------------------------------------------
def _flatten_json_dict(d: Dict[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    """Flattens nested dictionary preserving dotted key paths."""
    items: List[Tuple[str, Any]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
        if isinstance(v, dict):
            items.extend(_flatten_json_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            # For list of primitives, store comma-separated or string representation
            if all(not isinstance(i, (dict, list)) for i in v):
                items.append((new_key, ", ".join(str(i) for i in v)))
            else:
                items.append((new_key, json.dumps(v)))
        else:
            items.append((new_key, v))
    return dict(items)


def read_json_adapter(
    file_path: str,
    max_rows: int = 50000,
    max_cols: int = 200,
) -> Tuple[pd.DataFrame, List[str], Dict[str, str]]:
    """
    Ingests JSON file (array of objects or single nested object).
    Preserves nested dotted keys (e.g. user.address.city).
    """
    warnings: List[str] = []
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as jde:
            raise ValueError(f"Malformed JSON file: {str(jde)}")

    if isinstance(data, dict):
        # Single object -> treat as 1-row table or array inside a top-level key
        for key in ["records", "data", "items", "rows", "patients", "customers"]:
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            data = [data]

    if not isinstance(data, list):
        raise ValueError("JSON file must contain an array of objects or an object with a list of records.")

    # Flatten each record
    flattened_records = []
    for rec in data:
        if isinstance(rec, dict):
            flattened_records.append(_flatten_json_dict(rec))
        else:
            flattened_records.append({"value": str(rec)})

    df = pd.DataFrame(flattened_records).astype(str)
    # Replace 'nan' strings with empty
    df = df.replace("nan", None)

    if len(df) > max_rows:
        raise ValueError(f"JSON record count ({len(df)}) exceeds limit of {max_rows} rows.")
    if len(df.columns) > max_cols:
        raise ValueError(f"JSON field count ({len(df.columns)}) exceeds limit of {max_cols} columns.")

    mapping: Dict[str, str] = {}
    new_cols: List[str] = []
    seen: Dict[str, int] = {}

    for idx, col in enumerate(df.columns):
        orig = str(col).strip()
        norm, warn = normalize_column_name(col, idx, seen)
        if warn:
            warnings.append(warn)
        new_cols.append(norm)
        mapping[norm] = orig

    df.columns = new_cols
    return df, warnings, mapping


# ---------------------------------------------------------------------------
# 6. Scanned Document and Image OCR Adapter
# ---------------------------------------------------------------------------
def read_document_ocr_adapter(
    file_path: str,
    language: Optional[str] = None,
    max_pages: Optional[int] = None,
) -> Tuple[pd.DataFrame, List[str], Dict[str, str], Dict[str, Any]]:
    """
    Ingests PDF (selectable text or scanned) or image files (PNG, JPG, TIFF) via local OCR engine.
    Returns:
        (df, warnings, mapping, metadata)
    """
    from backend.etl.ocr_engine import DocumentExtractor
    extractor = DocumentExtractor(language=language, max_pages=max_pages)
    return extractor.extract(file_path)
