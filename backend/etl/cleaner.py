import re
from typing import Any, Dict, List, Tuple
import pandas as pd
import numpy as np

NULL_STRINGS = {"", "null", "NULL", "N/A", "n/a", "NA", "-", "none", "NONE", "None"}
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
PHONE_IN_REGEX = re.compile(r"^(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9]\d{9}$")
URL_REGEX = re.compile(r"^(?:https?:\/\/|www\.)[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)+(?:[\/?#]\S*)?$")
BOOLEAN_SET = {"true", "false", "yes", "no", "1", "0", "t", "f", "y", "n"}


def infer_column_type(series: pd.Series) -> str:
    """
    Infers one of the 10 permitted ETL types:
    TEXT, INTEGER, FLOAT, DATE, DATETIME, BOOLEAN, EMAIL, PHONE, URL, UNKNOWN
    """
    non_null = series.dropna().astype(str).str.strip()
    total_non_null = len(non_null)
    if total_non_null == 0:
        return "UNKNOWN"

    # 1. Email check (>60%)
    email_matches = sum(bool(EMAIL_REGEX.match(v)) for v in non_null)
    if (email_matches / total_non_null) >= 0.6:
        return "EMAIL"

    # 2. Indian Phone check (>60%)
    phone_matches = sum(bool(PHONE_IN_REGEX.match(re.sub(r"[\s\-]", "", v))) for v in non_null)
    if (phone_matches / total_non_null) >= 0.6:
        return "PHONE"

    # 3. URL check (>60%)
    url_matches = sum(bool(URL_REGEX.match(v)) for v in non_null)
    if (url_matches / total_non_null) >= 0.6:
        return "URL"

    # 4. Boolean check (all non-null values belong to boolean set)
    lower_vals = set(non_null.str.lower())
    if lower_vals.issubset(BOOLEAN_SET):
        return "BOOLEAN"

    # 5. Integer check (all non-null values are int-like)
    is_all_int = True
    for v in non_null:
        # Check if v is string representation of integer
        try:
            val_float = float(v)
            if not val_float.is_integer():
                is_all_int = False
                break
        except (ValueError, OverflowError):
            is_all_int = False
            break
    if is_all_int:
        return "INTEGER"

    # 6. Float check (all non-null values are float-like)
    is_all_float = True
    for v in non_null:
        try:
            float(v)
        except (ValueError, OverflowError):
            is_all_float = False
            break
    if is_all_float:
        return "FLOAT"

    # 7. Date / Datetime check (>60% parseable, must look like date string)
    date_candidates = sum(1 for v in non_null if any(char in v for char in ["-", "/", ":"]))
    if (date_candidates / total_non_null) >= 0.6:
        try:
            parsed = pd.to_datetime(non_null, errors="coerce", format="mixed")
            valid_dates = parsed.notna().sum()
            if (valid_dates / total_non_null) >= 0.6:
                # Differentiate DATE vs DATETIME
                has_time = any(":" in v for v in non_null)
                return "DATETIME" if has_time else "DATE"
        except Exception:
            pass

    return "TEXT"


def clean_dataset(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[Dict[str, Any]], Dict[str, str]]:
    """
    Cleans the dataframe:
    - Trims string whitespace
    - Replaces null representations with None
    - Tracks missing-value counts per column
    - Deduplicates identical rows
    - Infers types for each column

    Returns:
        (cleaned_df, list of etl_issue dicts, column_type_map)
    """
    etl_issues: List[Dict[str, Any]] = []

    # Clean cell values
    df_clean = df.copy()
    for col in df_clean.columns:
        if df_clean[col].dtype == object or isinstance(df_clean[col].dtype, pd.StringDtype):
            df_clean[col] = df_clean[col].apply(
                lambda val: val.strip() if isinstance(val, str) else val
            )
            df_clean[col] = df_clean[col].apply(
                lambda val: None if val in NULL_STRINGS or (isinstance(val, float) and np.isnan(val)) else val
            )
        else:
            # For numeric columns, replace NaN with None
            df_clean[col] = df_clean[col].apply(lambda val: None if pd.isna(val) else val)

    # Missing values tracking per column
    for col in df_clean.columns:
        missing_count = int(df_clean[col].isna().sum())
        if missing_count > 0:
            etl_issues.append({
                "issue_type": "MISSING",
                "column_name": col,
                "row_index": None,
                "detail": f"Column '{col}' has {missing_count} missing value(s)."
            })

    # Fully duplicate rows
    dup_mask = df_clean.duplicated(keep="first")
    duplicate_indices = df_clean[dup_mask].index.tolist()
    if duplicate_indices:
        for row_idx in duplicate_indices:
            etl_issues.append({
                "issue_type": "DUPLICATE",
                "column_name": None,
                "row_index": int(row_idx),
                "detail": f"Duplicate row identified and removed at original index {row_idx}."
            })
        df_clean = df_clean.drop_duplicates(keep="first").reset_index(drop=True)

    # Infer column types
    column_type_map: Dict[str, str] = {}
    for col in df_clean.columns:
        column_type_map[col] = infer_column_type(df_clean[col])

    return df_clean, etl_issues, column_type_map
