import os
import secrets
import tempfile
from backend.security import normalise, mask, hmac_value, get_kavach_key


def test_normalise_phone_cases():
    variants = [
        "+91 98765-43210",
        "+919876543210",
        "098765 43210",
        "09876543210",
        "919876543210",
        "98765-43210",
        "98765 43210",
        "9876543210",
    ]
    for variant in variants:
        assert normalise("phone", variant) == "9876543210"


def test_normalise_email_cases():
    variants = [
        "  User.Test@Example.COM  ",
        "USER.TEST@EXAMPLE.COM",
        "user.test@example.com ",
    ]
    for variant in variants:
        assert normalise("email", variant) == "user.test@example.com"


def test_normalise_aadhaar_cases():
    variants = [
        "1234 5678 9012",
        "1234-5678-9012",
        " 123456789012 ",
    ]
    for variant in variants:
        assert normalise("aadhaar", variant) == "123456789012"


def test_same_phone_different_formats_gives_same_hmac():
    key = b"test_secret_key_32_bytes_abcdef!"
    h1 = hmac_value("phone", "+91 98765-43210", key=key)
    h2 = hmac_value("phone", "098765 43210", key=key)
    h3 = hmac_value("phone", "9876543210", key=key)
    assert h1 == h2 == h3
    assert len(h1) == 64


def test_different_key_gives_different_hmac():
    key1 = b"test_key_1_111111111111111111111"
    key2 = b"test_key_2_222222222222222222222"
    val = "9876543210"
    h1 = hmac_value("phone", val, key=key1)
    h2 = hmac_value("phone", val, key=key2)
    assert h1 != h2


def test_mask_format_preserving():
    assert mask("phone", "9876543210") == "XXXXXX3210"
    assert mask("email", "john.doe@example.com") == "j***e@e***.com"
    assert mask("aadhaar", "123456789012") == "XXXX-XXXX-9012"
    assert mask("pan", "ABCDE1234F") == "ABXXXXX34F"
    masked_name = mask("name", "Rahul Sharma")
    assert "Rahul" not in masked_name and "Sharma" not in masked_name


def test_get_or_create_key_env_and_file():
    # Test env var override
    custom_hex = secrets.token_hex(32)
    os.environ["KAVACH_KEY"] = custom_hex
    try:
        retrieved = get_kavach_key()
        assert retrieved == bytes.fromhex(custom_hex)
    finally:
        del os.environ["KAVACH_KEY"]

    # Test file-based generation in temporary data directory
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["KAVACH_DATA_DIR"] = tmp_dir
        try:
            key1 = get_kavach_key()
            assert len(key1) == 32
            key_file = os.path.join(tmp_dir, ".key")
            assert os.path.exists(key_file)

            # Re-read should return identical key
            key2 = get_kavach_key()
            assert key1 == key2
        finally:
            del os.environ["KAVACH_DATA_DIR"]
