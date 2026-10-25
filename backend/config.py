from typing import Optional
from urllib.parse import urlparse
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./privacy_assistant.db"
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
