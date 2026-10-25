"""
tests/test_detectors.py
======================
Unit tests for ported deterministic PII/financial/health detectors.
Verifies golden examples (at least 3 valid and 3 invalid strings each, all synthetic),
Verhoeff Aadhaar validation, DOB under-18 calculation relative to fixed reference date,
and ensures detector outputs never contain raw matched text slices.
"""

from datetime import date
import pytest

from backend.etl.identifier_checks import (
    verhoeff_validate,
    detect_aadhaar,
    detect_gstin,
    detect_ifsc,
    detect_upi,
    detect_dob,
    detect_bank_account,
    detect_health,
    detect_name,
    detect_phone,
    detect_email,
    detect_pan,
    detect_all,
)
from backend.services.provenance import compute_impact_tier, classify_column_category


# ---------------------------------------------------------------------------
# Verhoeff Checksum & Aadhaar Detector
# ---------------------------------------------------------------------------

def test_verhoeff_checksum_algorithm():
    # Valid Aadhaar numbers with correct Verhoeff check digits
    assert verhoeff_validate("234567890124") is True
    assert verhoeff_validate("345678901238") is True
    assert verhoeff_validate("456789012341") is True

    # Differ by one digit -> check digit fails
    assert verhoeff_validate("234567890125") is False
    assert verhoeff_validate("345678901239") is False
    assert verhoeff_validate("456789012342") is False


def test_aadhaar_detector_golden_examples():
    # 3 Valid synthetic Aadhaar strings
    valid_examples = [
        "234567890124",
        "Aadhaar: 3456 7890 1238",
        "UID: 4567-8901-2341",
    ]
    for text in valid_examples:
        findings = detect_aadhaar(text)
        assert len(findings) == 1
        f = findings[0]
        assert f["category"] == "aadhaar"
        assert f["validated"] is True
        assert isinstance(f["start"], int) and isinstance(f["end"], int)

    # 3 Invalid synthetic strings
    # 1. Differs by one digit from valid (fails Verhoeff)
    f_invalid_check = detect_aadhaar("234567890125")
    assert len(f_invalid_check) == 1
    assert f_invalid_check[0]["validated"] is False

    # 2. Starts with 1 (invalid for Aadhaar)
    f_starts_with_one = detect_aadhaar("123456789012")
    assert len(f_starts_with_one) == 1
    assert f_starts_with_one[0]["validated"] is False

    # 3. Not an Aadhaar number at all
    f_none = detect_aadhaar("Random customer note without any digits")
    assert len(f_none) == 0


# ---------------------------------------------------------------------------
# GSTIN Detector
# ---------------------------------------------------------------------------

def test_gstin_detector_golden_examples():
    # 3 Valid synthetic GSTIN strings
    valid_gstins = [
        "29ABCDE1234F1Z5",
        "GSTIN: 07AAAAA0000A1Z5 is verified",
        "Supplier GST: 27ABCPA1234F2Z1",
    ]
    for text in valid_gstins:
        findings = detect_gstin(text)
        assert len(findings) == 1
        assert findings[0]["category"] == "gstin"
        assert findings[0]["validated"] is True

    # 3 Invalid synthetic strings
    # 1. Too short (11 chars) -> no candidate match
    assert len(detect_gstin("29ABCDE1234")) == 0
    # 2. Non-numeric state code
    assert len(detect_gstin("INVALIDGSTIN1234")) == 0
    # 3. 15-char candidate with invalid structure (all digits, invalid PAN segment)
    f_bad_structure = detect_gstin("291234567890123")
    assert len(f_bad_structure) == 1
    assert f_bad_structure[0]["validated"] is False


# ---------------------------------------------------------------------------
# IFSC Detector
# ---------------------------------------------------------------------------

def test_ifsc_detector_golden_examples():
    # 3 Valid synthetic IFSC strings
    valid_ifscs = [
        "SBIN0001234",
        "Bank Branch IFSC: HDFC0000001",
        "Remit to ICIC0000102 immediately",
    ]
    for text in valid_ifscs:
        findings = detect_ifsc(text)
        assert len(findings) == 1
        assert findings[0]["category"] == "ifsc"
        assert findings[0]["validated"] is True

    # 3 Invalid synthetic strings
    # 1. 5th char is '1' instead of '0' -> structure invalid
    f_non_zero = detect_ifsc("SBIN1001234")
    assert len(f_non_zero) == 1
    assert f_non_zero[0]["validated"] is False
    # 2. Too short
    assert len(detect_ifsc("HDFC001")) == 0
    # 3. Starts with digits
    assert len(detect_ifsc("12340001234")) == 0


