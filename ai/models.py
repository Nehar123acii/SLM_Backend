"""Pydantic schemas matching contracts/AI_BACKEND_CONTRACT.md (v1.0)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Enumerated / Literal Types from contracts/AI_BACKEND_CONTRACT.md
# ---------------------------------------------------------------------------

TaskName = Literal[
    "classify_columns",
    "contextual_privacy_findings",
    "classify_privacy_request",
    "extract_breach_details",
]

ErrorCode = Literal[
    "INVALID_INPUT",
    "MODEL_UNAVAILABLE",
    "INFERENCE_TIMEOUT",
    "CONTEXT_LENGTH_EXCEEDED",
    "MODEL_OUTPUT_INVALID",
    "SAFETY_POLICY_BLOCKED",
    "INTERNAL_AI_ERROR",
]

SupportedLanguage = Literal["en", "hi", "kn"]

InferredDataType = Literal[
    "string",
    "integer",
    "float",
    "boolean",
    "date",
    "datetime",
    "json",
    "unknown",
]

DeterministicSignal = Literal[
    "AADHAAR_PATTERN",
    "PAN_PATTERN",
    "GSTIN_PATTERN",
    "INDIAN_PHONE_PATTERN",
    "EMAIL_PATTERN",
    "PINCODE_PATTERN",
    "IFSC_PATTERN",
    "UPI_ID_PATTERN",
    "DOB_PATTERN",
    "IPV4_PATTERN",
    "NONE",
]

DataCategory = Literal[
    "GOVERNMENT_ID",
    "CONTACT_INFO",
    "IDENTITY_DEMOGRAPHIC",
    "FINANCIAL_DATA",
    "HEALTH_MEDICAL",
    "CHILDREN_DATA",
    "BIOMETRIC_GENETIC",
    "AUTHENTICATION_SECRET",
    "BEHAVIORAL_LOCATION",
    "BUSINESS_NON_PERSONAL",
    "UNKNOWN_AMBIGUOUS",
]

SpecificIdentifierType = Literal[
    "AADHAAR",
    "PAN",
    "PASSPORT",
    "VOTER_ID",
    "DRIVING_LICENCE",
    "GSTIN",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "POSTAL_ADDRESS",
    "PINCODE",
    "PERSON_NAME",
    "DATE_OF_BIRTH",
    "GENDER",
    "BANK_ACCOUNT",
    "IFSC_CODE",
    "UPI_ID",
    "PAYMENT_CARD",
    "MEDICAL_RECORD",
    "MINOR_INDICATOR",
    "AUTH_CREDENTIAL",
    "IP_ADDRESS",
    "OTHER_PERSONAL",
    "NON_PERSONAL",
    "UNKNOWN",
]

SensitivityTier = Literal[
    "CRITICAL_PERSONAL",
    "SENSITIVE_PERSONAL",
    "GENERAL_PERSONAL",
    "NON_PERSONAL",
    "UNKNOWN",
]

AccessScope = Literal[
    "PUBLIC_LINK",
    "ALL_STAFF",
    "ROLE_RESTRICTED",
    "ENCRYPTED_RESTRICTED",
    "UNKNOWN",
]

RiskSeverity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

FindingType = Literal[
    "OVER_COLLECTION",
    "MISSING_CONSENT_BASIS",
    "EXCESSIVE_ACCESS",
    "MISSING_RETENTION_POLICY",
    "UNSAFE_COMBINATION",
    "CHILDREN_DATA_SAFEGUARD_REQUIRED",
    "THIRD_PARTY_SHARING_RISK",
    "VERSION_DRIFT_ESCALATION",
]

RequestChannel = Literal[
    "EMAIL",
    "WEBFORM",
    "WHATSAPP_SUPPORT",
    "IN_PERSON",
    "GRIEVANCE_PORTAL",
    "OTHER",
]

RequesterRoleHint = Literal[
    "CUSTOMER",
    "EMPLOYEE",
    "PARENT_GUARDIAN",
    "NOMINEE",
    "UNKNOWN",
]

PrimaryRequestType = Literal[
    "ACCESS_SUMMARY",
    "THIRD_PARTY_SHARING_LIST",
    "CORRECTION_COMPLETION_UPDATING",
    "ERASURE",
    "CONSENT_WITHDRAWAL",
    "GRIEVANCE_REDRESSAL",
    "NOMINATION",
    "MULTI_INTENT",
    "NON_PRIVACY_SUPPORT",
    "AMBIGUOUS",
]

SpecificRightSubType = Literal[
    "ACCESS_SUMMARY",
    "THIRD_PARTY_SHARING_LIST",
    "CORRECTION_COMPLETION_UPDATING",
    "ERASURE",
    "CONSENT_WITHDRAWAL",
    "GRIEVANCE_REDRESSAL",
    "NOMINATION",
]

RequestUrgency = Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]

VerificationStatusAdvice = Literal[
    "VERIFIED_READY",
    "REQUIRES_STANDARD_VERIFICATION",
    "REQUIRES_GUARDIAN_OR_NOMINEE_PROOF",
]

BreachType = Literal[
    "UNAUTHORIZED_ACCESS",
    "ACCIDENTAL_DISCLOSURE",
    "RANSOMWARE_MALWARE",
    "LOST_OR_STOLEN_DEVICE",
    "VENDOR_THIRD_PARTY_BREACH",
    "PHYSICAL_BREACH",
    "UNKNOWN",
]

# ---------------------------------------------------------------------------
# Common Error Envelope (Section 3.2 of AI_BACKEND_CONTRACT.md)
# ---------------------------------------------------------------------------


class ContractErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool
    details: Dict[str, Any] = Field(default_factory=dict)


class AIErrorResponse(BaseModel):
    """Standard contract error envelope. Always enforces needs_human_review=True."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    task: TaskName
    status: Literal["error"] = "error"
    error: ContractErrorDetail
    needs_human_review: Literal[True] = True
    review_reasons: List[str] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Task 1: classify_columns (Section 4, Task 1 of AI_BACKEND_CONTRACT.md)
