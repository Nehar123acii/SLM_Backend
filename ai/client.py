"""Local Ollama HTTP client wrapper with bounded retries and schema validation.

Connects strictly to the local Ollama instance (`/api/generate` with `format="json"`).
Never logs raw personal data, prompts, spreadsheet rows, or tokens.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

from ai.config import AIConfig
from ai.models import ContractErrorDetail, ErrorCode, TaskName
from ai.safety import contains_forbidden_action_output, get_safe_logger, log_safe_event


class OllamaClientError(Exception):
    """Structured exception raised when local SLM inference fails after bounded retries."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        retryable: bool,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def to_contract_error(self) -> ContractErrorDetail:
        return ContractErrorDetail(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            details=self.details,
        )


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Extract and parse a JSON object from raw SLM output."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end >= start:
        cleaned = cleaned[start : end + 1]

    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Model JSON output must be a top-level JSON object.")
    return parsed


class OllamaClient:
    """Stateless local-only Ollama client with bounded retries and validation."""

    def __init__(
        self,
        config: Optional[AIConfig] = None,
        transport: Optional[Callable[[str, Dict[str, Any], float], str]] = None,
    ) -> None:
        self.config = config or AIConfig()
        self._transport = transport or self._default_http_post
        self._logger = get_safe_logger("ai.client")

    def _default_http_post(
        self, url: str, payload: Dict[str, Any], timeout: float
    ) -> str:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")

    def generate_validated_json(
        self,
        *,
        request_id: str,
        task: TaskName,
        system_prompt: str,
        user_prompt: str,
        response_validator: Callable[[Dict[str, Any]], Tuple[bool, Optional[str]]],
    ) -> Dict[str, Any]:
        """Invoke local Ollama with bounded retries until response_validator succeeds."""
        total_chars = len(system_prompt) + len(user_prompt)
        if total_chars > self.config.max_context_chars:
            log_safe_event(
                self._logger,
                logging.WARNING,
                "context_length_exceeded",
                request_id=request_id,
                task=task,
                status="error",
                error_code="CONTEXT_LENGTH_EXCEEDED",
            )
            raise OllamaClientError(
                code="CONTEXT_LENGTH_EXCEEDED",
                message="Input payload exceeds the configured SLM context window.",
                retryable=False,
                details={"failed_stage": "input_check"},
            )

        endpoint = f"{self.config.ollama_base_url}/api/generate"
        max_attempts = 1 + self.config.max_retries
        last_error: Optional[OllamaClientError] = None

        for attempt in range(1, max_attempts + 1):
            start_ts = time.perf_counter()
            payload = {
                "model": self.config.model_name,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": self.config.temperature,
                },
            }
            try:
                raw_http = self._transport(
                    endpoint, payload, self.config.timeout_seconds
                )
                envelope = json.loads(raw_http)
                model_text = envelope.get("response", "")
                if not isinstance(model_text, str) or not model_text.strip():
                    raise ValueError("Empty 'response' field from local Ollama server.")

                safety_issue = contains_forbidden_action_output(model_text)
                if safety_issue:
                    raise OllamaClientError(
                        code="SAFETY_POLICY_BLOCKED",
                        message=safety_issue,
                        retryable=False,
                        details={"failed_stage": "output_safety_filter"},
                    )

                parsed_json = _extract_json_object(model_text)
                is_valid, invalid_reason = response_validator(parsed_json)
                if not is_valid:
                    raise OllamaClientError(
                        code="MODEL_OUTPUT_INVALID",
                        message=(
                            f"SLM output failed JSON schema validation after {attempt} "
                            f"attempt(s)."
                        ),
                        retryable=True,
                        details={
                            "failed_stage": "response_validation",
                            "reason": invalid_reason or "Schema validation failed.",
                        },
                    )

                latency_ms = int((time.perf_counter() - start_ts) * 1000)
                log_safe_event(
                    self._logger,
                    logging.INFO,
                    "ollama_inference_ok",
                    request_id=request_id,
                    task=task,
                    status="ok",
                    attempt=attempt,
                    latency_ms=latency_ms,
                )
                return parsed_json

            except OllamaClientError as err:
                last_error = err
                log_safe_event(
                    self._logger,
                    logging.WARNING,
                    "ollama_inference_failed",
                    request_id=request_id,
                    task=task,
                    status="error",
                    attempt=attempt,
                    error_code=err.code,
                )
                if not err.retryable or attempt >= max_attempts:
                    raise
            except (socket.timeout, TimeoutError) as exc:
                last_error = OllamaClientError(
                    code="INFERENCE_TIMEOUT",
                    message="Local SLM inference exceeded the configured timeout threshold.",
                    retryable=True,
                    details={"failed_stage": "ollama_http", "attempt": attempt},
                )
                log_safe_event(
                    self._logger,
                    logging.WARNING,
                    "ollama_timeout",
                    request_id=request_id,
                    task=task,
                    status="error",
                    attempt=attempt,
                    error_code="INFERENCE_TIMEOUT",
                )
                if attempt >= max_attempts:
                    raise last_error from exc
            except urllib.error.URLError as exc:
                if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                    last_error = OllamaClientError(
                        code="INFERENCE_TIMEOUT",
                        message="Local SLM inference exceeded the configured timeout threshold.",
                        retryable=True,
                        details={"failed_stage": "ollama_http", "attempt": attempt},
                    )
                else:
                    last_error = OllamaClientError(
                        code="MODEL_UNAVAILABLE",
                        message="Local Ollama server is unreachable or model is not loaded.",
                        retryable=True,
                        details={"failed_stage": "ollama_http", "attempt": attempt},
                    )
                log_safe_event(
                    self._logger,
                    logging.WARNING,
                    "ollama_unavailable",
                    request_id=request_id,
                    task=task,
                    status="error",
                    attempt=attempt,
                    error_code=last_error.code,
                )
                if attempt >= max_attempts:
                    raise last_error from exc
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                last_error = OllamaClientError(
                    code="MODEL_OUTPUT_INVALID",
                    message=(
                        f"SLM output failed JSON parsing/validation after {attempt} attempt(s)."
                    ),
                    retryable=True,
                    details={
                        "failed_stage": "json_parse",
                        "reason": type(exc).__name__,
                    },
                )
                log_safe_event(
                    self._logger,
                    logging.WARNING,
                    "ollama_output_invalid",
                    request_id=request_id,
                    task=task,
                    status="error",
                    attempt=attempt,
                    error_code="MODEL_OUTPUT_INVALID",
                )
                if attempt >= max_attempts:
                    raise last_error from exc

        assert last_error is not None
        raise last_error
