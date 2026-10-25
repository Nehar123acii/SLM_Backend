"""
backend/etl/reader.py
=====================
Unified file ingestion dispatcher delegating to source-specific adapters:
- CSV
- Excel (XLSX / XLS)
- Google Forms exports
- WhatsApp exported chat text
- JSON exports

Maintains full backward compatibility for existing `read_file_to_df(file_path)`.
"""

import os
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from backend.config import settings
from backend.etl.adapters import (
    SUPPORTED_SOURCES,
    inspect_excel_sheets,
    read_csv_adapter,
    read_excel_adapter,
    read_google_forms_adapter,
    read_whatsapp_adapter,
    read_json_adapter,
    read_document_ocr_adapter,
)


def detect_source_type(file_path: str, hint: Optional[str] = None) -> str:
    """
    Determines source type based on user hint or file extension/content heuristics.
    """
    if hint:
        valid_types = {s["source_type"] for s in SUPPORTED_SOURCES}
        if hint.lower() in valid_types:
            return hint.lower()

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        return "csv"
    elif ext in [".xlsx", ".xls"]:
        return "excel"
    elif ext == ".json":
        return "json"
    elif ext in [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"]:
        return "document_ocr"
    elif ext == ".txt":
        # Check if first few lines look like WhatsApp chat
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                first_lines = [f.readline() for _ in range(5)]
            if any(" - " in l and any(char in l for char in ["/", "-", "."]) for l in first_lines):
                return "whatsapp"
        except Exception:
            pass
        return "text"

    # Signature / magic byte fallback
    try:
        with open(file_path, "rb") as f:
            head = f.read(16)
        if (
            head.startswith(b"%PDF-")
            or head.startswith(b"\x89PNG\r\n\x1a\n")
            or head.startswith(b"\xff\xd8\xff")
            or head.startswith(b"II*\x00")
            or head.startswith(b"MM\x00*")
        ):
            return "document_ocr"
    except Exception:
        pass

    return "unknown"


def read_file_to_df(
    file_path: str,
    source_type: Optional[str] = None,
    sheet_name: Optional[str] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Backward-compatible wrapper returning (df, list of warnings).
    """
    df, warnings, _, _ = read_file_with_metadata(
        file_path=file_path,
        source_type=source_type,
        sheet_name=sheet_name,
    )
    return df, warnings


def read_file_with_metadata(
    file_path: str,
    source_type: Optional[str] = None,
    sheet_name: Optional[str] = None,
    language: Optional[str] = None,
) -> Tuple[pd.DataFrame, List[str], Dict[str, str], Dict[str, Any]]:
    """
    Comprehensive reader returning:
    - pd.DataFrame
    - warnings (list of str)
    - column_mapping (dict: normalized_col -> original_col)
    - metadata (dict with source-specific details)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    resolved_source_type = detect_source_type(file_path, hint=source_type)
    warnings: List[str] = []
    mapping: Dict[str, str] = {}
    metadata: Dict[str, Any] = {
        "source_type": resolved_source_type,
        "original_filename": os.path.basename(file_path),
        "file_size_bytes": os.path.getsize(file_path),
    }

    if resolved_source_type == "csv":
        df, warns, mapping = read_csv_adapter(
            file_path,
            max_rows=settings.max_upload_rows,
            max_cols=settings.max_upload_columns,
        )
        warnings.extend(warns)

    elif resolved_source_type == "excel":
        df, warns, mapping, processed_sheet, available_sheets = read_excel_adapter(
            file_path,
            sheet_name=sheet_name,
            max_rows=settings.max_upload_rows,
            max_cols=settings.max_upload_columns,
        )
        warnings.extend(warns)
        metadata["sheet_name"] = processed_sheet
        metadata["available_sheets"] = available_sheets

    elif resolved_source_type == "google_forms":
        df, warns, mapping, forms_meta = read_google_forms_adapter(
            file_path,
            max_rows=settings.max_upload_rows,
            max_cols=settings.max_upload_columns,
        )
        warnings.extend(warns)
        metadata.update(forms_meta)

    elif resolved_source_type == "whatsapp":
        df, warns, wa_meta = read_whatsapp_adapter(
            file_path,
            max_messages=settings.max_upload_rows,
        )
        warnings.extend(warns)
        metadata.update(wa_meta)
        mapping = {c: c for c in df.columns}

    elif resolved_source_type == "json":
        df, warns, mapping = read_json_adapter(
            file_path,
            max_rows=settings.max_upload_rows,
            max_cols=settings.max_upload_columns,
        )
        warnings.extend(warns)

    elif resolved_source_type == "document_ocr":
        df, warns, mapping, doc_meta = read_document_ocr_adapter(
            file_path=file_path,
            language=language,
            max_pages=settings.ocr_max_pages,
        )
        warnings.extend(warns)
        metadata.update(doc_meta)

    else:
        ext = os.path.splitext(file_path)[1].lower()
        raise ValueError(
            f"Unsupported file format '{ext}' and source type '{resolved_source_type}'. "
            "Supported source types: csv, excel, google_forms, whatsapp, json, document_ocr."
        )

    return df, warnings, mapping, metadata
