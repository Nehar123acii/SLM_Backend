"""
backend/etl/eda.py
==================
Complete 5-Category Exploratory Data Analysis (EDA) engine:
1. Dataset Overview
2. Completeness and Duplication
3. Numeric Distributions (measurements only; bounded histograms)
4. Categorical Distributions (bounded frequencies; sensitive values redacted)
5. Time, Text and Data Quality

Safety rules enforced:
- Never expose raw sensitive identifiers (Aadhaar, PAN, personal names) in EDA output.
- Bounded histograms (max 10 bins).
- Distinguish between numeric measurements and numeric-formatted identifiers (IDs, PINs, Phones).
"""

import math
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


IDENTIFIER_COLUMN_KEYWORDS = {
    "id", "id_number", "customer_id", "patient_id", "employee_id",
    "pan", "pan_number", "aadhaar", "aadhar", "ssn", "voter_id", "passport",
    "phone", "mobile", "contact", "pin", "pincode", "zip", "postal_code",
    "account", "bank_account", "ifsc", "gstin", "invoice_no", "message_ref"
}


def is_measurement_column(col_name: str, series: pd.Series, inferred_type: str) -> bool:
    """
    Returns True if the column represents a continuous or interval measurement
    (e.g., amount, salary, test value, temperature, age) rather than an identifier.
    """
    col_lower = col_name.lower().replace("-", "_").strip()
    if any(k == col_lower or col_lower.endswith(f"_{k}") or col_lower.startswith(f"{k}_") for k in IDENTIFIER_COLUMN_KEYWORDS):
        return False
    if inferred_type not in ["INTEGER", "FLOAT"]:
        return False
    return True


