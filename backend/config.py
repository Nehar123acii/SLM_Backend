import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    kavach_data_dir: str = "data"
    database_url: str = ""
    upload_temp_dir: str = "./uploads_temp"
    max_upload_rows: int = 50_000
    max_upload_columns: int = 200
    ai_mode: str = "mock"  # "mock" | "live"
    ai_live_url: str = "http://localhost:11434"
    log_level: str = "INFO"

    # Local OCR and Scanned Document Ingestion settings
    tesseract_cmd: Optional[str] = None
    tessdata_dir: Optional[str] = None
    ocr_default_language: str = "eng"
    ocr_max_file_size_bytes: int = 25 * 1024 * 1024  # 25 MB
    ocr_max_pages: int = 100
    ocr_timeout_seconds: float = 30.0
    ocr_min_native_text_chars: int = 50
    ocr_min_native_words: int = 5

    # Statutory DPDP constants
    response_days: int = 30
    breach_stage_2_hours: int = 72

    # Operational Retention & Purge settings (Kavach-configurable, not statutory)
    kavach_retention_days: int = 15
    kavach_dev: int = 0

    def model_post_init(self, __context: object) -> None:
        if "KAVACH_DATA_DIR" in os.environ:
            self.kavach_data_dir = os.environ["KAVACH_DATA_DIR"]
        os.makedirs(self.kavach_data_dir, exist_ok=True)
        if not self.database_url:
            db_file = (Path(self.kavach_data_dir) / "kavach.db").as_posix()
            self.database_url = f"sqlite:///{db_file}"

    @field_validator("database_url")
    @classmethod
    def validate_sqlite_only(cls, value: str) -> str:
        if value and not value.startswith("sqlite"):
            raise ValueError(f"SQLite is the only allowed database. Provided: {value}")
        return value

    @field_validator("ai_live_url")
    @classmethod
    def validate_local_only_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        hostname = (parsed.hostname or "").lower()
        allowed = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}
        if hostname not in allowed:
            raise ValueError(
                f"Cloud or non-local host '{hostname}' is forbidden. "
                "Ollama must run locally."
            )
        return value.rstrip("/")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

# Statutory DPDP constants
# UNVERIFIED, shown as "verify" in the UI
RESPONSE_DAYS: int = 30

# Statutory breach notification timeline constants under DPDP
# The first Board intimation is "without delay": no number
BREACH_STAGE_1_DESCRIPTION: str = "without delay"
BREACH_STAGE_2_HOURS: int = 72

# Kavach operational retention setting (not statutory / not legal mandate)
KAVACH_RETENTION_DAYS: int = int(os.environ.get("KAVACH_RETENTION_DAYS", "15"))


def is_kavach_dev() -> bool:
    """Returns True if developer mode is enabled via KAVACH_DEV env or setting."""
    val = os.environ.get("KAVACH_DEV", "")
    if val.lower() in ("1", "true", "yes", "on"):
        return True
    return bool(getattr(settings, "kavach_dev", 0))