# ---------------------------------------------------------------------------
# UPI Detector
# ---------------------------------------------------------------------------

def test_upi_detector_golden_examples():
    # 3 Valid synthetic UPI handles
    valid_upis = [
        "payer@okaxis",
        "merchant.store@upi",
        "Send refund to payment.desk@paytm",
    ]
    for text in valid_upis:
        findings = detect_upi(text)
        assert len(findings) == 1
        assert findings[0]["category"] == "upi"
        assert findings[0]["validated"] is True

    # 3 Invalid synthetic strings
    # 1. Standard email address (has email TLD)
    assert len(detect_upi("user@gmail.com")) == 0
    # 2. Missing @ handle
    assert len(detect_upi("not_a_upi_handle")) == 0
    # 3. Trailing @ with no provider
    assert len(detect_upi("user@")) == 0


# ---------------------------------------------------------------------------
# DOB Detector (with Minor Flag relative to fixed reference date)
# ---------------------------------------------------------------------------

def test_dob_detector_golden_examples():
    # Fixed reference date: 2026-10-25
    ref_date = date(2026, 10, 25)

    # 1. Minor: Born 2010-05-15 (age 16 < 18)
    f_minor = detect_dob("Date of Birth: 2010-05-15", reference_date=ref_date)
    assert len(f_minor) == 1
    assert f_minor[0]["category"] == "dob"
    assert f_minor[0]["validated"] is True
    assert f_minor[0]["is_minor"] is True

    # 2. Adult: Born 1990-01-01 (age 36 >= 18)
    f_adult = detect_dob("DOB: 1990-01-01", reference_date=ref_date)
    assert len(f_adult) == 1
    assert f_adult[0]["category"] == "dob"
    assert f_adult[0]["validated"] is True
    assert f_adult[0]["is_minor"] is False

    # 3. Minor: Born 2015-11-20 (age 10 < 18)
    f_minor_2 = detect_dob("Birthdate: 20/11/2015", reference_date=ref_date)
    assert len(f_minor_2) == 1
    assert f_minor_2[0]["category"] == "dob"
    assert f_minor_2[0]["validated"] is True
    assert f_minor_2[0]["is_minor"] is True

    # 3 Invalid date strings
    # 1. Impossible date 99-99-9999
    f_bad_date = detect_dob("DOB: 99-99-9999", reference_date=ref_date)
    assert len(f_bad_date) == 1
    assert f_bad_date[0]["validated"] is False
    assert f_bad_date[0]["is_minor"] is False

    # 2. Invalid month/day 2026-15-40
    f_bad_month = detect_dob("2026-15-40", reference_date=ref_date)
    assert len(f_bad_month) == 1
    assert f_bad_month[0]["validated"] is False

    # 3. Pure text
    assert len(detect_dob("Not a valid date string", reference_date=ref_date)) == 0


# ---------------------------------------------------------------------------
# Bank Account Detector
# ---------------------------------------------------------------------------

def test_bank_account_detector_golden_examples():
    # 3 Valid synthetic bank accounts (9-18 digits)
    valid_accounts = [
        "123456789012",             # 12 digits
        "Account: 987654321",       # 9 digits
        "112233445566778899",       # 18 digits
    ]
    for text in valid_accounts:
        findings = detect_bank_account(text)
        assert len(findings) == 1
        assert findings[0]["category"] == "bank_account"
        assert findings[0]["validated"] is True

    # 3 Invalid synthetic strings
    # 1. Too short (4 digits)
    f_short = detect_bank_account("1234")
    assert len(f_short) == 1
    assert f_short[0]["validated"] is False

    # 2. Too long (> 18 digits)
    f_long = detect_bank_account("12345678901234567890")
    assert len(f_long) == 1
    assert f_long[0]["validated"] is False

    # 3. Non-numeric
    assert len(detect_bank_account("No numbers here")) == 0


# ---------------------------------------------------------------------------
# Health Terms Detector
# ---------------------------------------------------------------------------

