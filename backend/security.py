import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path
from typing import Any, Optional
from backend.config import settings


def get_kavach_key() -> bytes:
    """
    Retrieves or generates the secret key for HMAC hashing.
    1. If KAVACH_KEY env var is present, uses it.
    2. Otherwise reads from data/.key (or {KAVACH_DATA_DIR}/.key).
    3. If .key does not exist, generates 32 cryptographically secure random bytes
       and stores them to {KAVACH_DATA_DIR}/.key.
    No hardcoded key or salt in source code.
    """
    env_key = os.environ.get("KAVACH_KEY")
    if env_key:
        env_key_clean = env_key.strip()
        if len(env_key_clean) == 64:
            try:
                return bytes.fromhex(env_key_clean)
            except ValueError:
                pass
        return env_key_clean.encode("utf-8")

    data_dir = os.environ.get("KAVACH_DATA_DIR", getattr(settings, "kavach_data_dir", "data"))
    os.makedirs(data_dir, exist_ok=True)
    key_path = Path(data_dir) / ".key"
    if key_path.exists():
        return key_path.read_bytes()

    new_key = secrets.token_bytes(32)
    key_path.write_bytes(new_key)
    return new_key


def normalise(kind: str, value: Any) -> str:
    """
    Canonicalizes identifiers prior to hashing or comparisons.
    - phone: strips +91, leading 0, spaces, dashes, brackets -> 10-digit format
    - email: trimmed, lowercase
    - aadhaar: digits only (12 digits)
    - pan: uppercase, whitespace removed (10 chars)
    - name/other: trimmed, lowercase, collapsed internal whitespace
    """
    if value is None:
        return ""
    val_str = str(value).strip()
    k = kind.lower().strip()

    if k in ["phone", "mobile", "phone_in"]:
        digits = re.sub(r"\D", "", val_str)
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]
        return digits

    elif k == "email":
        return val_str.lower()

    elif k in ["aadhaar", "aadhar"]:
        return re.sub(r"\D", "", val_str)

    elif k == "pan":
        return re.sub(r"\s+", "", val_str).upper()

    else:
        # Default / names / free text: lowercase, collapsed whitespace
        return " ".join(val_str.lower().split())


def mask(kind: str, value: Any) -> str:
    """
    Generates a format-preserving masked sample for safe display/logging.
    - phone: XXXXXX + last 4 digits (e.g. XXXXXX4321)
    - email: a***e@d***.com
    - aadhaar: XXXX-XXXX-1234
    - pan: ABXXXXX12C
    - name/other: F***L
    """
    if value is None:
        return ""
    val_str = str(value).strip()
    k = kind.lower().strip()

    if k in ["phone", "mobile", "phone_in"]:
        digits = normalise("phone", val_str)
        if len(digits) >= 4:
            return "X" * (len(digits) - 4) + digits[-4:]
        return "XXXX"

    elif k == "email":
        norm = normalise("email", val_str)
        if "@" in norm:
            user, domain = norm.split("@", 1)
            u_len = len(user)
            masked_u = f"{user[0]}***{user[-1]}" if u_len > 2 else f"{user[0]}***"
            if "." in domain:
                parts = domain.split(".")
                d_name = parts[0]
                tld = ".".join(parts[1:])
                masked_d = f"{d_name[0]}***.{tld}" if len(d_name) > 1 else f"***.{tld}"
            else:
                masked_d = f"{domain[0]}***" if len(domain) > 1 else "***"
            return f"{masked_u}@{masked_d}"
        return "x***@***.com"

    elif k in ["aadhaar", "aadhar"]:
        digits = normalise("aadhaar", val_str)
        if len(digits) == 12:
            return f"XXXX-XXXX-{digits[-4:]}"
        elif len(digits) >= 4:
            return f"XXXX-{digits[-4:]}"
        return "XXXX-XXXX-XXXX"

    elif k == "pan":
        p = normalise("pan", val_str)
        if len(p) == 10:
            return f"{p[:2]}XXXXX{p[-3:]}"
        return "XXXXXXXXXX"

    else:
        v = val_str
        if len(v) <= 2:
            return "*" * len(v)
        return f"{v[0]}{'*' * (len(v) - 2)}{v[-1]}"


def hmac_value(kind: str, value: Any, key: Optional[bytes] = None) -> str:
    """
    Computes an HMAC-SHA256 hex digest of the normalized value.
    Guarantees that different formats of the same identifier produce the exact same HMAC.
    """
    if key is None:
        key = get_kavach_key()
    norm = normalise(kind, value)
    msg = f"{kind.lower()}:{norm}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()
