"""
generate_datasets.py
====================
Reproducible generator for controlled-messy synthetic datasets.

Usage
-----
    python sample_data/generate_datasets.py

Outputs (never touches originals)
----------------------------------
    sample_data/raw_messy/
    sample_data/expected_clean/
    sample_data/reports/

Seed: 42  (change SEED constant to vary output)

Safety rules enforced here
--------------------------
- Originals are hash-verified before and after every run; the script aborts
  if any checksum changes.
- No real personal data is introduced. Identifier-shaped tokens are clearly
  synthetic (e.g. "AADHAAR-TEST-*", phone prefixes 0000, 9999).
- Raw PII from originals is NOT copied verbatim into reports; only counts,
  column names, and pattern statistics are written.
- The whatsapp_chat.txt is analysed in-place; its content is never echoed
  into other output files.
"""

import csv
import hashlib
import json
import os
import random
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl
from openpyxl import Workbook

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SEED = 42
BASE = Path(__file__).parent          # sample_data/
RAW_MESSY = BASE / "raw_messy"
EXPECTED_CLEAN = BASE / "expected_clean"
REPORTS = BASE / "reports"

# Known-good MD5 checksums for the 7 original files.
# Regenerate with: python -c "import hashlib,sys; print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" <file>
ORIGINAL_CHECKSUMS = {
    "patients.xlsx":             "23f0f79e0b5da069ceaeed1eaf8c9f2c",
    "staff.csv":                 "35c25f591269fdf17e346e1ba143fd73",
    "billing.csv":               "cf7f91c111f4fe87be570cb868230302",
    "appointments_form.csv":     "70e7b26fc7bbabd7400d35864f314938",
    "whatsapp_chat.txt":         "765cddf000bfc9be5b751b50122ee7b1",
    "synthetic_customers.csv":   "9cae1b81b9ee79542fe898560a97dd2c",
    "synthetic_customers_v2.csv":"81ed2068977ba034d1c637dc519f6619",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def verify_originals(label: str) -> None:
    print(f"\n[checksum] Verifying originals ({label}) …")
    ok = True
    for fname, expected in ORIGINAL_CHECKSUMS.items():
        p = BASE / fname
        if not p.exists():
            print(f"  MISSING  {fname}")
            ok = False
            continue
        actual = md5(p)
        status = "OK" if actual == expected else "CHANGED *** ABORT ***"
        print(f"  {status}  {fname}")
        if actual != expected:
            ok = False
    if not ok:
        sys.exit("ERROR: one or more original files were modified. Aborting.")


def make_dirs() -> None:
    for d in [RAW_MESSY, EXPECTED_CLEAN, REPORTS]:
        d.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> tuple[list[str], list[list]]:
    """Return (headers, rows) where rows is list-of-list of str."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)
    return rows[0], rows[1:]


def write_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


rng = random.Random(SEED)


# ---------------------------------------------------------------------------
# Messy-value helpers  (all fully synthetic)
# ---------------------------------------------------------------------------
MESSY_EMAILS = [
    "not-an-email",
    "missing_at_sign.example.com",
    "double@@example.com",
    "  spaced@example.com",
    "trailing@example.com  ",
    "",
]

MESSY_PHONES = [
    "0000000000",          # synthetic invalid
    "99999 99999",         # synthetic with space
    "+910000000001",       # synthetic with country code
    "123",                 # too short
    "PHONE-MISSING",       # text placeholder
    "",
]

MESSY_DATES = [
    "01/02/03",            # ambiguous: could be 2001-Feb-03 or 2003-Feb-01 etc.
    "3-4-26",              # ambiguous
    "26/26/2026",          # impossible
    "Feb 30 2026",         # impossible date
    "2026-13-01",          # impossible month
    "tomorrow",            # free text
    "",
]

MESSY_AMOUNTS = [
    "NaN",
    "₹ 1,500",            # currency symbol + comma
    "-999",               # negative
    "FREE",
    "",
]

CATEGORY_VARIANTS = {
    "HIV screening":    ["hiv screening", "HIV Screening", "HIV screening ", " hiv SCREENING", "HIV-Screening"],
    "Regular checkup":  ["regular checkup", "Regular Check-up", "regular check up", "Regular Checkup "],
    "Pregnancy test":   ["pregnancy test", "Pregnancy Test", "PREGNANCY TEST", "prgnancy test"],   # typo
    "Fever since 3 days": ["Fever since 3 days", "fever 3 days", "Fever - 3 days", "fever since 3 days"],
    "Sugar test":       ["sugar test", "Sugar Test", "Blood Sugar", "sugar  test"],
    "Eye checkup":      ["Eye checkup", "eye check up", "Eye Check-up"],
    "Routine CBC":      ["Routine CBC", "routine cbc", "CBC", "Routine C.B.C."],
    "Thyroid check":    ["Thyroid check", "thyroid check", "Thyroid Check", "THYROID"],
    "Lipid profile test": ["Lipid profile test", "lipid profile", "Lipid Profile Test", "lipid test"],
    "Follow up":        ["Follow up", "follow up", "Follow-up", "followup"],
}

TEST_NAME_VARIANTS = {
    "Complete Metabolic Panel": ["Complete metabolic panel", "CMP", "complete metabolic panel", "Metabolic Panel"],
    "Vitamin D":                ["Vitamin D", "vitamin d", "Vit D", "VitaminD"],
    "Thyroid Panel":            ["Thyroid Panel", "thyroid panel", "TSH Panel", "Thyroid panel"],
    "Kidney Function Test":     ["Kidney Function Test", "KFT", "kidney function test", "Kidney function"],
    "CBC":                      ["CBC", "cbc", "Complete Blood Count", "C.B.C"],
    "Lipid Profile":            ["Lipid Profile", "lipid profile", "Lipid panel", "LIPID PROFILE"],
}

HEADER_CASE_VARIANTS = {
    "Name":         ["Name", "name", "NAME", " Name ", "Patient Name", "Patient_Name"],
    "Phone":        ["Phone", "phone", "PHONE", "Phone Number", "phone_number", "Mobile"],
    "Email":        ["Email", "email", "EMAIL", "Email Address", "e-mail"],
    "Aadhaar":      ["Aadhaar", "aadhaar", "AADHAAR", "Aadhar", "Aadhaar Number"],
    "DOB":          ["DOB", "dob", "Date of Birth", "date_of_birth", "DateOfBirth"],
    "Test Name":    ["Test Name", "test name", "Test", "test_name", "TestName"],
    "Notes":        ["Notes", "notes", "NOTES", "Remarks", "remarks"],
}

SYNTHETIC_AADHAAR_TOKENS = [
    "0000-0000-0000",   # clearly invalid/synthetic
    "TEST-AADHAAR-1",
    "XXXX XXXX XXXX",
    "9999 9999 9999",   # synthetic sentinel
    "",
]

SYNTHETIC_PAN_TOKENS = [
    "AAAAA0000A",       # clearly synthetic (all-A + zeros)
    "TEST00001T",
    "XXXXX9999X",
    "",
]


# ===========================================================================
# 1. patients_messy.xlsx
# ===========================================================================
def generate_patients_messy() -> dict:
    """
    Expand patients.xlsx (20 rows) to ~60 rows with controlled issues.
    Returns EDA findings dict.
    """
    wb_orig = openpyxl.load_workbook(BASE / "patients.xlsx", read_only=True, data_only=True)
    ws_orig = wb_orig["Patients"]
    orig_rows = list(ws_orig.iter_rows(values_only=True))
    orig_header = list(orig_rows[0])   # ['Name','Phone','Email','Aadhaar','DOB','Test Name','Notes']
    orig_data = orig_rows[1:]          # 20 data rows

    # --- Build messy header row (mixed case, whitespace, separators) --------
    messy_header = []
    for col in orig_header:
        variants = HEADER_CASE_VARIANTS.get(col, [col])
        messy_header.append(rng.choice(variants))

    # --- Expand base data: repeat originals + inject issues -----------------
    issues = {
        "exact_duplicates": 0,
        "plausible_duplicates": 0,
        "missing_values": {},
        "messy_phones": 0,
        "messy_emails": 0,
        "messy_aadhaar": 0,
        "ambiguous_dates": 0,
        "category_inconsistencies": 0,
        "sensitive_notes": 0,
    }
    messy_rows = []

    # Copy all originals first (clean copies)
    for r in orig_data:
        messy_rows.append(list(r))

    # Add 5 exact duplicate rows
    for _ in range(5):
        src = rng.choice(orig_data)
        messy_rows.append(list(src))
        issues["exact_duplicates"] += 1

    # Add 4 plausible duplicates (same name, slightly different phone)
    plausible_dup_pairs = []
    for _ in range(4):
        src = list(rng.choice(orig_data))
        dup = src[:]
        dup[1] = rng.choice(MESSY_PHONES[:3]) if dup[1] else dup[1]  # change phone only
        messy_rows.append(dup)
        plausible_dup_pairs.append((src[0], dup[0]))
        issues["plausible_duplicates"] += 1

    # Add 15 new synthetic patients (extend dataset)
    new_names = [
        "Arjun Mehta", "Sunita Pillai", "Gopal Das", "Nirmala Bai", "Harish Nambiar",
        "Champa Devi", "Sivakumar R", "Usha Rani", "Baljit Kaur", "Dilnawaz Khan",
        "Tarini Ghosh", "Subramaniam V", "Rohini Patil", "Krishnakumar P", "Zainab Mirza",
    ]
    for i, nm in enumerate(new_names):
        row = [
            nm,
            f"98{rng.randint(10,99)}{rng.randint(1000000,9999999)}",
            f"{nm.lower().replace(' ','.')}{rng.randint(1,99)}@example.com",
            f"{rng.randint(1000,9999)} {rng.randint(1000,9999)} {rng.randint(1000,9999)}",  # synthetic Aadhaar pattern
            str(date(rng.randint(1960, 2000), rng.randint(1, 12), rng.randint(1, 28))),
            rng.choice(list(TEST_NAME_VARIANTS.keys())),
            None,
        ]
        messy_rows.append(row)

    # Now inject issues into copies of existing rows
    # --- Messy phones (5 rows) ---
    phone_col = orig_header.index("Phone")
    indices = rng.sample(range(len(messy_rows)), 5)
    for idx in indices:
        messy_rows[idx][phone_col] = rng.choice(MESSY_PHONES)
        issues["messy_phones"] += 1

    # --- Messy emails (4 rows) ---
    email_col = orig_header.index("Email")
    indices = rng.sample(range(len(messy_rows)), 4)
    for idx in indices:
        messy_rows[idx][email_col] = rng.choice(MESSY_EMAILS)
        issues["messy_emails"] += 1

    # --- Synthetic/invalid Aadhaar tokens (3 rows) ---
    aad_col = orig_header.index("Aadhaar")
    indices = rng.sample(range(len(messy_rows)), 3)
    for idx in indices:
        messy_rows[idx][aad_col] = rng.choice(SYNTHETIC_AADHAAR_TOKENS)
        issues["messy_aadhaar"] += 1

    # --- Ambiguous / impossible dates (4 rows) ---
    dob_col = orig_header.index("DOB")
    indices = rng.sample(range(len(messy_rows)), 4)
    for idx in indices:
        messy_rows[idx][dob_col] = rng.choice(MESSY_DATES)
        issues["ambiguous_dates"] += 1

    # --- Test name category inconsistencies (6 rows) ---
    test_col = orig_header.index("Test Name")
    indices = rng.sample(range(len(messy_rows)), 6)
    for idx in indices:
        orig_val = str(messy_rows[idx][test_col] or "")
        for canonical, variants in TEST_NAME_VARIANTS.items():
            if canonical.lower() in orig_val.lower():
                messy_rows[idx][test_col] = rng.choice(variants)
                issues["category_inconsistencies"] += 1
                break
        else:
            messy_rows[idx][test_col] = rng.choice(list(TEST_NAME_VARIANTS.values())[0])
            issues["category_inconsistencies"] += 1

    # --- Missing optional values (Notes column) ---
    notes_col = orig_header.index("Notes")
    for i, row in enumerate(messy_rows):
        if row[notes_col] is None and rng.random() < 0.4:
            pass  # already None/missing — counted below
    issues["missing_values"]["Notes"] = sum(1 for r in messy_rows if not r[notes_col])
    issues["missing_values"]["Email"] = sum(1 for r in messy_rows if not r[email_col])

    # --- Add contextual notes with sensitive mentions (edge cases for SLM) ---
    sensitive_note_snippets = [
        "Patient has diabetes",
        "Requires follow-up for thyroid",
        "Pregnancy confirmed",
        "Reported HIV negative",
        "Allergy to penicillin",
    ]
    indices = rng.sample(range(len(messy_rows)), 5)
    for idx in indices:
        messy_rows[idx][notes_col] = rng.choice(sensitive_note_snippets)
        issues["sensitive_notes"] += 1

    # --- Extra whitespace in Name column (3 rows) ---
    name_col = orig_header.index("Name")
    for idx in rng.sample(range(len(messy_rows)), 3):
        messy_rows[idx][name_col] = "  " + str(messy_rows[idx][name_col] or "") + "  "

    # Write XLSX
    wb_out = Workbook()
    ws_out = wb_out.active
    ws_out.title = "Patients"
    ws_out.append(messy_header)
    for row in messy_rows:
        ws_out.append(row)
    out_path = RAW_MESSY / "patients_messy.xlsx"
    wb_out.save(out_path)

    findings = {
        "file": "patients_messy.xlsx",
        "source": "patients.xlsx",
        "row_count": len(messy_rows),
        "column_count": len(messy_header),
        "messy_header_applied": messy_header != orig_header,
        "issues": issues,
        "columns_with_personal_data": ["Name", "Phone", "Email", "Aadhaar", "DOB", "Notes"],
        "sensitive_columns": ["Aadhaar", "Notes (health)", "Test Name (health)"],
        "edge_cases_for_slm": [
            "Notes column contains health condition mentions requiring DPDP sensitive-data classification",
            "Aadhaar column contains synthetic invalid tokens and missing values",
            "Test Name includes HIV, pregnancy — sensitive health context",
        ],
    }
    print(f"  Written: {out_path}  rows={len(messy_rows)}")
    return findings


# ===========================================================================
# 2. staff_messy.csv
# ===========================================================================
def generate_staff_messy() -> dict:
    """
    Expand staff.csv (10 rows) to ~40 rows with controlled issues.
    Columns: name, pan, phone, salary, bank_account, ifsc
    """
    orig_headers, orig_data = read_csv(BASE / "staff.csv")
    # orig_headers: ['name','pan','phone','salary','bank_account','ifsc']

    # Messy header variants
    header_map = {
        "name":         ["name", "Name", "NAME", " name ", "Employee Name", "employee_name"],
        "pan":          ["pan", "PAN", "Pan Number", "pan_number", " PAN "],
        "phone":        ["phone", "Phone", "PHONE", "Mobile", "phone_number"],
        "salary":       ["salary", "Salary", "SALARY", "Monthly Salary", "salary_inr"],
        "bank_account": ["bank_account", "Bank Account", "BANK_ACCOUNT", "AccountNumber", "account_no"],
        "ifsc":         ["ifsc", "IFSC", "IFSC Code", "ifsc_code", " IFSC"],
    }
    messy_header = [rng.choice(header_map.get(h, [h])) for h in orig_headers]

    messy_rows = [list(r) for r in orig_data]

    # Add 5 exact duplicates
    for _ in range(5):
        messy_rows.append(list(rng.choice(orig_data)))

    # Add 3 plausible duplicates (same name, different bank_account)
    bank_col = orig_headers.index("bank_account")
    for _ in range(3):
        dup = list(rng.choice(orig_data))
        dup[bank_col] = f"00{rng.randint(10000000, 99999999)}"  # different account, leading zeros
        messy_rows.append(dup)

    # Add 15 new synthetic staff
    dept_pool = ["Accounts", "Reception", "Lab", "Admin", "Pharmacy", "Nursing", "IT", "Security"]
    for i in range(15):
        row = [
            f"Staff Member {i+1:02d}",            # no real names
            rng.choice(SYNTHETIC_PAN_TOKENS[:-1]),  # synthetic PAN-shaped token
            f"98{rng.randint(10,99)}{rng.randint(1000000,9999999)}",
            str(rng.randint(18000, 80000)),
            f"0{rng.randint(100000000, 999999999)}",  # leading-zero account number
            f"HDFC{rng.randint(1000000, 9999999):07d}",
        ]
        messy_rows.append(row)

    # Inject issues
    pan_col = orig_headers.index("pan")
    phone_col = orig_headers.index("phone")
    salary_col = orig_headers.index("salary")

    # Messy phones (4)
    for idx in rng.sample(range(len(messy_rows)), 4):
        messy_rows[idx][phone_col] = rng.choice(MESSY_PHONES)

    # Synthetic PAN tokens (3) — edge cases for identifier detector
    for idx in rng.sample(range(len(messy_rows)), 3):
        messy_rows[idx][pan_col] = rng.choice(SYNTHETIC_PAN_TOKENS)

    # Messy salary values (3)
    for idx in rng.sample(range(len(messy_rows)), 3):
        messy_rows[idx][salary_col] = rng.choice(MESSY_AMOUNTS)

    # Missing values
    for col in [pan_col, phone_col]:
        for idx in rng.sample(range(len(messy_rows)), 2):
            messy_rows[idx][col] = ""

    # Extra whitespace in name (3)
    name_col = orig_headers.index("name")
    for idx in rng.sample(range(len(messy_rows)), 3):
        messy_rows[idx][name_col] = "  " + messy_rows[idx][name_col] + "  "

    write_csv(RAW_MESSY / "staff_messy.csv", messy_header, messy_rows)

    findings = {
        "file": "staff_messy.csv",
        "source": "staff.csv",
        "row_count": len(messy_rows),
        "column_count": len(messy_header),
        "messy_header_applied": True,
        "issues": {
            "exact_duplicates": 5,
            "plausible_duplicates": 3,
            "messy_phones": 4,
            "synthetic_pan_tokens": 3,
            "messy_salary": 3,
            "missing_values": {"pan": 2, "phone": 2},
            "leading_zero_accounts": 18,
            "extra_whitespace_name": 3,
        },
        "columns_with_personal_data": ["name", "pan", "phone", "bank_account"],
        "sensitive_columns": ["pan (GOVERNMENT_ID)", "bank_account (FINANCIAL)", "salary (FINANCIAL)", "ifsc (FINANCIAL)"],
        "edge_cases_for_slm": [
            "PAN column contains clearly synthetic tokens mixed with pattern-valid values",
            "Bank account numbers have leading zeros — must be preserved as TEXT",
            "Salary field has non-numeric entries requiring validation",
        ],
    }
    print(f"  Written: {RAW_MESSY / 'staff_messy.csv'}  rows={len(messy_rows)}")
    return findings


# ===========================================================================
# 3. billing_messy.csv
# ===========================================================================
def generate_billing_messy() -> dict:
    """
    Expand billing.csv (15 rows) to ~50 rows with controlled issues.
    Columns: invoice_no, patient_name, phone, amount, gstin
    """
    orig_headers, orig_data = read_csv(BASE / "billing.csv")

    header_map = {
        "invoice_no":    ["invoice_no", "Invoice No", "InvoiceNo", "invoice_number", " invoice_no"],
        "patient_name":  ["patient_name", "Patient Name", "patient name", "Name", "PatientName"],
        "phone":         ["phone", "Phone", "PHONE", "Mobile", "phone_number"],
        "amount":        ["amount", "Amount", "AMOUNT", "Bill Amount", "amount_inr"],
        "gstin":         ["gstin", "GSTIN", "GST Number", "gstin_no", " GSTIN"],
    }
    messy_header = [rng.choice(header_map.get(h, [h])) for h in orig_headers]

    messy_rows = [list(r) for r in orig_data]

    # Add 4 exact duplicates
    for _ in range(4):
        messy_rows.append(list(rng.choice(orig_data)))

    # Add 25 new synthetic billing records
    inv_no_col = orig_headers.index("invoice_no")
    start_inv = 16
    for i in range(25):
        inv_no = f"INV-2026-{start_inv + i:04d}"
        row = [
            inv_no,
            f"Patient {i+1:02d}",                 # no real names
            f"98{rng.randint(10,99)}{rng.randint(1000000,9999999)}",
            str(rng.randint(500, 15000)),
            "07XOGCA6819L1ZQ" if rng.random() > 0.3 else "",
        ]
        messy_rows.append(row)

    # Inject issues
    phone_col = orig_headers.index("phone")
    amount_col = orig_headers.index("amount")
    gstin_col = orig_headers.index("gstin")
    name_col = orig_headers.index("patient_name")

    # Messy phones (5)
    for idx in rng.sample(range(len(messy_rows)), 5):
        messy_rows[idx][phone_col] = rng.choice(MESSY_PHONES)

    # Messy amounts (4)
    for idx in rng.sample(range(len(messy_rows)), 4):
        messy_rows[idx][amount_col] = rng.choice(MESSY_AMOUNTS)

    # Deliberately invalid invoice references (3) — edge cases
    for idx in rng.sample(range(len(messy_rows)), 3):
        messy_rows[idx][inv_no_col] = f"INV-INVALID-{rng.randint(1,99)}"

    # Missing GSTIN (naturally present in originals)
    for idx in rng.sample(range(len(messy_rows)), 5):
        messy_rows[idx][gstin_col] = ""

    # Extra whitespace (name, 3 rows)
    for idx in rng.sample(range(len(messy_rows)), 3):
        messy_rows[idx][name_col] = "  " + messy_rows[idx][name_col] + "  "

    write_csv(RAW_MESSY / "billing_messy.csv", messy_header, messy_rows)

    findings = {
        "file": "billing_messy.csv",
        "source": "billing.csv",
        "row_count": len(messy_rows),
        "column_count": len(messy_header),
        "messy_header_applied": True,
        "issues": {
            "exact_duplicates": 4,
            "messy_phones": 5,
            "messy_amounts": 4,
            "invalid_invoice_refs": 3,
            "missing_gstin": 5,
            "extra_whitespace_name": 3,
        },
        "cross_file_relationship": "patient_name should match patients.xlsx Name column — invalid refs are labelled edge cases",
        "columns_with_personal_data": ["patient_name", "phone"],
        "sensitive_columns": ["phone (CONTACT)"],
        "edge_cases_for_slm": [
            "Some rows reference patients not present in patients.xlsx (deliberate invalid FK)",
            "GSTIN field: empty cells vs. a shared GSTIN — business-purpose ambiguity for review",
        ],
    }
    print(f"  Written: {RAW_MESSY / 'billing_messy.csv'}  rows={len(messy_rows)}")
    return findings


# ===========================================================================
# 4. appointments_messy.csv
# ===========================================================================
def generate_appointments_messy() -> dict:
    """
    Expand appointments_form.csv (20 rows) to ~70 rows with controlled issues.
    Columns: Timestamp, Name, Phone, Email, Reason
    """
    orig_headers, orig_data = read_csv(BASE / "appointments_form.csv")
    # orig: Timestamp, Name, Phone, Email, Reason

    header_map = {
        "Timestamp":  ["Timestamp", "timestamp", "TIMESTAMP", "Date/Time", "date_time", "submitted_at"],
        "Name":       ["Name", "name", "NAME", " Name ", "Patient Name", "patient_name"],
        "Phone":      ["Phone", "phone", "PHONE", "Mobile", "phone_number"],
        "Email":      ["Email", "email", "EMAIL", "Email Address", "e-mail"],
        "Reason":     ["Reason", "reason", "REASON", "Appointment Reason", "reason_for_visit", "Chief Complaint"],
    }
    messy_header = [rng.choice(header_map.get(h, [h])) for h in orig_headers]

    messy_rows = [list(r) for r in orig_data]

    # Add 6 exact duplicates
    for _ in range(6):
        messy_rows.append(list(rng.choice(orig_data)))

    # Add 3 plausible duplicates (same name+email, different timestamp)
    ts_col = orig_headers.index("Timestamp")
    for _ in range(3):
        dup = list(rng.choice(orig_data))
        dup[ts_col] = "2026/10/25 10:00:00 AM"  # different timestamp
        messy_rows.append(dup)

    # Add 35 new synthetic appointments
    new_names = [
        "Arvind Kumar", "Sushma Rani", "Girish Naik", "Padma Lakshmi", "Firoz Ahmed",
        "Vidya Sagar", "Radha Krishnan", "Pushpa Devi", "Naveen Gowda", "Amrita Kaur",
        "Sanjay Rathod", "Laxmi Bai", "Chandrakant Patil", "Savitha Rao", "Muniraju G",
        "Hemalatha V", "Jayaraj S", "Mumtaz Begum", "Venkat Reddy", "Tara Singh",
        "Bharat Kumar", "Sulochana Devi", "Ramakrishna T", "Anjali Mehta", "Krishnamurthy N",
        "Devika R", "Surendra Babu", "Geetha Kumari", "Ranjith Kumar", "Nagalakshmi S",
        "Ashok Nair", "Saroja Bai", "Muthukumar P", "Rekha Pillai", "Mohan Das",
    ]
    reasons = list(CATEGORY_VARIANTS.keys())
    base_date = date(2026, 10, 1)
    for i, nm in enumerate(new_names):
        delta = timedelta(days=rng.randint(0, 30), hours=rng.randint(8, 18))
        ts = (datetime(2026, 10, 1) + delta).strftime("%Y/%m/%d %I:%M:00 %p")
        row = [
            ts,
            nm,
            f"98{rng.randint(10,99)}{rng.randint(1000000,9999999)}",
            f"{nm.lower().replace(' ','.')}{rng.randint(1,99)}@example.com",
            rng.choice(reasons),
        ]
        messy_rows.append(row)

    # Inject issues
    phone_col = orig_headers.index("Phone")
    email_col = orig_headers.index("Email")
    ts_col = orig_headers.index("Timestamp")
    reason_col = orig_headers.index("Reason")
    name_col = orig_headers.index("Name")

    # Messy phones (7)
    for idx in rng.sample(range(len(messy_rows)), 7):
        messy_rows[idx][phone_col] = rng.choice(MESSY_PHONES)

    # Messy emails (5)
    for idx in rng.sample(range(len(messy_rows)), 5):
        messy_rows[idx][email_col] = rng.choice(MESSY_EMAILS)

    # Ambiguous / impossible timestamps (5)
    MESSY_TS = [
        "01/02/26 10:00 AM",     # ambiguous
        "25-10-2026",            # date only, missing time
        "2026/13/01 09:00:00 AM",  # impossible month
        "morning",               # free text
        "",
    ]
    for idx in rng.sample(range(len(messy_rows)), 5):
        messy_rows[idx][ts_col] = rng.choice(MESSY_TS)

    # Reason category inconsistencies (8)
    for idx in rng.sample(range(len(messy_rows)), 8):
        val = messy_rows[idx][reason_col]
        for canonical, variants in CATEGORY_VARIANTS.items():
            if val and canonical.lower() in val.lower():
                messy_rows[idx][reason_col] = rng.choice(variants)
                break
        else:
            messy_rows[idx][reason_col] = rng.choice(list(CATEGORY_VARIANTS.values())[rng.randint(0,4)])

    # Missing emails (4)
    for idx in rng.sample(range(len(messy_rows)), 4):
        messy_rows[idx][email_col] = ""

    # Extra whitespace in Name (4)
    for idx in rng.sample(range(len(messy_rows)), 4):
        messy_rows[idx][name_col] = "  " + str(messy_rows[idx][name_col]) + "  "

    # Unknown reason — needs owner review (3 rows)
    for idx in rng.sample(range(len(messy_rows)), 3):
        messy_rows[idx][reason_col] = "Other / Not specified"

    write_csv(RAW_MESSY / "appointments_messy.csv", messy_header, messy_rows)

    findings = {
        "file": "appointments_messy.csv",
        "source": "appointments_form.csv",
        "row_count": len(messy_rows),
        "column_count": len(messy_header),
        "messy_header_applied": True,
        "issues": {
            "exact_duplicates": 6,
            "plausible_duplicates": 3,
            "messy_phones": 7,
            "messy_emails": 5,
            "ambiguous_timestamps": 5,
            "missing_emails": 4,
            "reason_category_inconsistencies": 8,
            "unknown_reason_needs_review": 3,
            "extra_whitespace_name": 4,
        },
        "columns_with_personal_data": ["Name", "Phone", "Email"],
        "sensitive_columns": ["Reason (health condition)", "Email (CONTACT)", "Phone (CONTACT)"],
        "edge_cases_for_slm": [
            "Reason field contains HIV screening, pregnancy — sensitive health context",
            "3 rows have 'Other / Not specified' reason — unknown business purpose requiring owner review",
            "Ambiguous timestamps like '01/02/26' cannot be safely parsed without locale context",
        ],
    }
    print(f"  Written: {RAW_MESSY / 'appointments_messy.csv'}  rows={len(messy_rows)}")
    return findings


# ===========================================================================
# 5. customers_messy_v1.csv  and  customers_messy_v2.csv
#    (expanded from synthetic_customers.csv / synthetic_customers_v2.csv)
# ===========================================================================
def generate_customers_messy() -> dict:
    """
    Expand synthetic_customers.csv to ~50 rows (v1) and ~55 rows (v2).
    Columns: customer_id, customer_name, email, phone, pan_number, city, pincode, purchase_amount_inr
    """
    orig_h1, orig_d1 = read_csv(BASE / "synthetic_customers.csv")
    orig_h2, orig_d2 = read_csv(BASE / "synthetic_customers_v2.csv")

    header_map = {
        "customer_id":         ["customer_id", "Customer ID", "CustomerID", " customer_id", "cust_id"],
        "customer_name":       ["customer_name", "Customer Name", "name", "NAME", "CustomerName"],
        "email":               ["email", "Email", "EMAIL", "email_address", "e-mail"],
        "phone":               ["phone", "Phone", "PHONE", "Mobile", "mobile_no"],
        "pan_number":          ["pan_number", "PAN", "PAN Number", "pan_no", " PAN"],
        "city":                ["city", "City", "CITY", "Town", "location"],
        "pincode":             ["pincode", "Pincode", "PIN Code", "postal_code", "pin_code"],
        "purchase_amount_inr": ["purchase_amount_inr", "Amount", "Purchase Amount", "amount_inr", "Purchase (INR)"],
    }
    messy_header_v1 = [rng.choice(header_map.get(h, [h])) for h in orig_h1]

    # ----- V1 (based on synthetic_customers.csv) ----------------------------
    messy_rows_v1 = [list(r) for r in orig_d1]

    city_variants = {
        "Mumbai": ["Mumbai", "mumbai", "MUMBAI", "Bombay", "mumbai "],
        "Ahmedabad": ["Ahmedabad", "ahmedabad", "Ahemdabad", "AHMEDABAD"],  # typo variant
        "Delhi": ["Delhi", "delhi", "New Delhi", "DELHI"],
        "Bengaluru": ["Bengaluru", "Bangalore", "bangalore", "BENGALURU"],
        "Jaipur": ["Jaipur", "jaipur", "JAIPUR"],
        "Kolkata": ["Kolkata", "kolkata", "Calcutta", "KOLKATA"],
        "Kochi": ["Kochi", "kochi", "Cochin", "KOCHI"],
        "Pune": ["Pune", "pune", "PUNE"],
        "Lucknow": ["Lucknow", "lucknow", "LUCKNOW"],
        "Hyderabad": ["Hyderabad", "hyderabad", "HYDERABAD"],
    }

    # Add 3 exact duplicates
    for _ in range(3):
        messy_rows_v1.append(list(rng.choice(orig_d1)))

    # Add 25 new synthetic customers
    cust_id_col = orig_h1.index("customer_id")
    city_col = orig_h1.index("city")
    email_col = orig_h1.index("email")
    phone_col = orig_h1.index("phone")
    pan_col = orig_h1.index("pan_number")
    pin_col = orig_h1.index("pincode")
    amount_col = orig_h1.index("purchase_amount_inr")
    name_col = orig_h1.index("customer_name")

    cities = list(city_variants.keys())
    pin_codes = ["400001","380001","110001","560001","302001","700001","682001","411001","226001","500001",
                 "600001","530001","462001","248001","141001","781001","440001","800001","491001","363001"]

    for i in range(25):
        cid = f"CUST{i+13:03d}"
        city = rng.choice(cities)
        row = [
            cid,
            f"Customer {i+13:03d}",
            f"customer{i+13:03d}@example.com",
            f"9{rng.randint(100000000, 999999999)}",
            f"{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=5))}{rng.randint(1000,9999)}{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=1))}",
            city,
            rng.choice(pin_codes),
            f"{rng.uniform(200, 9999):.2f}",
        ]
        messy_rows_v1.append(row)

    # Inject issues in v1
    for idx in rng.sample(range(len(messy_rows_v1)), 4):
        messy_rows_v1[idx][phone_col] = rng.choice(MESSY_PHONES)
    for idx in rng.sample(range(len(messy_rows_v1)), 3):
        messy_rows_v1[idx][email_col] = rng.choice(MESSY_EMAILS)
    for idx in rng.sample(range(len(messy_rows_v1)), 3):
        messy_rows_v1[idx][pan_col] = rng.choice(SYNTHETIC_PAN_TOKENS)
    for idx in rng.sample(range(len(messy_rows_v1)), 4):
        val = messy_rows_v1[idx][city_col]
        variants = city_variants.get(val, [val])
        messy_rows_v1[idx][city_col] = rng.choice(variants) if variants else val
    for idx in rng.sample(range(len(messy_rows_v1)), 2):
        messy_rows_v1[idx][amount_col] = rng.choice(MESSY_AMOUNTS)
    for idx in rng.sample(range(len(messy_rows_v1)), 2):
        messy_rows_v1[idx][name_col] = "  " + str(messy_rows_v1[idx][name_col]) + "  "

    write_csv(RAW_MESSY / "customers_messy_v1.csv", messy_header_v1, messy_rows_v1)

    # ----- V2 (based on synthetic_customers_v2.csv) — for version diff ------
    # Keep 8 overlapping customers from v1, modify 3, add 7 new, remove 2
    messy_rows_v2 = [list(r) for r in messy_rows_v1[:8]]   # first 8 overlap

    # Modify 3 overlapping rows (amount change)
    for idx in rng.sample(range(8), 3):
        messy_rows_v2[idx][amount_col] = f"{float(messy_rows_v2[idx][amount_col] or 0) * 1.1:.2f}"

    # Add 7 new customers (not in v1)
    for i in range(7):
        cid = f"CUST{i+51:03d}"
        city = rng.choice(cities)
        row = [
            cid,
            f"New Customer {i+1:02d}",
            f"newcust{i+51:03d}@example.com",
            f"9{rng.randint(100000000, 999999999)}",
            f"{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=5))}{rng.randint(1000,9999)}{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ',k=1))}",
            city,
            rng.choice(pin_codes),
            f"{rng.uniform(200, 9999):.2f}",
        ]
        messy_rows_v2.append(row)
    # rows 9-10 from v1 are excluded → 2 removed
    # total: 8 overlap + 7 new = 15 rows in v2

    messy_header_v2 = messy_header_v1[:]  # same header for valid diff
    write_csv(RAW_MESSY / "customers_messy_v2.csv", messy_header_v2, messy_rows_v2)

    findings = {
        "file_v1": "customers_messy_v1.csv",
        "file_v2": "customers_messy_v2.csv",
        "source_v1": "synthetic_customers.csv",
        "source_v2": "synthetic_customers_v2.csv",
        "row_count_v1": len(messy_rows_v1),
        "row_count_v2": len(messy_rows_v2),
        "column_count": len(messy_header_v1),
        "version_diff_expected": {
            "unchanged": 5,
            "changed": 3,
            "added": 7,
            "removed": 2,
        },
        "issues_v1": {
            "exact_duplicates": 3,
            "messy_phones": 4,
            "messy_emails": 3,
            "synthetic_pan_tokens": 3,
            "city_inconsistencies": 4,
            "messy_amounts": 2,
            "extra_whitespace_name": 2,
        },
        "columns_with_personal_data": ["customer_name","email","phone","pan_number"],
        "sensitive_columns": ["pan_number (GOVERNMENT_ID)", "phone (CONTACT)", "email (CONTACT)"],
        "edge_cases_for_slm": [
            "PAN column contains clearly synthetic tokens for identifier detector edge-case testing",
            "City column has regional spelling variants (Mumbai/Bombay, Bengaluru/Bangalore)",
            "V2 excludes 2 customers from V1 — tests REMOVED detection in version reconciler",
        ],
    }
    print(f"  Written: customers_messy_v1.csv rows={len(messy_rows_v1)}, customers_messy_v2.csv rows={len(messy_rows_v2)}")
    return findings


# ===========================================================================
# 6. Expected-clean reference fixtures
# ===========================================================================
def generate_clean_fixtures():
    """
    Small deterministic input → expected-output pairs.
    These are NOT full cleaned datasets — they are 10-row fixtures
    showing exactly which transformations were applied and which issues remain.
    """

    # ---- Fixture A: patients -----------------------------------------------
    # 5 clean + 5 with injected issues; expected output shows what's fixable
    fix_a_raw = [
        # Clean rows
        ["  Ravi Kumar  ", "9876543210",    "ravi.kumar@example.com",   "1234 5678 9012", "1990-05-15", "CBC",              ""],
        ["Sunita Bai",     "8765432109",    "sunita.bai@example.com",   "9876 5432 1098", "1985-11-20", "Thyroid Panel",    ""],
        # Messy: leading/trailing whitespace in name, fixable
        ["  Arjun Das  ",  " 9988776655 ", "arjun.das@example.com",    "2345 6789 0123", "1978-03-10", "Kidney Function Test", ""],
        # Messy: non-email, NOT auto-fixable
        ["Parvati Nair",   "9123456780",    "not-an-email",             "3456 7890 1234", "1992-07-22", "Vitamin D",        ""],
        # Messy: empty phone, NOT auto-fixable (cannot invent)
        ["Mohammed Rafi",  "",              "mrafi@example.com",         "4567 8901 2345", "1970-01-01", "Lipid Profile",    "Allergy to penicillin"],
        # Messy: ambiguous date, NOT auto-fixable
        ["Lakshmi K",      "9001234567",   "lakshmi.k@example.com",    "5678 9012 3456", "01/02/03",   "CBC",              ""],
        # Messy: synthetic Aadhaar token (invalid), flag but don't delete
        ["Gopal Das",      "9876543211",   "gopal.das@example.com",    "TEST-AADHAAR-1", "1988-09-14", "Vitamin D",        ""],
        # Messy: category inconsistency in test name, fixable if canonical mapping exists
        ["Nirmala Devi",   "9765432100",   "nirmala.d@example.com",    "6789 0123 4567", "1975-06-30", "cbc",              ""],
        # Messy: sensitive note — must flag for SLM review, cannot auto-classify
        ["Harish G",       "9654321098",   "harish.g@example.com",     "7890 1234 5678", "1995-12-01", "Thyroid Panel",    "HIV positive"],
        # Exact duplicate of row 0 (fixable: flag, do not auto-delete)
        ["  Ravi Kumar  ", "9876543210",   "ravi.kumar@example.com",   "1234 5678 9012", "1990-05-15", "CBC",              ""],
    ]
    fix_a_expected = [
        # applied_transforms: list of what was done
        # remaining_issues: what could not be auto-resolved
        {
            "row": 0, "name_cleaned": "Ravi Kumar", "phone_cleaned": "9876543210",
            "applied": ["strip_whitespace_name"], "remaining": [],
        },
        {
            "row": 1, "applied": [], "remaining": [],
        },
        {
            "row": 2, "name_cleaned": "Arjun Das", "phone_cleaned": "9988776655",
            "applied": ["strip_whitespace_name", "strip_whitespace_phone"], "remaining": [],
        },
        {
            "row": 3,
            "applied": [],
            "remaining": ["INVALID_EMAIL: 'not-an-email' does not match email pattern; requires human review"],
        },
        {
            "row": 4,
            "applied": [],
            "remaining": ["MISSING_PHONE: cannot infer phone number; requires human review"],
        },
        {
            "row": 5,
            "applied": [],
            "remaining": ["AMBIGUOUS_DATE: '01/02/03' is ambiguous (day/month/year order unclear); not parsed"],
        },
        {
            "row": 6,
            "applied": [],
            "remaining": ["INVALID_AADHAAR_PATTERN: 'TEST-AADHAAR-1' does not match 12-digit pattern; flagged for review"],
        },
        {
            "row": 7,
            "applied": ["normalise_test_name: 'cbc' → 'CBC'"],
            "remaining": ["REVIEW_RECOMMENDED: canonical mapping applied; verify with owner"],
        },
        {
            "row": 8,
            "applied": [],
            "remaining": ["SENSITIVE_NOTES: Note mentions health condition; requires SLM contextual review before classification"],
        },
        {
            "row": 9,
            "applied": [],
            "remaining": ["EXACT_DUPLICATE: duplicate of row 0; flagged for owner decision — not auto-deleted"],
        },
    ]

    fix_a_raw_path = EXPECTED_CLEAN / "patients_fixture_input.csv"
    fix_a_exp_path = EXPECTED_CLEAN / "patients_fixture_expected.json"

    raw_header = ["Name", "Phone", "Email", "Aadhaar", "DOB", "Test Name", "Notes"]
    write_csv(fix_a_raw_path, raw_header, fix_a_raw)
    fix_a_exp_path.write_text(json.dumps(fix_a_expected, indent=2), encoding="utf-8")

    # ---- Fixture B: staff --------------------------------------------------
    fix_b_raw = [
        ["Ramesh Kumar",    "SBSTR6030R",  "9876543210", "46099",  "0046281948219",  "KKBK0351819"],  # leading zero account
        ["  Priya Sharma ", "FYKCP7601Y",  "+917786579754", "51315", "55979711471049", "CNRB0746507"],  # whitespace name
        ["Staff Test 01",   "AAAAA0000A",  "9988776655", "25000",  "0012345678",     "HDFC0619958"],  # synthetic PAN
        ["Staff Test 02",   "",            "9000000000", "30000",  "0099887766",     "ICIC0950032"],  # missing PAN
        ["Staff Test 03",   "XXXXX9999X",  "PHONE-MISSING", "NaN", "0000000001",    "UTIB0172795"],  # messy phone + amount
    ]
    fix_b_expected = [
        {"row": 0, "applied": [], "remaining": ["LEADING_ZERO_ACCOUNT: preserve '0046281948219' as TEXT"]},
        {"row": 1, "name_cleaned": "Priya Sharma", "applied": ["strip_whitespace_name", "normalise_phone: +917786579754 → 7786579754"], "remaining": []},
        {"row": 2, "applied": [], "remaining": ["SYNTHETIC_PAN_TOKEN: 'AAAAA0000A' is a clearly synthetic test value; identifier detector should flag but not classify as real PAN"]},
        {"row": 3, "applied": [], "remaining": ["MISSING_PAN: cannot infer; requires human review"]},
        {"row": 4, "applied": [], "remaining": [
            "INVALID_PHONE: 'PHONE-MISSING' is not a valid phone number",
            "INVALID_SALARY: 'NaN' is not numeric; requires human review",
            "SYNTHETIC_PAN_TOKEN: 'XXXXX9999X' is a test sentinel",
        ]},
    ]
    fix_b_raw_path = EXPECTED_CLEAN / "staff_fixture_input.csv"
    fix_b_exp_path = EXPECTED_CLEAN / "staff_fixture_expected.json"
    write_csv(fix_b_raw_path, ["name","pan","phone","salary","bank_account","ifsc"], fix_b_raw)
    fix_b_exp_path.write_text(json.dumps(fix_b_expected, indent=2), encoding="utf-8")

    # ---- Fixture C: version diff -------------------------------------------
    fix_c_v1 = [
        ["CUST001", "Alpha Ltd",    "alpha@example.com",   "9876543210", "ABCDE1234F", "Mumbai",    "400001", "1500.00"],
        ["CUST002", "Beta Corp",    "beta@example.com",    "9123456780", "BCDEF2345G", "Delhi",     "110001", "2000.00"],
        ["CUST003", "Gamma Inc",    "gamma@example.com",   "9988776655", "CDEFG3456H", "Pune",      "411001", "750.00"],
        ["CUST004", "Delta Stores", "delta@example.com",   "9845012345", "DEFGH4567I", "Kolkata",   "700001", "4500.00"],
        ["CUST005", "Epsilon Ltd",  "epsilon@example.com", "9711223344", "EFGHI5678J", "Chennai",   "600001", "1200.00"],
    ]
    fix_c_v2 = [
        ["CUST001", "Alpha Ltd",    "alpha@example.com",   "9876543210", "ABCDE1234F", "Mumbai",    "400001", "1500.00"],  # unchanged
        ["CUST002", "Beta Corp",    "beta@example.com",    "9123456780", "BCDEF2345G", "Delhi",     "110001", "2500.00"],  # changed: amount
        ["CUST003", "Gamma Inc",    "gamma@example.com",   "9988776655", "CDEFG3456H", "Pune",      "411001", "750.00"],   # unchanged
        # CUST004 removed
        # CUST005 removed
        ["CUST006", "Zeta Traders", "zeta@example.com",   "9900112233", "FGHIJ6789K", "Bengaluru", "560001", "3300.00"],  # added
        ["CUST007", "Eta Retail",   "eta@example.com",    "9811223344", "GHIJK7890L", "Jaipur",    "302001", "800.00"],   # added
    ]
    fix_c_expected_diff = {
        "key_column": "CUST_ID",
        "unchanged_count": 2,
        "changed_count": 1,
        "added_count": 2,
        "removed_count": 2,
        "changed_rows": [{"key": "CUST002", "changed_columns": ["purchase_amount_inr"]}],
        "added_keys": ["CUST006", "CUST007"],
        "removed_keys": ["CUST004", "CUST005"],
    }
    ver_hdr = ["customer_id","customer_name","email","phone","pan_number","city","pincode","purchase_amount_inr"]
    write_csv(EXPECTED_CLEAN / "version_diff_v1_fixture.csv", ver_hdr, fix_c_v1)
    write_csv(EXPECTED_CLEAN / "version_diff_v2_fixture.csv", ver_hdr, fix_c_v2)
    (EXPECTED_CLEAN / "version_diff_expected.json").write_text(
        json.dumps(fix_c_expected_diff, indent=2), encoding="utf-8"
    )

    print(f"  Written: {EXPECTED_CLEAN} — 3 fixture pairs (patients, staff, version_diff)")


# ===========================================================================
# 7. WhatsApp chat EDA findings (in-place analysis, no content copied)
# ===========================================================================
def analyse_whatsapp() -> dict:
    """
    Read whatsapp_chat.txt and produce only statistical findings.
    No raw message content is written to any output file.
    """
    text = (BASE / "whatsapp_chat.txt").read_text(encoding="utf-8")
    lines = text.splitlines()

    # Count patterns without storing matched values
    RE_AADHAAR = re.compile(r'\b\d{4}[\s-]\d{4}[\s-]\d{4}\b')
    RE_PHONE = re.compile(r'(?:\+91[\s-]?|0)?[6-9]\d{9}')
    RE_EMAIL = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    RE_HEALTH = re.compile(r'\b(HIV|pregnancy|diabetes|thyroid|blood test|CBC|Aadhaar)\b', re.I)
    RE_ERASURE = re.compile(r'(delete|hata|number\s+list\s+se|erase|remove.*details)', re.I)

    msg_lines = [l for l in lines if " - " in l and ":" in l]
    participants = set()
    aadhaar_count = 0
    phone_count = 0
    email_count = 0
    health_mentions = 0
    erasure_requests = 0

    for line in msg_lines:
        try:
            rest = line.split(" - ", 1)[1]
            sender = rest.split(":")[0].strip()
            participants.add(sender)
            body = rest.split(":", 1)[1] if ":" in rest else ""
        except IndexError:
            continue
        aadhaar_count += len(RE_AADHAAR.findall(body))
        phone_count += len(RE_PHONE.findall(body))
        email_count += len(RE_EMAIL.findall(body))
        health_mentions += len(RE_HEALTH.findall(body))
        if RE_ERASURE.search(body):
            erasure_requests += 1

    findings = {
        "file": "whatsapp_chat.txt",
        "note": "Statistical analysis only — no raw message content recorded in this report.",
        "total_lines": len(lines),
        "message_lines": len(msg_lines),
        "unique_participants": len(participants),
        "aadhaar_pattern_matches": aadhaar_count,
        "phone_pattern_matches": phone_count,
        "email_pattern_matches": email_count,
        "health_keyword_mentions": health_mentions,
        "erasure_request_signals": erasure_requests,
        "privacy_risk_summary": (
            "Chat log contains Aadhaar-format numbers, phone numbers, and email addresses shared "
            "in plaintext messages. Health conditions and test results mentioned. Multiple messages "
            "appear to signal erasure or opt-out intent. This file requires SLM contextual review "
            "and likely constitutes a data source requiring breach-response assessment."
        ),
        "slm_review_triggers": [
            "Aadhaar numbers shared in plaintext — SENSITIVE_PERSONAL_DATA",
            "Health condition disclosures — SENSITIVE_PERSONAL_DATA / HEALTH category",
            "Erasure-intent signals — potential DPDP Act rights requests to be actioned",
            "Phone numbers and emails shared across participants — CONTACT category",
        ],
        "recommended_action": (
            "DO NOT include raw chat content in any ETL pipeline without explicit owner consent "
            "and legal basis review. Treat as a privacy-incident evidence source."
        ),
    }
    return findings


# ===========================================================================
# 8. Data manifest + data dictionary
# ===========================================================================
def write_manifest(all_findings: list) -> None:
    manifest = {
        "generated_at": "2026-10-25T00:00:00",
        "seed": SEED,
        "regeneration_command": "python sample_data/generate_datasets.py",
        "original_checksums": ORIGINAL_CHECKSUMS,
        "datasets": all_findings,
    }
    (REPORTS / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Human-readable summary
    md = ["# Data Manifest\n",
          f"**Generated:** {manifest['generated_at']}  ",
          f"**Seed:** {SEED}  ",
          f"**Regeneration:** `python sample_data/generate_datasets.py`\n",
          "## Original file checksums (MD5)\n",
          "| File | MD5 | Purpose |",
          "|---|---|---|",
          "| patients.xlsx | 23f0f79e0b5da069ceaeed1eaf8c9f2c | Clinic patient records; highly sensitive |",
          "| staff.csv | 35c25f591269fdf17e346e1ba143fd73 | Payroll with PAN and bank accounts |",
          "| billing.csv | cf7f91c111f4fe87be570cb868230302 | Clinical invoices |",
          "| appointments_form.csv | 70e7b26fc7bbabd7400d35864f314938 | Appointment form submissions |",
          "| whatsapp_chat.txt | 765cddf000bfc9be5b751b50122ee7b1 | WhatsApp chat log (highly sensitive) |",
          "| synthetic_customers.csv | 9cae1b81b9ee79542fe898560a97dd2c | Retail ETL test v1 |",
          "| synthetic_customers_v2.csv | 81ed2068977ba034d1c637dc519f6619 | Retail ETL test v2 |",
          "\n## Generated messy variants\n",
          "| File | Source | Rows | Columns | Key issues |",
          "|---|---|---|---|---|",
    ]
    for f in all_findings:
        if "file" in f:
            row_count = f.get("row_count", "—")
            col_count = f.get("column_count", "—")
            issues = ", ".join(list(f.get("issues", {}).keys())[:3])
            md.append(f"| {f['file']} | {f.get('source','—')} | {row_count} | {col_count} | {issues} |")
        if "file_v1" in f:
            md.append(f"| {f['file_v1']} | {f['source_v1']} | {f['row_count_v1']} | {f['column_count']} | see v1 issues |")
            md.append(f"| {f['file_v2']} | {f['source_v2']} | {f['row_count_v2']} | {f['column_count']} | version diff fixture |")

    md.extend([
        "\n## Expected-clean reference fixtures\n",
        "| File | Purpose |",
        "|---|---|",
        "| patients_fixture_input.csv | 10-row patients input with injected issues |",
        "| patients_fixture_expected.json | Expected transforms + remaining issues per row |",
        "| staff_fixture_input.csv | 5-row staff input with PAN/account edge cases |",
        "| staff_fixture_expected.json | Expected transforms + remaining issues per row |",
        "| version_diff_v1_fixture.csv | 5-row customer dataset v1 |",
        "| version_diff_v2_fixture.csv | 5-row customer dataset v2 |",
        "| version_diff_expected.json | Expected diff: 2 unchanged, 1 changed, 2 added, 2 removed |",
        "\n## Folder structure\n",
        "```",
        "sample_data/",
        "├── (originals — never modified)",
        "├── raw_messy/           ← expanded messy variants for upload/ETL testing",
        "├── expected_clean/      ← small input+expected fixtures for unit testing",
        "├── reports/             ← manifest, data dictionary, EDA summary",
        "└── generate_datasets.py ← this script (reproducible, seed=42)",
        "```",
    ])
    (REPORTS / "MANIFEST.md").write_text("\n".join(md), encoding="utf-8")
    print(f"  Written: {REPORTS / 'MANIFEST.md'}")


def write_data_dictionary() -> None:
    dd = """# Data Dictionary

All datasets below are **synthetic** — no real personal data.
Identifier-shaped fields (PAN, Aadhaar, phone) use clearly synthetic or deliberately
invalid tokens for detector testing. Do not treat any value here as a real identity.

---

## patients.xlsx / patients_messy.xlsx

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| Name | TEXT | Yes | PERSONAL_DATA | Full name — IDENTITY category |
| Phone | PHONE | Yes | PERSONAL_DATA | Indian mobile/landline format |
| Email | EMAIL | Yes | PERSONAL_DATA | CONTACT category |
| Aadhaar | TEXT | Yes | SENSITIVE_PERSONAL_DATA | 12-digit format; some rows have synthetic invalid tokens |
| DOB | DATE | Yes | PERSONAL_DATA | Date of birth; some rows have ambiguous formats |
| Test Name | TEXT | Indirect | PERSONAL_DATA | Health test — implies health category when combined with Name |
| Notes | TEXT | Yes | SENSITIVE_PERSONAL_DATA | Free text; may contain health diagnoses |

---

## staff.csv / staff_messy.csv

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| name | TEXT | Yes | PERSONAL_DATA | Employee name |
| pan | TEXT | Yes | SENSITIVE_PERSONAL_DATA | PAN number — GOVERNMENT_ID; some rows have synthetic tokens |
| phone | PHONE | Yes | PERSONAL_DATA | CONTACT |
| salary | FLOAT | Yes | PERSONAL_DATA | FINANCIAL — personal financial data |
| bank_account | TEXT | Yes | SENSITIVE_PERSONAL_DATA | FINANCIAL; must be stored as TEXT to preserve leading zeros |
| ifsc | TEXT | No | NON_PERSONAL_DATA | Bank branch code — not directly identifying |

---

## billing.csv / billing_messy.csv

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| invoice_no | TEXT | No | NON_PERSONAL_DATA | Invoice reference ID |
| patient_name | TEXT | Yes | PERSONAL_DATA | IDENTITY — linked to patient record |
| phone | PHONE | Yes | PERSONAL_DATA | CONTACT |
| amount | FLOAT | Indirect | PERSONAL_DATA | FINANCIAL when linked to named patient |
| gstin | TEXT | No | NON_PERSONAL_DATA | Business GSTIN — not an individual identifier |

**Cross-file relationship:** `patient_name` should match `patients.xlsx.Name`.
Invalid references are labelled edge cases.

---

## appointments_form.csv / appointments_messy.csv

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| Timestamp | DATETIME | Indirect | PERSONAL_DATA | When combined with Name, reveals attendance |
| Name | TEXT | Yes | PERSONAL_DATA | IDENTITY |
| Phone | PHONE | Yes | PERSONAL_DATA | CONTACT |
| Email | EMAIL | Yes | PERSONAL_DATA | CONTACT |
| Reason | TEXT | Yes | SENSITIVE_PERSONAL_DATA | Appointment reason reveals health context (HIV, pregnancy) |

---

## synthetic_customers.csv / v2 / customers_messy_v1 / v2

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| customer_id | TEXT | No | NON_PERSONAL_DATA | Synthetic key |
| customer_name | TEXT | Yes | PERSONAL_DATA | IDENTITY |
| email | EMAIL | Yes | PERSONAL_DATA | CONTACT |
| phone | PHONE | Yes | PERSONAL_DATA | CONTACT |
| pan_number | TEXT | Yes | SENSITIVE_PERSONAL_DATA | GOVERNMENT_ID; some rows have synthetic tokens |
| city | TEXT | Indirect | PERSONAL_DATA | LOCATION when combined with other fields |
| pincode | TEXT | Indirect | PERSONAL_DATA | LOCATION; preserve as TEXT (leading zeros) |
| purchase_amount_inr | FLOAT | Indirect | PERSONAL_DATA | FINANCIAL when linked to named customer |

---

## whatsapp_chat.txt

Unstructured chat log. Contains:
- Aadhaar numbers in plaintext messages (SENSITIVE_PERSONAL_DATA)
- Phone numbers and email addresses (PERSONAL_DATA)
- Health condition disclosures (SENSITIVE_PERSONAL_DATA)
- Apparent erasure/opt-out requests (DPDP Act rights signals)

**Processing rule:** This file must NOT be ingested via the standard ETL pipeline
without explicit owner consent and legal basis review. Treat as a privacy-incident
evidence source requiring SLM contextual review.
"""
    (REPORTS / "DATA_DICTIONARY.md").write_text(dd, encoding="utf-8")
    print(f"  Written: {REPORTS / 'DATA_DICTIONARY.md'}")


def write_eda_summary(findings_list: list, whatsapp_findings: dict) -> None:
    """Write a dataset-level EDA summary report (no raw values)."""
    lines = ["# EDA Findings Summary\n",
             "Statistical findings only — no raw personal data values recorded.\n"]

    for f in findings_list:
        fname = f.get("file") or f.get("file_v1", "unknown")
        lines.append(f"## {fname}\n")
        lines.append(f"- **Source:** {f.get('source') or f.get('source_v1','—')}")
        lines.append(f"- **Rows:** {f.get('row_count') or f.get('row_count_v1','—')}")
        lines.append(f"- **Columns:** {f.get('column_count','—')}")
        issues = f.get("issues", {})
        if issues:
            lines.append("- **Issues injected:**")
            for k, v in issues.items():
                lines.append(f"  - {k}: {v}")
        pii_cols = f.get("columns_with_personal_data", [])
        if pii_cols:
            lines.append(f"- **Personal data columns:** {', '.join(pii_cols)}")
        sens = f.get("sensitive_columns", [])
        if sens:
            lines.append(f"- **Sensitive columns:** {', '.join(sens)}")
        edge = f.get("edge_cases_for_slm", [])
        if edge:
            lines.append("- **Edge cases for SLM review:**")
            for e in edge:
                lines.append(f"  - {e}")
        if "version_diff_expected" in f:
            vd = f["version_diff_expected"]
            lines.append(f"- **Version diff (v1→v2):** unchanged={vd['unchanged']}, changed={vd['changed']}, added={vd['added']}, removed={vd['removed']}")
        lines.append("")

    lines.append("## whatsapp_chat.txt\n")
    for k, v in whatsapp_findings.items():
        if k not in ("privacy_risk_summary", "recommended_action", "slm_review_triggers"):
            lines.append(f"- **{k}:** {v}")
    lines.append(f"\n**Privacy risk summary:** {whatsapp_findings['privacy_risk_summary']}\n")
    lines.append("**SLM review triggers:**")
    for t in whatsapp_findings["slm_review_triggers"]:
        lines.append(f"  - {t}")
    lines.append(f"\n**Recommended action:** {whatsapp_findings['recommended_action']}")

    (REPORTS / "EDA_FINDINGS.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  Written: {REPORTS / 'EDA_FINDINGS.md'}")


# ===========================================================================
# Main
# ===========================================================================
def main():
    print("=" * 60)
    print("Synthetic dataset generator  (seed=42)")
    print("=" * 60)

    # Re-seed RNG for deterministic reproducibility across runs
    rng.seed(SEED)

    verify_originals("before generation")
    make_dirs()

    print("\n[1] Generating messy variants …")
    findings = []
    findings.append(generate_patients_messy())
    findings.append(generate_staff_messy())
    findings.append(generate_billing_messy())
    findings.append(generate_appointments_messy())
    findings.append(generate_customers_messy())

    print("\n[2] Generating expected-clean reference fixtures …")
    generate_clean_fixtures()

    print("\n[3] Analysing whatsapp_chat.txt (statistics only) …")
    wa_findings = analyse_whatsapp()
    print(f"  Participants: {wa_findings['unique_participants']}  "
          f"Aadhaar patterns: {wa_findings['aadhaar_pattern_matches']}  "
          f"Erasure signals: {wa_findings['erasure_request_signals']}")

    print("\n[4] Writing manifest and data dictionary …")
    write_manifest(findings)
    write_data_dictionary()
    write_eda_summary(findings, wa_findings)

    print("\n[5] Verifying originals unchanged …")
    verify_originals("after generation")

    print("\n" + "=" * 60)
    print("DONE — output structure:")
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in sorted(dirs) if d not in [".venv", "__pycache__"]]
        level = root.replace(str(BASE), "").count(os.sep)
        indent = "  " * level
        folder = os.path.basename(root)
        if level > 0:
            print(f"{indent}{folder}/")
        for f in sorted(files):
            size = os.path.getsize(os.path.join(root, f))
            print(f"{'  ' * (level+1)}{f}  ({size:,} bytes)")
    print("=" * 60)


if __name__ == "__main__":
    main()