def test_health_detector_golden_examples():
    # 3 Valid synthetic health sentences
    valid_health = [
        "Patient was diagnosed with diabetes last month.",
        "Screening reported hiv positive status.",
        "Clinical observation: suffering from hypertension.",
    ]
    for text in valid_health:
        findings = detect_health(text)
        assert len(findings) == 1
        assert findings[0]["category"] == "health"
        assert findings[0]["validated"] is True

    # 3 Invalid/Negated health strings
    # 1. No health terms
    assert len(detect_health("Patient is healthy and active.")) == 0
    # 2. Negated: negative for diabetes
    assert len(detect_health("Lab report: negative for diabetes.")) == 0
    # 3. Negated: no hypertension
    assert len(detect_health("Vital check: no hypertension.")) == 0


# ---------------------------------------------------------------------------
# Name Detector
# ---------------------------------------------------------------------------

def test_name_detector_golden_examples():
    # 3 Valid synthetic name occurrences
    valid_names = [
        "Dr. Rohan Sharma attended the consultation",
        "Mr. Arvind Kumar signed the document",
        "Hello, my name is Priya Verma and I am checking in",
    ]
    for text in valid_names:
        findings = detect_name(text)
        assert len(findings) >= 1
        assert findings[0]["category"] == "name"
        assert findings[0]["validated"] is True

    # 3 Invalid strings
    assert len(detect_name("and who with for")) == 0
    assert len(detect_name("12345 67890")) == 0
    assert len(detect_name("just a generic sentence without names")) == 0


# ---------------------------------------------------------------------------
# Phone, Email, PAN Detectors
# ---------------------------------------------------------------------------

def test_phone_email_pan_detectors():
    # Phone
    f_phone = detect_phone("Contact: +91 9876543210")
    assert len(f_phone) == 1 and f_phone[0]["category"] == "phone" and f_phone[0]["validated"] is True
    assert len(detect_phone("not a phone 123")) == 0

    # Email
    f_email = detect_email("Reach us at contact.us@company.in")
    assert len(f_email) == 1 and f_email[0]["category"] == "email" and f_email[0]["validated"] is True
    assert len(detect_email("not an email")) == 0

    # PAN
    f_pan = detect_pan("Permanent Account Number: ABCDE1234F")
    assert len(f_pan) == 1 and f_pan[0]["category"] == "pan" and f_pan[0]["validated"] is True
    assert len(detect_pan("not a pan ABC123")) == 0


# ---------------------------------------------------------------------------
# Strict Contract: NO RAW MATCHED VALUE STORED OR RETURNED
# ---------------------------------------------------------------------------

def test_detectors_never_return_matched_raw_value():
    """
    Contract assertion:
    A detector returns only: category, start and end offsets, validated true/false,
    and is_minor (for dob only).
    It MUST NEVER return the matched value, raw slice, or sample.
    """
    sentinel_val = "234567890124"
    findings = detect_aadhaar(f"UID: {sentinel_val}")
    assert len(findings) == 1
    f = findings[0]

    # Check allowed keys
    assert set(f.keys()) == {"category", "start", "end", "validated"}
    assert sentinel_val not in f.values()
    assert "value" not in f
    assert "raw_value" not in f
    assert "text" not in f
    assert "sample" not in f

    # Check DOB keys
    dob_findings = detect_dob("1990-05-15", reference_date=date(2026, 10, 25))
    assert len(dob_findings) == 1
    f_dob = dob_findings[0]
    assert set(f_dob.keys()) == {"category", "start", "end", "validated", "is_minor"}
    assert "1990-05-15" not in f_dob.values()
    assert "dob_str" not in f_dob
    assert "value" not in f_dob


# ---------------------------------------------------------------------------
# Provenance Category & Impact Tier Mapping
# ---------------------------------------------------------------------------

def test_provenance_impact_tier_and_category_mapping():
    # Tier 3
    assert compute_impact_tier("aadhaar") == "3"
    assert compute_impact_tier("pan") == "3"
    assert compute_impact_tier("health") == "3"
    assert compute_impact_tier("bank_account") == "3"

    # Tier 2
    assert compute_impact_tier("phone") == "2"
    assert compute_impact_tier("email") == "2"
    assert compute_impact_tier("name") == "2"
    assert compute_impact_tier("dob") == "2"
    assert compute_impact_tier("address") == "2"
    assert compute_impact_tier("gstin") == "2"
    assert compute_impact_tier("ifsc") == "2"
    assert compute_impact_tier("upi") == "2"

    # Tier 1
    assert compute_impact_tier("other") == "1"

    # Column classification
    assert classify_column_category("bank_account_num") == "bank_account"
    assert classify_column_category("supplier_gstin") == "gstin"
    assert classify_column_category("branch_ifsc_code") == "ifsc"
    assert classify_column_category("customer_upi_id") == "upi"
