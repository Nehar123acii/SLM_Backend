import os
from typing import List, Tuple
import pandas as pd
from backend.config import settings


def read_file_to_df(file_path: str) -> Tuple[pd.DataFrame, List[str]]:
    """
    Reads a CSV or XLSX file into a pandas DataFrame.
    Normalises column headers and validates maximum row and column thresholds.

    Returns:
        (DataFrame, list of warning strings)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    warnings: List[str] = []

    if ext == ".csv":
        try:
            df = pd.read_csv(file_path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding="latin-1")
            warnings.append("File could not be parsed as UTF-8; fell back to latin-1 encoding.")
    elif ext in [".xlsx", ".xls"]:
        df = pd.read_excel(file_path, sheet_name=0)
    else:
        raise ValueError(f"Unsupported file format '{ext}'. Only .csv and .xlsx files are supported.")

    # Validate limits
    row_count = len(df)
    col_count = len(df.columns)

    if row_count > settings.max_upload_rows:
        raise ValueError(
            f"Row count ({row_count}) exceeds the maximum allowed limit of {settings.max_upload_rows} rows."
        )

    if col_count > settings.max_upload_columns:
        raise ValueError(
            f"Column count ({col_count}) exceeds the maximum allowed limit of {settings.max_upload_columns} columns."
        )

    # Normalise column names
    new_cols = []
    seen = {}
    for idx, col in enumerate(df.columns):
        col_str = str(col).strip().lstrip("\ufeff").lower().replace(" ", "_")
        if not col_str:
            col_str = f"unnamed_col_{idx}"
        # Ensure column uniqueness
        if col_str in seen:
            seen[col_str] += 1
            col_str = f"{col_str}_{seen[col_str]}"
        else:
            seen[col_str] = 0
        new_cols.append(col_str)

    df.columns = new_cols
    return df, warnings
