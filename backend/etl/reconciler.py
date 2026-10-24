import json
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd


def reconcile_datasets(
    prev_df: pd.DataFrame,
    new_df: pd.DataFrame,
    key_columns: Optional[List[str]] = None,
) -> Tuple[int, int, int, int, str]:
    """
    Compares two versions of a dataset.
    Identifies added, changed, removed, and unchanged rows.

    Returns:
        (added_count, changed_count, removed_count, unchanged_count, diff_json_str)
    """
    if key_columns:
        valid_keys = [k for k in key_columns if k in prev_df.columns and k in new_df.columns]
    else:
        valid_keys = []

    if not valid_keys:
        # Default to first column common to both, or first column of new_df
        common_cols = [c for c in new_df.columns if c in prev_df.columns]
        valid_keys = [common_cols[0]] if common_cols else [new_df.columns[0]]

    # Helper to construct row key
    def get_row_key(df: pd.DataFrame, idx: int) -> str:
        vals = [str(df.at[idx, k]) for k in valid_keys]
        return "___".join(vals)

    prev_key_to_idx = {get_row_key(prev_df, i): i for i in prev_df.index}
    new_key_to_idx = {get_row_key(new_df, i): i for i in new_df.index}

    added_indices: List[int] = []
    removed_indices: List[int] = []
    changed_records: List[Dict[str, Any]] = []
    unchanged_count = 0

    common_cols = [c for c in new_df.columns if c in prev_df.columns and c not in valid_keys]

    for new_key, new_idx in new_key_to_idx.items():
        if new_key not in prev_key_to_idx:
            added_indices.append(int(new_idx))
        else:
            prev_idx = prev_key_to_idx[new_key]
            changed_cols_for_row: List[str] = []
            for col in common_cols:
                prev_val = prev_df.at[prev_idx, col]
                new_val = new_df.at[new_idx, col]
                # Compare handling None/NaN
                prev_is_null = pd.isna(prev_val) or prev_val is None
                new_is_null = pd.isna(new_val) or new_val is None
                if prev_is_null and new_is_null:
                    continue
                if prev_is_null != new_is_null or str(prev_val) != str(new_val):
                    changed_cols_for_row.append(col)

            if changed_cols_for_row:
                changed_records.append({
                    "row_index": int(new_idx),
                    "changed_columns": changed_cols_for_row,
                })
            else:
                unchanged_count += 1

    for prev_key, prev_idx in prev_key_to_idx.items():
        if prev_key not in new_key_to_idx:
            removed_indices.append(int(prev_idx))

    added_count = len(added_indices)
    changed_count = len(changed_records)
    removed_count = len(removed_indices)

    diff_summary = {
        "key_columns": valid_keys,
        "added_count": added_count,
        "changed_count": changed_count,
        "removed_count": removed_count,
        "unchanged_count": unchanged_count,
        "added_row_indices": added_indices,
        "removed_row_indices": removed_indices,
        "changed_rows": changed_records,
    }

    return added_count, changed_count, removed_count, unchanged_count, json.dumps(diff_summary)
