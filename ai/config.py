"""Configuration for the local-first AI / SLM module.

All inference runs strictly against a local Ollama server or in deterministic
mock mode. Cloud AI endpoints are explicitly rejected.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse
from pydantic import BaseModel, Field, field_validator

ALLOWED_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}
SUPPORTED_LANGUAGES = {"en", "hi", "kn"}


class AIConfig(BaseModel):
    """Runtime settings for the AI/SLM module."""

    ollama_base_url: str = Field(
        default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    )
    model_name: str = Field(
        default_factory=lambda: os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    )
    mock_mode: bool = Field(
        default_factory=lambda: os.environ.get("AI_MOCK_MODE", "false").strip().lower()
        in {"1", "true", "yes", "mock"}
    )
    timeout_seconds: float = Field(
        default_factory=lambda: float(os.environ.get("AI_TIMEOUT_SECONDS", "15.0")),
        ge=1.0,
        le=120.0,
    )
    max_retries: int = Field(
        default_factory=lambda: int(os.environ.get("AI_MAX_RETRIES", "2")),
        ge=0,
        le=5,
    )
    temperature: float = Field(
        default_factory=lambda: float(os.environ.get("AI_TEMPERATURE", "0.0")),
        ge=0.0,
        le=1.0,
    )
    max_context_chars: int = Field(
        default_factory=lambda: int(os.environ.get("AI_MAX_CONTEXT_CHARS", "16000")),
        ge=512,
        le=64000,
    )
    default_language: str = Field(
        default_factory=lambda: os.environ.get("AI_DEFAULT_LANGUAGE", "en").strip().lower()
    )
    fallback_on_model_error: bool = Field(
        default_factory=lambda: os.environ.get("AI_FALLBACK_ON_ERROR", "true").strip().lower()
        in {"1", "true", "yes"}
    )

    @field_validator("ollama_base_url")
    @classmethod
    def validate_local_only_url(cls, value: str) -> str:
        """Enforce local-only Ollama inference; block external/cloud URLs."""
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("ollama_base_url must use http or https scheme.")
        hostname = (parsed.hostname or "").lower()
        if hostname not in ALLOWED_LOCAL_HOSTS:
            raise ValueError(
                f"Cloud or non-local host '{hostname}' is forbidden. "
                f"Ollama must run locally on one of: {sorted(ALLOWED_LOCAL_HOSTS)}."
            )
        return value.rstrip("/")

    @field_validator("default_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        lang = value.strip().lower()
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{value}'. Permitted values: {sorted(SUPPORTED_LANGUAGES)}."
            )
        return lang
