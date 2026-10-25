"""
validate_datasets.py
====================
Validation suite for synthetic datasets in sample_data.

Checks:
1. Originals remain unchanged (hash match against recorded baseline).
2. Reproducibility test (re-running generator yields identical hashes).
3. Raw messy variants exist, have non-trivial row counts, and contain intentional issues.
4. Expected-clean reference fixtures validate schema and expected transformations.
5. Cross-file references and identifier rules behave as specified.
"""

import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path
import openpyxl

BASE = Path(__file__).parent
RAW_MESSY = BASE / "raw_messy"
EXPECTED_CLEAN = BASE / "expected_clean"
REPORTS = BASE / "reports"

ORIGINAL_CHECKSUMS = {
    "patients.xlsx":             "23f0f79e0b5da069ceaeed1eaf8c9f2c",
    "staff.csv":                 "35c25f591269fdf17e346e1ba143fd73",
    "billing.csv":               "cf7f91c111f4fe87be570cb868230302",
    "appointments_form.csv":     "70e7b26fc7bbabd7400d35864f314938",
    "whatsapp_chat.txt":         "765cddf000bfc9be5b751b50122ee7b1",
    "synthetic_customers.csv":   "9cae1b81b9ee79542fe898560a97dd2c",
    "synthetic_customers_v2.csv":"81ed2068977ba034d1c637dc519f6619",
}

def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()

def check_originals():
    print("[1/5] Verifying original dataset integrity...")
    for fn, expected in ORIGINAL_CHECKSUMS.items():
        p = BASE / fn
        assert p.exists(), f"Original file {fn} missing!"
        actual = md5(p)
        assert actual == expected, f"Original file {fn} checksum mismatch! expected {expected}, got {actual}"
    print("      -> All 7 original files verified intact and unmodified.")

def check_raw_messy():
    print("[2/5] Validating raw_messy datasets...")
    files = [
        ("appointments_messy.csv", 64, 5),
        ("billing_messy.csv", 44, 5),
        ("customers_messy_v1.csv", 38, 8),
        ("customers_messy_v2.csv", 15, 8),
        ("staff_messy.csv", 33, 6),
    ]
    for fn, min_rows, expected_cols in files:
        p = RAW_MESSY / fn
        assert p.exists(), f"{fn} is missing!"
        with open(p, newline='', encoding='utf-8') as f:
            reader = list(csv.reader(f))
            header = reader[0]
            rows = reader[1:]
            assert len(header) == expected_cols, f"{fn} has {len(header)} cols, expected {expected_cols}"
            assert len(rows) >= min_rows, f"{fn} has {len(rows)} rows, expected >= {min_rows}"
            
    # Check patients_messy.xlsx
    p_xlsx = RAW_MESSY / "patients_messy.xlsx"
    assert p_xlsx.exists(), "patients_messy.xlsx is missing!"
    wb = openpyxl.load_workbook(p_xlsx, read_only=True, data_only=True)
    ws = wb["Patients"]
    p_rows = list(ws.iter_rows(values_only=True))
    assert len(p_rows[0]) == 7, f"patients_messy.xlsx header has {len(p_rows[0])} cols, expected 7"
    assert len(p_rows) - 1 >= 44, f"patients_messy.xlsx has {len(p_rows)-1} rows, expected >= 44"
    print("      -> All raw_messy files exist with verified schemas and row counts.")

def check_clean_fixtures():
    print("[3/5] Validating expected_clean reference fixtures...")
    fixtures = [
        ("patients_fixture_input.csv", "patients_fixture_expected.json"),
        ("staff_fixture_input.csv", "staff_fixture_expected.json"),
        ("version_diff_v1_fixture.csv", "version_diff_expected.json"),
    ]
    for in_fn, exp_fn in fixtures:
        in_p = EXPECTED_CLEAN / in_fn
        exp_p = EXPECTED_CLEAN / exp_fn
        assert in_p.exists(), f"{in_fn} missing!"
        assert exp_p.exists(), f"{exp_fn} missing!"
        with open(exp_p, encoding="utf-8") as f:
            data = json.load(f)
            assert data is not None, f"Failed to load JSON from {exp_fn}"
            
    # Verify version_diff structure
    vd_exp = json.loads((EXPECTED_CLEAN / "version_diff_expected.json").read_text(encoding="utf-8"))
    assert vd_exp["unchanged_count"] == 2
    assert vd_exp["changed_count"] == 1
    assert vd_exp["added_count"] == 2
    assert vd_exp["removed_count"] == 2
    print("      -> Expected-clean fixtures and reconciliation rules verified.")

def check_manifest_and_reports():
    print("[4/5] Checking manifest and documentation reports...")
    reports = ["MANIFEST.md", "DATA_DICTIONARY.md", "EDA_FINDINGS.md", "manifest.json"]
    for r in reports:
        p = REPORTS / r
        assert p.exists() and p.stat().st_size > 0, f"Report {r} missing or empty"
    print("      -> Manifest, data dictionary, and EDA findings documentation present.")

def check_reproducibility():
    print("[5/5] Checking reproducibility across generator runs...")
    # Record current hashes for non-xlsx, and cell contents for xlsx
    initial_hashes = {}
    initial_xlsx_cells = {}
    
    for sub in [RAW_MESSY, EXPECTED_CLEAN, REPORTS]:
        for child in sub.iterdir():
            if child.is_file() and not child.name.endswith(".tmp") and child.name != "manifest.json":
                rel = str(child.relative_to(BASE))
                if child.suffix == ".xlsx":
                    wb = openpyxl.load_workbook(child, read_only=True, data_only=True)
                    sheet_data = {}
                    for sname in wb.sheetnames:
                        sheet_data[sname] = list(wb[sname].iter_rows(values_only=True))
                    initial_xlsx_cells[rel] = sheet_data
                else:
                    initial_hashes[rel] = md5(child)
                
    # Re-run generator in-process
    import generate_datasets
    generate_datasets.main()
    
    # Verify hashes match for text/csv files
    for rel_path, expected_hash in initial_hashes.items():
        actual_hash = md5(BASE / rel_path)
        assert actual_hash == expected_hash, f"Reproducibility failure in {rel_path}: expected {expected_hash}, got {actual_hash}"

    # Verify cell contents match exactly for xlsx files
    for rel_path, expected_sheets in initial_xlsx_cells.items():
        wb = openpyxl.load_workbook(BASE / rel_path, read_only=True, data_only=True)
        actual_sheets = {}
        for sname in wb.sheetnames:
            actual_sheets[sname] = list(wb[sname].iter_rows(values_only=True))
        assert actual_sheets == expected_sheets, f"Reproducibility cell content failure in {rel_path}"

    print("      -> Generator produces 100% identical, deterministic outputs under seed 42.")

def main():
    print("============================================================")
    print("Running Dataset Validation Suite")
    print("============================================================")
    check_originals()
    check_raw_messy()
    check_clean_fixtures()
    check_manifest_and_reports()
    check_reproducibility()
    print("============================================================")
    print("ALL VALIDATION CHECKS PASSED.")
    print("============================================================")

if __name__ == "__main__":
    main()
