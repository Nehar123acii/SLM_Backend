from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


# -------------------------------------------------------------
# Common Config
# -------------------------------------------------------------
class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -------------------------------------------------------------
# Inventory & ETL Schemas
# -------------------------------------------------------------
class ColumnResponse(ORMBase):
    column_name: str
    original_name: Optional[str] = None
    inferred_type: str
    locator: Optional[str] = None
    category: Optional[str] = None
    impact_tier: Optional[str] = None
    ai_category: Optional[str] = None
    ai_sensitivity: Optional[str] = None
    ai_confidence: Optional[float] = None
    ai_explanation: Optional[str] = None
    dpdp_basis: Optional[str] = None
    identifier_flags: Optional[Union[List[str], str]] = None
    purpose: Optional[str] = None
    purpose_status: Optional[str] = None


class ETLIssueResponse(ORMBase):
    issue_type: str
    column_name: Optional[str] = None
    row_index: Optional[int] = None
    detail: str


class IdentifierFindingResponse(ORMBase):
    column_name: str
    pattern_type: str
    match_count: int
    caveat: str


class DatasetUploadResponse(BaseModel):
    dataset_id: str
    version: int
    filename: str
    source_type: Optional[str] = "csv"
    sheet_name: Optional[str] = None
    row_count: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    etl_issues: List[ETLIssueResponse]
    identifier_findings: List[IdentifierFindingResponse]
    columns: List[ColumnResponse]
    ai_result: Optional[Dict[str, Any]] = None
    eda_summary: Optional[Dict[str, Any]] = None
    status: str


class DatasetListItemResponse(ORMBase):
    id: int
    dataset_id: str
    original_filename: str
    source_type: Optional[str] = "csv"
    sheet_name: Optional[str] = None
    version: int
    status: str
    row_count: int
    accepted_count: int
    upload_timestamp: datetime


class DatasetDetailResponse(ORMBase):
    id: int
    dataset_id: str
    original_filename: str
    source_type: Optional[str] = "csv"
    sheet_name: Optional[str] = None
    version: int
    row_count: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    upload_timestamp: datetime
    status: str
    temp_file_path: Optional[str] = None
    columns: List[ColumnResponse] = []
    etl_issues: List[ETLIssueResponse] = []
    identifier_findings: List[IdentifierFindingResponse] = []
    eda_summary: Optional[Any] = None


class VersionDiffResponse(ORMBase):
    dataset_id: str
    previous_dataset_id: Optional[str] = None
    added_count: int
    changed_count: int
    removed_count: int
    unchanged_count: int
    diff_json: Any
    created_at: datetime


class SupportedSourceResponse(BaseModel):
    source_type: str
    label: str
    file_extensions: List[str]
    description: str
    options: List[str]


class ConsolidatedInventoryResponse(BaseModel):
    total_sources: int
    total_columns: int
    total_records: int
    sources: List[Dict[str, Any]]
    columns: List[Dict[str, Any]]
    category_coverage_matrix: Dict[str, List[str]]
    cross_source_matches: List[Dict[str, Any]]


class AuditLogResponse(ORMBase):
    id: int
    timestamp: datetime
    action: str
    entity_type: str
    entity_id: str
    actor: str
    details: Optional[str] = None


class PrivacyAnalysisResponse(BaseModel):
    smart_personal_data_mapper: Dict[str, Any]
    privacy_leak_detector: Dict[str, Any]
    privacy_requests_summary: Dict[str, Any]
    breach_assistant_summary: Dict[str, Any]


# -------------------------------------------------------------
# Privacy Request Schemas
# -------------------------------------------------------------
class PrivacyRequestCreate(BaseModel):
    raw_text: str = Field(..., max_length=5000)
    submission_channel: str = Field("web_form", pattern="^(web_form|email|walk_in|other)$")


class PrivacyRequestResponse(ORMBase):
    request_id: str
    submission_channel: str
    request_types: Any
    is_composite: bool
    urgency: str
    status: str
    needs_human_review: bool
    ai_confidence: Optional[float] = None
    subject_reference: Optional[str] = None
    data_scope_hint: Optional[str] = None
    suggested_response_outline: Optional[str] = None
    ambiguities: Optional[Any] = None
    checklist: Optional[Any] = None
    sla_deadline: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class PrivacyRequestStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(RECEIVED|PENDING_REVIEW|IN_PROGRESS|FULFILLED|REJECTED|WITHDRAWN)$")


class PrivacyRequestChecklistUpdate(BaseModel):
    checklist: List[Any]


# -------------------------------------------------------------
# Incident Schemas
# -------------------------------------------------------------
class IncidentCreate(BaseModel):
    report_text: str = Field(..., max_length=10000)
    reporter_role: Optional[str] = Field(None, max_length=128)
    discovery_datetime_hint: Optional[str] = None


class IncidentResponse(ORMBase):
    incident_ref: str
    reporter_role: Optional[str] = None
    incident_type: str
    discovery_datetime_hint: Optional[str] = None
    affected_data_categories: Any
    estimated_affected_count: Optional[int] = None
    count_confidence: str
    potential_harm: Any
    containment_steps: Any
    notification_likely_required: bool
    notification_reasoning: Optional[str] = None
    draft_summary: Optional[str] = None
    open_questions: Optional[Any] = None
    status: str
    needs_human_review: bool
    checklist: Any
    evidence_refs: Any
    created_at: datetime
    updated_at: datetime


class IncidentStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(DRAFT|UNDER_REVIEW|CONTAINED|NOTIFIED|CLOSED)$")


class IncidentChecklistUpdate(BaseModel):
    checklist: List[Any]


class IncidentEvidenceCreate(BaseModel):
    evidence_ref: str = Field(..., min_length=1, max_length=512)