def compute_numeric_distribution(series: pd.Series) -> Optional[Dict[str, Any]]:
    """
    Computes count, min, max, mean, median, std_dev, q1, q3, iqr, and a 10-bin histogram.
    """
    numeric_s = pd.to_numeric(series.dropna(), errors="coerce").dropna()
    if len(numeric_s) == 0:
        return None

    count = int(len(numeric_s))
    min_val = float(numeric_s.min())
    max_val = float(numeric_s.max())
    mean_val = round(float(numeric_s.mean()), 2)
    median_val = round(float(numeric_s.median()), 2)
    std_val = round(float(numeric_s.std(ddof=1)), 2) if count > 1 else 0.0

    q1 = round(float(numeric_s.quantile(0.25)), 2)
    q3 = round(float(numeric_s.quantile(0.75)), 2)
    iqr = round(q3 - q1, 2)

    # Bounded 10-bin histogram
    histogram = []
    if min_val == max_val:
        histogram.append({
            "bin_start": min_val,
            "bin_end": max_val,
            "count": count,
        })
    else:
        counts, bin_edges = np.histogram(numeric_s, bins=min(10, max(2, count // 2)))
        for i in range(len(counts)):
            histogram.append({
                "bin_start": round(float(bin_edges[i]), 2),
                "bin_end": round(float(bin_edges[i + 1]), 2),
                "count": int(counts[i]),
            })

    return {
        "count": count,
        "min": min_val,
        "max": max_val,
        "mean": mean_val,
        "median": median_val,
        "std_dev": std_val,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "histogram": histogram,
    }


def compute_categorical_distribution(
    col_name: str,
    series: pd.Series,
    ai_sensitivity: Optional[str] = None,
    ai_category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes distinct count, top 10 frequencies, high cardinality flag.
    Redacts raw values if the column is identified as sensitive personal data.
    """
    non_null = series.dropna().astype(str).str.strip()
    total_rows = len(series)
    non_null_count = len(non_null)
    missing_count = total_rows - non_null_count
    missing_pct = round((missing_count / total_rows) * 100, 1) if total_rows > 0 else 0.0

    val_counts = non_null.value_counts()
    distinct_count = len(val_counts)

    is_sensitive = (
        ai_sensitivity in ["SENSITIVE_PERSONAL_DATA", "PERSONAL_DATA"]
        and ai_category in ["GOVERNMENT_ID", "BIOMETRIC", "HEALTH", "IDENTITY"]
    ) or any(k in col_name.lower() for k in ["pan", "aadhaar", "passport", "patient_name", "customer_name"])

    top_categories = []
    for val, cnt in val_counts.head(10).items():
        pct = round((cnt / total_rows) * 100, 1) if total_rows > 0 else 0.0
        display_val = "[REDACTED_SENSITIVE_VALUE]" if is_sensitive else str(val)
        top_categories.append({
            "value": display_val,
            "count": int(cnt),
            "percentage": pct,
        })

    high_cardinality = distinct_count > 50 or (total_rows > 20 and distinct_count / total_rows > 0.6)

    return {
        "distinct_value_count": distinct_count,
        "high_cardinality_warning": high_cardinality,
        "missing_count": missing_count,
        "missing_percentage": missing_pct,
        "top_categories": top_categories,
        "is_redacted": is_sensitive,
    }


def compute_complete_eda(
    df: pd.DataFrame,
    dataset_id: str,
    version: int,
    source_type: str,
    original_filename: str,
    col_types: Dict[str, str],
    etl_issues: List[Dict[str, Any]],
    identifier_findings: List[Dict[str, Any]],
    raw_row_count: int,
    duplicate_count: int,
    rejected_count: int,
    accepted_count: int,
    columns_meta: Optional[List[Dict[str, Any]]] = None,
    source_metadata: Optional[Dict[str, Any]] = None,
    normalization_collisions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Generates the complete 5-category EDA report.
    """
    total_rows = len(df)
    total_cols = len(df.columns)

    # -------------------------------------------------------------
    # Category 1: Dataset Overview
    # -------------------------------------------------------------
    type_dist: Dict[str, int] = {}
    for t in col_types.values():
        type_dist[t] = type_dist.get(t, 0) + 1

    overview = {
        "dataset_id": dataset_id,
        "version": version,
        "original_filename": original_filename,
        "source_type": source_type,
        "format": original_filename.split(".")[-1].lower() if "." in original_filename else "unknown",
        "row_count": total_rows,
        "column_count": total_cols,
        "processing_status": "COMPLETED",
        "type_distribution": type_dist,
        "unknown_type_count": type_dist.get("UNKNOWN", 0),
        "reconciliation_summary": {
            "source_raw_rows": raw_row_count,
            "accepted_rows": accepted_count,
            "rejected_rows": rejected_count,
            "duplicate_rows": duplicate_count,
        },
    }

    if source_type == "document_ocr" and source_metadata:
        overview["document_ocr_summary"] = {
            "document_format": source_metadata.get("document_format", "UNKNOWN"),
            "page_count": source_metadata.get("total_pages", 0),
            "pages_native_text": source_metadata.get("pages_native_text", 0),
            "pages_ocr": source_metadata.get("pages_ocr", 0),
            "pages_empty": source_metadata.get("pages_empty", 0),
            "pages_failed": source_metadata.get("pages_failed", 0),
            "extracted_character_count": source_metadata.get("total_characters", 0),
            "ocr_language": source_metadata.get("ocr_language", "eng"),
            "extraction_warnings": source_metadata.get("extraction_warnings", []),
        }

    # -------------------------------------------------------------
    # Category 2: Completeness and Duplication
    # -------------------------------------------------------------
    missing_counts: Dict[str, Dict[str, Any]] = {}
    total_cells = total_rows * total_cols if total_rows > 0 and total_cols > 0 else 1
    total_missing_cells = 0

    for col in df.columns:
        m_count = int(df[col].isna().sum())
        total_missing_cells += m_count
        m_pct = round((m_count / total_rows) * 100, 2) if total_rows > 0 else 0.0
        missing_counts[col] = {
            "missing_count": m_count,
            "missing_percentage": m_pct,
            "completeness_percentage": round(100.0 - m_pct, 2),
        }

    overall_missing_pct = round((total_missing_cells / total_cells) * 100, 2)

    # Potential duplicates (rows sharing email/phone but not exact identical duplicates)
    potential_duplicates = 0
    contact_cols = [c for c, t in col_types.items() if t in ["EMAIL", "PHONE"] and c in df.columns]
    if contact_cols:
        for ccol in contact_cols:
            s_clean = df[ccol].dropna().astype(str).str.strip()
            dups = s_clean[s_clean.duplicated(keep=False)]
            if len(dups) > 0:
                potential_duplicates += len(dups)

    completeness_and_duplication = {
        "total_missing_cells": total_missing_cells,
        "overall_missingness_percentage": overall_missing_pct,
        "exact_duplicate_rows": duplicate_count,
        "potential_duplicate_candidates": potential_duplicates,
        "missing_counts_per_column": missing_counts,
    }

    # -------------------------------------------------------------
    # Category 3: Numeric Distributions
    # -------------------------------------------------------------
    numeric_distributions: Dict[str, Any] = {}
    for col in df.columns:
        itype = col_types.get(col, "TEXT")
        if is_measurement_column(col, df[col], itype):
            dist = compute_numeric_distribution(df[col])
            if dist:
                numeric_distributions[col] = dist

    # -------------------------------------------------------------
    # Category 4: Categorical Distributions
    # -------------------------------------------------------------
    categorical_distributions: Dict[str, Any] = {}
    cols_meta_map = {c["column_name"]: c for c in (columns_meta or [])}

    for col in df.columns:
        itype = col_types.get(col, "TEXT")
        # Compute for all non-numeric measurements (text, boolean, categories, etc.)
        if col not in numeric_distributions:
            cmeta = cols_meta_map.get(col, {})
            cat_dist = compute_categorical_distribution(
                col_name=col,
                series=df[col],
                ai_sensitivity=cmeta.get("ai_sensitivity"),
                ai_category=cmeta.get("ai_category"),
            )
            categorical_distributions[col] = cat_dist

    # -------------------------------------------------------------
    # Category 5: Time, Text and Data Quality
    # -------------------------------------------------------------
    datetime_summary: Dict[str, Any] = {}
    for col in df.columns:
        if col_types.get(col) in ["DATE", "DATETIME"]:
            parsed = pd.to_datetime(df[col].dropna(), errors="coerce")
            valid = parsed.dropna()
            datetime_summary[col] = {
                "parsed_count": int(len(valid)),
                "failed_parse_count": int(len(parsed) - len(valid)),
                "earliest": str(valid.min()) if not valid.empty else None,
                "latest": str(valid.max()) if not valid.empty else None,
            }

    text_length_summary: Dict[str, Any] = {}
    for col in df.columns:
        if col_types.get(col) in ["TEXT"]:
            lens = df[col].dropna().astype(str).str.len()
            if not lens.empty:
                text_length_summary[col] = {
                    "min_length": int(lens.min()),
                    "max_length": int(lens.max()),
                    "average_length": round(float(lens.mean()), 1),
                }

    etl_issues_breakdown: Dict[str, int] = {}
    for iss in etl_issues:
        itype = iss.get("issue_type", "UNKNOWN")
        etl_issues_breakdown[itype] = etl_issues_breakdown.get(itype, 0) + 1

    time_text_quality = {
        "datetime_summary": datetime_summary,
        "text_length_summary": text_length_summary,
        "normalization_collisions": normalization_collisions or [],
        "invalid_format_counts": {
            f["pattern_type"]: f["match_count"] for f in identifier_findings
        },
        "etl_issues_breakdown": etl_issues_breakdown,
    }

    # Combine into unified 5-category EDA report
    eda_report = {
        "dataset_id": dataset_id,
        "version": version,
        "overview": overview,
        "completeness_and_duplication": completeness_and_duplication,
        "numeric_distributions": numeric_distributions,
        "categorical_distributions": categorical_distributions,
        "time_text_and_quality": time_text_quality,
        "source_specific_metadata": source_metadata or {},
    }

    return eda_report
