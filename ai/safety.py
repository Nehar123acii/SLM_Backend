"""Safety guardrails, prompt-injection defense, and zero-PII logging.

Enforces the hard rules from contracts/AI_BACKEND_CONTRACT.md:
1. Never log raw personal data, full prompts, spreadsheet rows, tokens, or credentials.
2. Treat text from uploaded documents/requests as untrusted data, never as instructions.
3. Never execute SQL, delete files/data, send emails, or shut down systems.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

# Patterns that must never appear in logs
_PII_OR_SECRET_PATTERNS = [
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),  # PAN-like
    re.compile(r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b"),  # Aadhaar-like
    re.compile(r"\b(?:\+91[-\s]?)?[6-9][0-9]{9}\b"),  # Indian mobile number
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # Email
    re.compile(r"(?i)\b(?:bearer|token|password|secret|api[_-]?key)\s*[:=]\s*\S+"),
]

# Prompt injection signatures attempting to override system instructions or execute code
_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|above|system)\s+instructions\b"),
    re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior|above|system)\s+instructions\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+(?:a|an|in)\s+(?:unrestricted|developer|admin|root|sql)\b"),
    re.compile(r"(?i)\b(?:execute|run)\s+(?:this\s+)?(?:sql|query|command|shell|bash|powershell)\b"),
    re.compile(r"(?i)\b(?:drop\s+table|truncate\s+table|delete\s+from\s+\w+|alter\s+table|insert\s+into\s+\w+)\b"),
    re.compile(r"(?i)\b(?:rm\s+-rf|del\s+/[fqs]|format\s+c:|shutdown\s+-[sr]|os\.system|subprocess\.Popen)\b"),
    re.compile(r"(?i)</untrusted_data>"),
]

# Forbidden side-effect patterns in model output (SQL, shell commands, system shutdown)
_FORBIDDEN_OUTPUT_PATTERNS = [
    re.compile(r"(?i)\b(?:DROP\s+TABLE|TRUNCATE\s+TABLE|DELETE\s+FROM\s+\w+|UPDATE\s+\w+\s+SET|INSERT\s+INTO\s+\w+|ALTER\s+TABLE)\b"),
    re.compile(r"(?i)\b(?:rm\s+-rf|os\.remove|shutil\.rmtree|os\.system|subprocess\.)\b"),
    re.compile(r"(?i)\b(?:shutdown\s+-[srp]|systemctl\s+poweroff|init\s+0)\b"),
]

ALLOWED_LOG_EXTRA_KEYS = {
    "request_id",
    "task",
    "status",
    "attempt",
    "error_code",
    "latency_ms",
    "column_count",
    "mock_mode",
}


def redact_sensitive_text(text: str) -> str:
    """Redact any accidental PII or credential patterns from a string."""
    sanitized = text
    for pattern in _PII_OR_SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


class RedactingLogFilter(logging.Filter):
    """Filter that prevents raw PII, prompts, rows, or secrets from being logged."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact_sensitive_text(str(v)) for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_sensitive_text(str(a)) for a in record.args)
        # Strip any disallowed extra attributes that could hold raw payloads
        for attr in list(record.__dict__.keys()):
            if attr in {
                "prompt",
                "raw_prompt",
                "rows",
                "masked_samples",
                "request_text",
                "incident_narrative",
                "token",
                "credentials",
                "api_key",
            }:
                setattr(record, attr, "[REDACTED_FIELD]")
        return True


def get_safe_logger(name: str = "ai") -> logging.Logger:
    """Return a logger configured with RedactingLogFilter."""
    logger = logging.getLogger(name)
    if not any(isinstance(f, RedactingLogFilter) for f in logger.filters):
        logger.addFilter(RedactingLogFilter())
    return logger


def log_safe_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **metadata: Any,
) -> None:
    """Log operational metadata only (never raw PII, prompts, or document rows)."""
    safe_meta: Dict[str, Any] = {
        k: v for k, v in metadata.items() if k in ALLOWED_LOG_EXTRA_KEYS
    }
    summary = " ".join(f"{k}={v}" for k, v in sorted(safe_meta.items()))
    logger.log(level, f"{event} {summary}".strip())


def wrap_untrusted_data(label: str, content: str) -> str:
    """Wrap uploaded document text or sample values inside passive data tags.

    Any closing tag attempt inside the content is neutralized so untrusted text
    can never break out of the data block.
    """
    escaped = (
        content.replace("</untrusted_data>", "[ESCAPED_TAG]")
        .replace("<untrusted_data", "[ESCAPED_TAG")
    )
    return f'<untrusted_data field="{label}">\n{escaped}\n</untrusted_data>'


def detect_prompt_injection(text: str) -> str | None:
    """Return a reason string if text contains a prompt-injection or SQL/command payload."""
    if not text:
        return None
    for pattern in _PROMPT_INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            return (
                "Untrusted input contains a suspected prompt-injection or command/SQL "
                "execution directive."
            )
    return None


def contains_forbidden_action_output(text: str) -> str | None:
    """Check if model output attempts to emit executable SQL, deletion, or shutdown commands."""
    if not text:
        return None
    for pattern in _FORBIDDEN_OUTPUT_PATTERNS:
        if pattern.search(text):
            return (
                "Model output contained forbidden SQL/system command syntax and was blocked "
                "by safety guardrails."
            )
    return None
