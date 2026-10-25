"""
backend/services/i18n.py
========================
Multilingual message catalog and translation service for Kavach.
Supports English ('en'), Hindi ('hi'), and Kannada ('kn').
Provides:
- t(key, lang, **kwargs) -> LocalizedStr with English fallback.
- t_meta(key, lang, **kwargs) -> Dict with machine_translated metadata.
- Native review tracking via locales/review_status.json.
- Placeholders verification across languages.
- Safe handling of missing keys and unknown languages.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = {"en", "hi", "kn"}
DEFAULT_LANGUAGE = "en"
REVIEW_NOTICE_TEXT = "machine-translated, not yet reviewed"

_LOCALES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "locales",
)
_REVIEW_STATUS_FILE = os.path.join(_LOCALES_DIR, "review_status.json")

# In-memory caches
_CATALOGS: Dict[str, Dict[str, str]] = {}
_REVIEWED_KEYS: Optional[Set[str]] = None


class LocalizedStr(str):
    """
    Subclass of str that preserves translation metadata (machine_translated flag,
    review status, and resolved language) while behaving exactly as a standard Python str.
    """
    machine_translated: bool
    review_status: str
    lang: str
    key: str

    def __new__(
        cls,
        content: str,
        machine_translated: bool = False,
        review_status: str = "",
        lang: str = "en",
        key: str = "",
    ):
        instance = super().__new__(cls, content)
        instance.machine_translated = machine_translated
        instance.review_status = review_status
        instance.lang = lang
        instance.key = key
        return instance


def _load_catalog(lang: str) -> Dict[str, str]:
    """Loads a JSON catalog for the specified language."""
    if lang in _CATALOGS:
        return _CATALOGS[lang]

    path = os.path.join(_LOCALES_DIR, f"{lang}.json")
    if not os.path.exists(path):
        logger.warning("Locale catalog not found for lang '%s' at %s", lang, path)
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            _CATALOGS[lang] = data
            return data
    except Exception as e:
        logger.error("Error loading locale catalog for '%s': %s", lang, e)
        return {}


def get_reviewed_keys(force_reload: bool = False) -> Set[str]:
    """Retrieves the set of reviewed keys from locales/review_status.json."""
    global _REVIEWED_KEYS
    if _REVIEWED_KEYS is not None and not force_reload:
        return _REVIEWED_KEYS

    if not os.path.exists(_REVIEW_STATUS_FILE):
        _REVIEWED_KEYS = set()
        return _REVIEWED_KEYS

    try:
        with open(_REVIEW_STATUS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            if isinstance(raw, list):
                _REVIEWED_KEYS = set(raw)
            elif isinstance(raw, dict):
                _REVIEWED_KEYS = set(raw.keys())
            else:
                _REVIEWED_KEYS = set()
    except Exception as e:
        logger.warning("Failed to load review_status.json: %s", e)
        _REVIEWED_KEYS = set()

    return _REVIEWED_KEYS


def mark_key_reviewed(key: str, lang: Optional[str] = None) -> None:
    """Marks a key (or lang:key) as reviewed by a native speaker."""
    current = get_reviewed_keys()
    entry = f"{lang}:{key}" if lang else key
    current.add(entry)
    with open(_REVIEW_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(current)), f, indent=2)


def reload_locales() -> None:
    """Clears in-memory caches to reload locale catalogs and review status."""
    global _CATALOGS, _REVIEWED_KEYS
    _CATALOGS.clear()
    _REVIEWED_KEYS = None


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs: Any) -> LocalizedStr:
    """
    Translates a key into the target language with fallback to English.
    
    If the requested language is unknown, falls back to 'en'.
    If the key is missing in the target language catalog, falls back to 'en'.
    If missing in 'en', returns the key itself.
    
    Returns a LocalizedStr string instance with:
    - .machine_translated: bool (True if target lang != 'en' and key not reviewed by native speaker)
    - .review_status: str ('reviewed' or 'machine-translated, not yet reviewed')
    - .lang: str (the resolved language)
    - .key: str (the lookup key)
    """
    requested_lang = (lang or DEFAULT_LANGUAGE).strip().lower()
    target_lang = requested_lang if requested_lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    catalog = _load_catalog(target_lang)
    raw_template = catalog.get(key)
    resolved_lang = target_lang

    if raw_template is None and target_lang != DEFAULT_LANGUAGE:
        # Fallback to English
        en_catalog = _load_catalog(DEFAULT_LANGUAGE)
        raw_template = en_catalog.get(key)
        resolved_lang = DEFAULT_LANGUAGE

    if raw_template is None:
        # Fallback to key itself if not found even in English
        raw_template = key
        resolved_lang = DEFAULT_LANGUAGE

    # Review status determination
    reviewed_keys = get_reviewed_keys()
    is_reviewed = (key in reviewed_keys) or (f"{resolved_lang}:{key}" in reviewed_keys)

    if resolved_lang == DEFAULT_LANGUAGE:
        machine_translated = False
        review_status = "reviewed"
    else:
        machine_translated = not is_reviewed
        review_status = "reviewed" if is_reviewed else REVIEW_NOTICE_TEXT

    # Interpolate keyword arguments
    if kwargs:
        try:
            formatted_text = raw_template.format(**kwargs)
        except (KeyError, ValueError, IndexError) as err:
            logger.debug("Failed placeholder formatting on key '%s' (%s): %s", key, raw_template, err)
            formatted_text = raw_template
    else:
        formatted_text = raw_template

    return LocalizedStr(
        content=formatted_text,
        machine_translated=machine_translated,
        review_status=review_status,
        lang=resolved_lang,
        key=key,
    )


def t_meta(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs: Any) -> Dict[str, Any]:
    """
    Returns a dictionary containing the translated text along with explicit metadata.
    """
    localized = t(key, lang=lang, **kwargs)
    return {
        "text": str(localized),
        "machine_translated": localized.machine_translated,
        "review_status": localized.review_status,
        "lang": localized.lang,
        "key": localized.key,
    }


def validate_catalog_completeness() -> Dict[str, List[str]]:
    """
    Validates that all keys present in en.json exist in hi.json and kn.json.
    Returns a dictionary of missing keys per language: {'hi': [...], 'kn': [...]}.
    """
    en_cat = _load_catalog("en")
    hi_cat = _load_catalog("hi")
    kn_cat = _load_catalog("kn")

    missing: Dict[str, List[str]] = {"hi": [], "kn": []}
    for k in sorted(en_cat.keys()):
        if k not in hi_cat:
            missing["hi"].append(k)
        if k not in kn_cat:
            missing["kn"].append(k)

    return missing


def validate_placeholders_match() -> List[str]:
    """
    Validates that placeholder variables (e.g. {count}) match identically
    across English, Hindi, and Kannada for every key.
    Returns a list of error descriptions, or an empty list if all match.
    """
    en_cat = _load_catalog("en")
    hi_cat = _load_catalog("hi")
    kn_cat = _load_catalog("kn")

    placeholder_pattern = re.compile(r"\{([a-zA-Z0-9_]+)\}")
    errors: List[str] = []

    for k, en_val in en_cat.items():
        en_vars = set(placeholder_pattern.findall(en_val))
        hi_val = hi_cat.get(k, "")
        hi_vars = set(placeholder_pattern.findall(hi_val))
        kn_val = kn_cat.get(k, "")
        kn_vars = set(placeholder_pattern.findall(kn_val))

        if en_vars != hi_vars:
            errors.append(f"Key '{k}' placeholder mismatch between 'en' {sorted(en_vars)} and 'hi' {sorted(hi_vars)}")
        if en_vars != kn_vars:
            errors.append(f"Key '{k}' placeholder mismatch between 'en' {sorted(en_vars)} and 'kn' {sorted(kn_vars)}")

    return errors
