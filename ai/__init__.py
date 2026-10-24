"""Local-first AI / SLM compliance module for small businesses in India.

Exposes the four contract-compliant AI functions:
1. classify_columns
2. contextual_privacy_findings
3. classify_privacy_request
4. extract_breach_details
"""

from ai.breach_extractor import extract_breach_details
from ai.classifier import classify_columns
from ai.client import OllamaClient, OllamaClientError
from ai.config import AIConfig
from ai.findings import contextual_privacy_findings
from ai.models import (
    AIErrorResponse,
    BreachAssessment,
    ClassifiedColumnSummary,
    ClassifyColumnsRequest,
    ClassifyColumnsResponse,
    ClassifyPrivacyRequestInput,
    ClassifyPrivacyRequestResponse,
    ColumnClassificationResult,
    ColumnInput,
    ContextualPrivacyFindingsRequest,
    ContextualPrivacyFindingsResponse,
    ContractErrorDetail,
    DatasetContext,
    DatasetMetadata,
    DraftNotifications,
    ExtractBreachDetailsRequest,
    ExtractBreachDetailsResponse,
    ExtractedBreachDetails,
    PrivacyFinding,
    VersionDiffSummary,
)
from ai.requests_classifier import classify_privacy_request

__all__ = [
    "AIConfig",
    "OllamaClient",
    "OllamaClientError",
    "ContractErrorDetail",
    "AIErrorResponse",
    "DatasetContext",
    "ColumnInput",
    "ClassifyColumnsRequest",
    "ColumnClassificationResult",
    "ClassifyColumnsResponse",
    "DatasetMetadata",
    "ClassifiedColumnSummary",
    "VersionDiffSummary",
    "ContextualPrivacyFindingsRequest",
    "PrivacyFinding",
    "ContextualPrivacyFindingsResponse",
    "ClassifyPrivacyRequestInput",
    "ClassifyPrivacyRequestResponse",
    "ExtractBreachDetailsRequest",
    "ExtractedBreachDetails",
    "BreachAssessment",
    "DraftNotifications",
    "ExtractBreachDetailsResponse",
    "classify_columns",
    "contextual_privacy_findings",
    "classify_privacy_request",
    "extract_breach_details",
]
