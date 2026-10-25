"""
tests/test_i18n.py
==================
Tests for multilingual message catalog (Kavach K14).
Validates:
- Every key in en.json exists in hi.json and kn.json (with informative failure messages listing missing keys).
- Fallback to English works for a missing key and an unknown language.
- Unreviewed keys are flagged machine_translated (and notice displayed).
- Placeholders like {count} match across en, hi, kn for every key.
- API endpoints support ?lang=en|hi|kn (and fall back to English for unknown language).
- Legal citations remain strictly in English.
"""

import json
import os
import re
from fastapi.testclient import TestClient
import pytest

from backend.main import app
from backend.db.engine import get_db
from sqlalchemy.orm import Session
from backend.services.i18n import (
    LocalizedStr,
    get_reviewed_keys,
    mark_key_reviewed,
    reload_locales,
    t,
    t_meta,
    validate_catalog_completeness,
    validate_placeholders_match,
)


@pytest.fixture
def app_client(db_session: Session):
    """Test client overriding database session."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_locales():
    """Ensure catalog cache is reloaded and test reviewed status is clean."""
    reload_locales()
    yield
    reload_locales()


def test_every_key_in_en_exists_in_hi_and_kn():
    """Every key in en.json must exist in hi.json and kn.json."""
    missing = validate_catalog_completeness()
    assert not missing["hi"], f"The following keys in en.json are missing from hi.json: {missing['hi']}"
    assert not missing["kn"], f"The following keys in en.json are missing from kn.json: {missing['kn']}"


def test_placeholders_match_across_all_three_languages():
    """Placeholders such as {count} must match across all three languages for each key."""
    mismatches = validate_placeholders_match()
    assert not mismatches, f"Placeholder mismatches detected: {mismatches}"

    # Specifically test placeholder interpolation
    t_en = t("actions.unknown_purposes.reason", lang="en", count=5)
    t_hi = t("actions.unknown_purposes.reason", lang="hi", count=5)
    t_kn = t("actions.unknown_purposes.reason", lang="kn", count=5)

    assert "5" in t_en
    assert "5" in t_hi
    assert "5" in t_kn


def test_fallback_to_english_for_unknown_language():
    """Unknown language (e.g. 'fr', 'es', 'unknown') falls back to English."""
    key = "flags.health_data_safeguards.title"
    en_val = t(key, lang="en")
    fr_val = t(key, lang="fr")
    xx_val = t(key, lang="invalid_language_code")

    assert str(fr_val) == str(en_val)
    assert str(xx_val) == str(en_val)
    assert fr_val.lang == "en"
    assert xx_val.lang == "en"


def test_fallback_to_english_for_missing_key_in_target_language(monkeypatch):
    """If a key exists in English but is missing in the target catalog, fall back to English."""
    # Temporarily remove a key from Hindi catalog
    from backend.services.i18n import _CATALOGS
    reload_locales()
    # Ensure catalogs are loaded
    t("flags.health_data_safeguards.title", "hi")
    
    hi_cat = _CATALOGS.get("hi", {})
    saved_val = hi_cat.pop("flags.health_data_safeguards.title", None)
    try:
        res = t("flags.health_data_safeguards.title", lang="hi")
        en_val = t("flags.health_data_safeguards.title", lang="en")
        assert str(res) == str(en_val)
    finally:
        if saved_val:
            hi_cat["flags.health_data_safeguards.title"] = saved_val


def test_fallback_to_key_itself_if_missing_everywhere():
    """If a key does not exist even in en.json, return the key itself."""
    missing_key = "non.existent.random.key.12345"
    res = t(missing_key, lang="en")
    assert str(res) == missing_key

    res_hi = t(missing_key, lang="hi")
    assert str(res_hi) == missing_key


def test_unreviewed_keys_are_flagged_machine_translated(tmp_path, monkeypatch):
    """Unreviewed keys are returned with machine_translated=true and UI disclaimer."""
    # Point review_status to empty temp file
    temp_review_file = str(tmp_path / "review_status.json")
    with open(temp_review_file, "w", encoding="utf-8") as f:
        json.dump([], f)

    import backend.services.i18n as i18n_mod
    monkeypatch.setattr(i18n_mod, "_REVIEW_STATUS_FILE", temp_review_file)
    i18n_mod.reload_locales()

    # In Hindi, unreviewed key has machine_translated=True
    hi_val = t("flags.health_data_safeguards.title", lang="hi")
    assert hi_val.machine_translated is True
    assert "machine-translated, not yet reviewed" in hi_val.review_status

    # In Kannada, unreviewed key has machine_translated=True
    kn_val = t("flags.health_data_safeguards.title", lang="kn")
    assert kn_val.machine_translated is True
    assert "machine-translated, not yet reviewed" in kn_val.review_status

    # t_meta also reflects the machine translation flag
    meta = t_meta("flags.health_data_safeguards.title", lang="hi")
    assert meta["machine_translated"] is True
    assert meta["review_status"] == "machine-translated, not yet reviewed"

    # Now mark the key as reviewed and verify machine_translated becomes False
    mark_key_reviewed("flags.health_data_safeguards.title")
    i18n_mod.reload_locales()

    reviewed_val = t("flags.health_data_safeguards.title", lang="hi")
    assert reviewed_val.machine_translated is False
    assert reviewed_val.review_status == "reviewed"


def test_legal_citations_remain_in_english(app_client: TestClient):
    """Legal citations must stay in English across all languages."""
    for lang in ["en", "hi", "kn"]:
        res = app_client.get(f"/api/flags?lang={lang}")
        assert res.status_code == 200
        flags = res.json()
        for f in flags:
            citation = f.get("citation_hint", "")
            if citation:
                # Citations must use ASCII / Latin legal terms like 's.', 'ss.', 'notice', 'safeguards'
                assert any(term in citation for term in ["s.", "ss.", "erasure", "safeguards", "consent", "notice", "processors", "breach"]), (
                    f"Citation '{citation}' for rule {f['rule_id']} in lang={lang} is not in standard English legal form"
                )


def test_api_flags_endpoint_multilingual(app_client: TestClient):
    """GET /api/flags returns localized text with machine_translated metadata."""
    # English
    en_res = app_client.get("/api/flags?lang=en")
    assert en_res.status_code == 200
    en_data = en_res.json()
    assert len(en_data) >= 12
    assert any("Health data security safeguards" in f["title"] for f in en_data)

    # Hindi
    hi_res = app_client.get("/api/flags?lang=hi")
    assert hi_res.status_code == 200
    hi_data = hi_res.json()
    # Check that title is localized in Hindi
    hi_health = next(f for f in hi_data if f["rule_id"] == "health_data_safeguards")
    assert "स्वास्थ्य" in hi_health["title"]
    assert hi_health["machine_translated"] is True

    # Kannada
    kn_res = app_client.get("/api/flags?lang=kn")
    assert kn_res.status_code == 200
    kn_data = kn_res.json()
    kn_health = next(f for f in kn_data if f["rule_id"] == "health_data_safeguards")
    assert "ಆರೋಗ್ಯ" in kn_health["title"]
    assert kn_health["machine_translated"] is True

    # Unknown language falls back to English
    fallback_res = app_client.get("/api/flags?lang=de")
    assert fallback_res.status_code == 200
    fallback_data = fallback_res.json()
    fb_health = next(f for f in fallback_data if f["rule_id"] == "health_data_safeguards")
    assert fb_health["title"] == "Health data security safeguards"


def test_api_questionnaire_endpoint_multilingual(app_client: TestClient):
    """GET /api/questionnaire returns localized questions with ?lang=en|hi|kn."""
    # Hindi
    hi_res = app_client.get("/api/questionnaire?lang=hi")
    assert hi_res.status_code == 200
    hi_questions = hi_res.json()
    assert len(hi_questions) == 8
    cctv_q = next(q for q in hi_questions if q["key"] == "cctv")
    assert "सीसीटीवी" in cctv_q["title"] or "CCTV" in cctv_q["title"]
    assert cctv_q["machine_translated"] is True

    # Kannada
    kn_res = app_client.get("/api/questionnaire?lang=kn")
    assert kn_res.status_code == 200
    kn_questions = kn_res.json()
    cctv_kn = next(q for q in kn_questions if q["key"] == "cctv")
    assert "CCTV" in cctv_kn["title"] or "ಕ್ಯಾಮೆರಾ" in cctv_kn["question"]
    assert cctv_kn["machine_translated"] is True

    # Fallback for unknown language
    fallback_res = app_client.get("/api/questionnaire?lang=unknown")
    assert fallback_res.status_code == 200
    fb_questions = fallback_res.json()
    cctv_fb = next(q for q in fb_questions if q["key"] == "cctv")
    assert cctv_fb["title"] == "CCTV surveillance on premises"


def test_api_checklist_and_notices_multilingual(app_client: TestClient):
    """GET /api/checklist and GET /api/notices return localized items."""
    # Checklist in Hindi
    hi_check = app_client.get("/api/checklist?lang=hi")
    assert hi_check.status_code == 200
    hi_items = hi_check.json()
    assert len(hi_items) == 6
    assert any("नियंत्रण" in item["title"] or "रोकें" in item["title"] for item in hi_items)
    assert hi_items[0]["machine_translated"] is True

    # Notices in Kannada
    kn_notices = app_client.get("/api/notices?lang=kn")
    assert kn_notices.status_code == 200
    kn_data = kn_notices.json()
    assert "header" in kn_data
    assert "ಖಂಡ (a)" in kn_data["sections"]["clause_a"] or "(a)" in kn_data["sections"]["clause_a"]
    assert kn_data["machine_translated"] is True