# ---------------------------------------------------------------------------


class DatasetContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    business_domain: str = Field(min_length=1)


class ColumnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_name: str = Field(min_length=1)
    inferred_data_type: InferredDataType
    null_ratio: float = Field(ge=0.0, le=1.0)
    deterministic_signals: List[DeterministicSignal] = Field(default_factory=list)
    masked_samples: List[str] = Field(default_factory=list, max_length=5)


class ClassifyColumnsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    task: Literal["classify_columns"] = "classify_columns"
    dataset_context: DatasetContext
    columns: List[ColumnInput] = Field(min_length=1)
    language: SupportedLanguage = "en"


class ColumnClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_name: str = Field(min_length=1)
    contains_personal_data: bool
    data_category: DataCategory
    specific_identifier_type: SpecificIdentifierType
    sensitivity_tier: SensitivityTier
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=1)
    needs_human_review: bool
    review_reasons: List[str] = Field(default_factory=list)


class ClassifyColumnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    task: Literal["classify_columns"] = "classify_columns"
    status: Literal["ok", "error"] = "ok"
    needs_human_review: bool
    review_reasons: List[str] = Field(default_factory=list)
    results: List[ColumnClassificationResult] = Field(default_factory=list)
    error: Optional[ContractErrorDetail] = None

    @model_validator(mode="after")
    def enforce_contract_invariants(self) -> "ClassifyColumnsResponse":
        if self.status == "error":
            self.needs_human_review = True
            if not self.review_reasons:
                self.review_reasons = ["AI inference returned error status; manual review required."]
        elif any(r.needs_human_review for r in self.results):
            self.needs_human_review = True
        return self


# ---------------------------------------------------------------------------
# Task 2: contextual_privacy_findings (Section 4, Task 2)
# ---------------------------------------------------------------------------


class DatasetMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    business_purpose: str = Field(min_length=1)
    stated_retention_days: Optional[int] = None
    has_consent_notice_linked: bool
    access_scope: AccessScope
    third_party_sharing: bool


class ClassifiedColumnSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_name: str = Field(min_length=1)
    data_category: DataCategory
    specific_identifier_type: SpecificIdentifierType
    sensitivity_tier: SensitivityTier


class VersionDiffSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    added_columns: List[str] = Field(default_factory=list)
    removed_columns: List[str] = Field(default_factory=list)
    tier_escalations: List[str] = Field(default_factory=list)


class ContextualPrivacyFindingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    task: Literal["contextual_privacy_findings"] = "contextual_privacy_findings"
    dataset_metadata: DatasetMetadata
    classified_columns: List[ClassifiedColumnSummary] = Field(min_length=1)
    version_diff_summary: Optional[VersionDiffSummary] = None
    language: SupportedLanguage = "en"


class PrivacyFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_type: FindingType
    severity: RiskSeverity
    dpdp_reference: str = Field(min_length=1)
    affected_columns: List[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1)
    recommended_remediation: str = Field(min_length=1)


class ContextualPrivacyFindingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    task: Literal["contextual_privacy_findings"] = "contextual_privacy_findings"
    status: Literal["ok", "error"] = "ok"
    overall_risk_level: RiskSeverity = "LOW"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_human_review: bool
    review_reasons: List[str] = Field(default_factory=list)
    findings: List[PrivacyFinding] = Field(default_factory=list)
    error: Optional[ContractErrorDetail] = None

    @model_validator(mode="after")
    def enforce_contract_invariants(self) -> "ContextualPrivacyFindingsResponse":
        if self.status == "error":
            self.needs_human_review = True
        if self.overall_risk_level in {"HIGH", "CRITICAL"}:
            self.needs_human_review = True
        if any(f.severity == "CRITICAL" for f in self.findings):
            self.needs_human_review = True
        if self.confidence < 0.75:
            self.needs_human_review = True
        return self


# ---------------------------------------------------------------------------
# Task 3: classify_privacy_request (Section 4, Task 3)
# ---------------------------------------------------------------------------


class ClassifyPrivacyRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    task: Literal["classify_privacy_request"] = "classify_privacy_request"
    case_id: str = Field(min_length=1)
    channel: RequestChannel
    received_at: str = Field(min_length=1)
    requester_role_hint: RequesterRoleHint
    identity_verified_by_backend: bool
    request_text: str = Field(min_length=1)
    language: SupportedLanguage = "en"


class ClassifyPrivacyRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    task: Literal["classify_privacy_request"] = "classify_privacy_request"
    status: Literal["ok", "error"] = "ok"
    case_id: str = Field(min_length=1)
    primary_request_type: PrimaryRequestType = "AMBIGUOUS"
    detected_sub_types: List[SpecificRightSubType] = Field(default_factory=list)
    urgency: RequestUrgency = "NORMAL"
    verification_status_advice: VerificationStatusAdvice = "REQUIRES_STANDARD_VERIFICATION"
    target_data_categories_mentioned: List[DataCategory] = Field(default_factory=list)
    legal_retention_check_required: bool = False
    explanation: str = Field(min_length=1)
    draft_response_for_staff_review: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human_review: bool = True
    review_reasons: List[str] = Field(default_factory=list)
    error: Optional[ContractErrorDetail] = None

    @model_validator(mode="after")
    def enforce_contract_invariants(self) -> "ClassifyPrivacyRequestResponse":
        actionable_types = {
            "ACCESS_SUMMARY",
            "THIRD_PARTY_SHARING_LIST",
            "CORRECTION_COMPLETION_UPDATING",
            "ERASURE",
            "CONSENT_WITHDRAWAL",
            "GRIEVANCE_REDRESSAL",
            "NOMINATION",
            "MULTI_INTENT",
            "AMBIGUOUS",
        }
        if (
            self.status == "error"
            or self.primary_request_type in actionable_types
            or self.confidence < 0.80
        ):
            self.needs_human_review = True
        return self


# ---------------------------------------------------------------------------
# Task 4: extract_breach_details (Section 4, Task 4)
# ---------------------------------------------------------------------------


class ExtractBreachDetailsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    task: Literal["extract_breach_details"] = "extract_breach_details"
    incident_id: str = Field(min_length=1)
    reported_at: str = Field(min_length=1)
    reporter_role: str = Field(min_length=1)
    incident_narrative: str = Field(min_length=1)
    language: SupportedLanguage = "en"


class ExtractedBreachDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    breach_type: BreachType
    estimated_occurrence_time: Optional[str] = None
    discovery_time: Optional[str] = None
    affected_systems: List[str] = Field(default_factory=list)
    affected_data_categories: List[DataCategory] = Field(default_factory=list)
    affected_data_principals_estimate: Optional[int] = None
    is_ongoing: Optional[bool] = None
    containment_actions_taken: List[str] = Field(default_factory=list)
    missing_critical_facts: List[str] = Field(default_factory=list)


class BreachAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: RiskSeverity
    dpb_notification_likely_required: bool
    cert_in_notification_likely_required: bool
    explanation: str = Field(min_length=1)
    recommended_next_steps: List[str] = Field(default_factory=list)


class DraftNotifications(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_summary_draft: str = Field(min_length=1)
    data_principal_notice_draft: str = Field(min_length=1)


class ExtractBreachDetailsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    task: Literal["extract_breach_details"] = "extract_breach_details"
    status: Literal["ok", "error"] = "ok"
    incident_id: str = Field(min_length=1)
    extracted_details: Optional[ExtractedBreachDetails] = None
    assessment: Optional[BreachAssessment] = None
    draft_notifications: Optional[DraftNotifications] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_human_review: bool = True
    review_reasons: List[str] = Field(default_factory=list)
    error: Optional[ContractErrorDetail] = None

    @model_validator(mode="after")
    def enforce_contract_invariants(self) -> "ExtractBreachDetailsResponse":
        # Rule 1 of Task 4: Always true for all breach extraction outputs
        self.needs_human_review = True
        if not self.review_reasons:
            self.review_reasons = [
                "All breach incident assessments and regulatory notification drafts require mandatory human and legal review."
            ]
        return self
