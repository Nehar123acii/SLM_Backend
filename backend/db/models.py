from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column as SAColumn,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Dataset(Base):
    """
    Datasets table storing uploaded dataset metadata, validation counts, and lifecycle status.
    """
    __tablename__ = "datasets"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    dataset_id = SAColumn(String(64), unique=True, index=True, nullable=False)
    original_filename = SAColumn(String(255), nullable=False)
    source_type = SAColumn(String(32), default="csv", nullable=False)  # csv / excel / google_forms / whatsapp / json
    sheet_name = SAColumn(String(128), nullable=True)
    version = SAColumn(Integer, default=1, nullable=False)
    row_count = SAColumn(Integer, default=0, nullable=False)
    accepted_count = SAColumn(Integer, default=0, nullable=False)
    rejected_count = SAColumn(Integer, default=0, nullable=False)
    duplicate_count = SAColumn(Integer, default=0, nullable=False)
    upload_timestamp = SAColumn(DateTime, default=utc_now, nullable=False)
    status = SAColumn(String(32), default="PENDING", nullable=False)  # PENDING / ETL_COMPLETE / AI_CLASSIFIED / APPROVED / REJECTED
    temp_file_path = SAColumn(String(512), nullable=True)
    eda_summary = SAColumn(Text, nullable=True)  # JSON string of 5-category EDA report
    metadata_json = SAColumn(Text, nullable=True)  # JSON string of source-specific metadata

    columns = relationship("Column", back_populates="dataset", cascade="all, delete-orphan")
    etl_issues = relationship("ETLIssue", back_populates="dataset", cascade="all, delete-orphan")
    identifier_findings = relationship("IdentifierFinding", back_populates="dataset", cascade="all, delete-orphan")
    version_diffs = relationship("VersionDiff", back_populates="dataset", foreign_keys="VersionDiff.dataset_id")


class Column(Base):
    """
    Columns table storing schema definitions, inferred types, and AI classification results.
    """
    __tablename__ = "columns"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    dataset_id = SAColumn(String(64), ForeignKey("datasets.dataset_id"), nullable=False, index=True)
    column_name = SAColumn(String(255), nullable=False)
    original_name = SAColumn(String(255), nullable=True)  # Un-normalized source name
    inferred_type = SAColumn(String(32), nullable=False)
    ai_category = SAColumn(String(64), nullable=True)
    ai_sensitivity = SAColumn(String(64), nullable=True)
    ai_confidence = SAColumn(Float, nullable=True)
    ai_explanation = SAColumn(String(512), nullable=True)
    dpdp_basis = SAColumn(String(255), nullable=True)
    identifier_flags = SAColumn(Text, nullable=True)  # JSON array string
    purpose = SAColumn(String(255), nullable=True)  # Documented business purpose
    purpose_status = SAColumn(String(32), default="AWAITING_REVIEW", nullable=False)  # DOCUMENTED / AWAITING_REVIEW
    locator = SAColumn(String(255), nullable=True)
    category = SAColumn(String(64), nullable=True)
    impact_tier = SAColumn(String(32), nullable=True)

    dataset = relationship("Dataset", back_populates="columns")


class ETLIssue(Base):
    """
    ETL issues table recording validation anomalies (missing, invalid, duplicates).
    Safe descriptions only — never logs raw PII.
    """
    __tablename__ = "etl_issues"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    dataset_id = SAColumn(String(64), ForeignKey("datasets.dataset_id"), nullable=False, index=True)
    issue_type = SAColumn(String(32), nullable=False)  # MISSING / INVALID / DUPLICATE / REJECTED
    column_name = SAColumn(String(255), nullable=True)
    row_index = SAColumn(Integer, nullable=True)  # 0-based row number
    detail = SAColumn(String(512), nullable=False)

    dataset = relationship("Dataset", back_populates="etl_issues")


class IdentifierFinding(Base):
    """
    Identifier findings from deterministic pattern matching (PAN, Email, Phone, etc.).
    """
    __tablename__ = "identifier_findings"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    dataset_id = SAColumn(String(64), ForeignKey("datasets.dataset_id"), nullable=False, index=True)
    column_name = SAColumn(String(255), nullable=False)
    pattern_type = SAColumn(String(64), nullable=False)  # EMAIL / PHONE_IN / PAN / AADHAAR / PINCODE
    match_count = SAColumn(Integer, nullable=False)
    caveat = SAColumn(String(512), nullable=False)

    dataset = relationship("Dataset", back_populates="identifier_findings")


class VersionDiff(Base):
    """
    Version diff table recording row/column change metrics between dataset versions.
    """
    __tablename__ = "version_diffs"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    dataset_id = SAColumn(String(64), ForeignKey("datasets.dataset_id"), nullable=False, index=True)
    previous_dataset_id = SAColumn(String(64), nullable=True)
    added_count = SAColumn(Integer, default=0, nullable=False)
    changed_count = SAColumn(Integer, default=0, nullable=False)
    removed_count = SAColumn(Integer, default=0, nullable=False)
    unchanged_count = SAColumn(Integer, default=0, nullable=False)
    diff_json = SAColumn(Text, nullable=False)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)

    dataset = relationship("Dataset", foreign_keys=[dataset_id], back_populates="version_diffs")


class AuditLog(Base):
    """
    Audit log table for sensitive system events.
    Never stores raw personal data in event details.
    """
    __tablename__ = "audit_logs"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    timestamp = SAColumn(DateTime, default=utc_now, nullable=False)
    action = SAColumn(String(64), nullable=False)
    entity_type = SAColumn(String(64), nullable=False)
    entity_id = SAColumn(String(64), nullable=False)
    actor = SAColumn(String(128), default="system", nullable=False)
    details = SAColumn(Text, nullable=True)  # JSON string without PII


class CrossSourceMatch(Base):
    """
    Potential or confirmed data principal identity link across different data sources.
    Kept UNRESOLVED by default; never automatically equates individuals on names alone.
    """
    __tablename__ = "cross_source_matches"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    source_dataset_id_1 = SAColumn(String(64), ForeignKey("datasets.dataset_id"), nullable=False, index=True)
    source_dataset_id_2 = SAColumn(String(64), ForeignKey("datasets.dataset_id"), nullable=False, index=True)
    match_field = SAColumn(String(128), nullable=False)
    match_type = SAColumn(String(64), default="POTENTIAL_CANDIDATE", nullable=False)  # POTENTIAL_CANDIDATE / EXACT_IDENTIFIER
    status = SAColumn(String(32), default="UNRESOLVED", nullable=False)  # UNRESOLVED / CONFIRMED / DISMISSED
    caveat = SAColumn(String(512), nullable=False)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)


class PrivacyRequest(Base):
    """
    Data principal rights-request workflow case.
    """
    __tablename__ = "privacy_requests"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    request_id = SAColumn(String(64), unique=True, index=True, nullable=False)
    submission_channel = SAColumn(String(32), nullable=False)  # web_form / email / walk_in / other
    raw_text = SAColumn(Text, nullable=False)  # Stored encrypted-at-rest in prod; never log raw PII
    request_types = SAColumn(Text, nullable=False)  # JSON array string
    is_composite = SAColumn(Boolean, default=False, nullable=False)
    urgency = SAColumn(String(16), default="MEDIUM", nullable=False)  # LOW / MEDIUM / HIGH
    status = SAColumn(String(32), default="RECEIVED", nullable=False)  # RECEIVED / PENDING_REVIEW / IN_PROGRESS / FULFILLED / REJECTED / WITHDRAWN
    needs_human_review = SAColumn(Boolean, default=True, nullable=False)
    ai_confidence = SAColumn(Float, nullable=True)
    subject_reference = SAColumn(String(255), nullable=True)  # No raw PII
    data_scope_hint = SAColumn(Text, nullable=True)
    suggested_response_outline = SAColumn(Text, nullable=True)
    ambiguities = SAColumn(Text, nullable=True)  # JSON array string
    checklist = SAColumn(Text, nullable=True)  # JSON array string
    sla_deadline = SAColumn(DateTime, nullable=True)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)
    updated_at = SAColumn(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class Incident(Base):
    """
    Data breach incident record and compliance tracking.
    """
    __tablename__ = "incidents"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    incident_ref = SAColumn(String(64), unique=True, index=True, nullable=False)
    reporter_role = SAColumn(String(128), nullable=True)  # Role only, no personal name
    report_text = SAColumn(Text, nullable=False)
    incident_type = SAColumn(String(64), nullable=False)
    discovery_datetime_hint = SAColumn(String(64), nullable=True)  # ISO 8601 string
    affected_data_categories = SAColumn(Text, nullable=False)  # JSON array string
    estimated_affected_count = SAColumn(Integer, nullable=True)
    count_confidence = SAColumn(String(16), default="UNKNOWN", nullable=False)  # EXACT / ESTIMATE / UNKNOWN
    potential_harm = SAColumn(Text, nullable=False)  # JSON array string
    containment_steps = SAColumn(Text, nullable=False)  # JSON array string
    notification_likely_required = SAColumn(Boolean, default=False, nullable=False)
    notification_reasoning = SAColumn(Text, nullable=True)
    draft_summary = SAColumn(Text, nullable=True)
    open_questions = SAColumn(Text, nullable=True)  # JSON array string
    status = SAColumn(String(32), default="DRAFT", nullable=False)  # DRAFT / UNDER_REVIEW / CONTAINED / NOTIFIED / CLOSED
    needs_human_review = SAColumn(Boolean, default=True, nullable=False)
    checklist = SAColumn(Text, nullable=False)  # JSON array string
    evidence_refs = SAColumn(Text, nullable=False)  # JSON array string
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)
    updated_at = SAColumn(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


# ---------------------------------------------------------------------------
# Part C: Additive Models (Identity, Occurrences, Governance, Ledger)
# ---------------------------------------------------------------------------

class Person(Base):
    """
    Resolved or unresolved individual identity entity.
    """
    __tablename__ = "people"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    resolution = SAColumn(String(64), nullable=False, default="UNRESOLVED")
    confidence = SAColumn(Float, nullable=False, default=1.0)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)

    occurrences = relationship("Occurrence", back_populates="person")


class Occurrence(Base):
    """
    Instance of an identifier occurrence in a source dataset or document.
    Stores only format-preserving masked sample and HMAC hash — never raw values.
    """
    __tablename__ = "occurrences"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    person_id = SAColumn(Integer, ForeignKey("people.id"), nullable=True, index=True)
    column_id = SAColumn(Integer, ForeignKey("columns.id"), nullable=True, index=True)
    row_ref = SAColumn(String(128), nullable=True)
    masked_sample = SAColumn(String(255), nullable=True)
    value_hmac = SAColumn(String(64), nullable=False, index=True)
    origin = SAColumn(String(32), nullable=False, default="rule")  # rule | slm | ocr
    ocr_conf = SAColumn(Float, nullable=True)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)

    person = relationship("Person", back_populates="occurrences")
    column = relationship("Column")


class Purpose(Base):
    """
    Catalog of permitted business processing purposes under DPDP.
    """
    __tablename__ = "purposes"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    label_key = SAColumn(String(128), nullable=False, unique=True, index=True)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)

    purpose_links = relationship("PurposeLink", back_populates="purpose")


class PurposeLink(Base):
    """
    Linkage between a dataset column, data principal segment, and business purpose.
    """
    __tablename__ = "purpose_links"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    column_id = SAColumn(Integer, ForeignKey("columns.id"), nullable=False, index=True)
    segment = SAColumn(String(32), nullable=False)  # patient | customer | staff
    purpose_id = SAColumn(Integer, ForeignKey("purposes.id"), nullable=False, index=True)
    status = SAColumn(String(32), nullable=False, default="inferred")  # confirmed | inferred | unknown
    answered_by = SAColumn(String(128), nullable=True)
    answered_at = SAColumn(DateTime, nullable=True)
    superseded_by = SAColumn(Integer, ForeignKey("purpose_links.id"), nullable=True)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)

    purpose = relationship("Purpose", back_populates="purpose_links")
    column = relationship("Column")


class FlagResult(Base):
    """
    Evaluation output of a compliance check or rule.
    """
    __tablename__ = "flag_results"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    run_id = SAColumn(String(64), nullable=False, index=True)
    rule_id = SAColumn(String(64), nullable=False, index=True)
    state = SAColumn(String(32), nullable=False)  # GREEN | YELLOW | RED | NOT_ASSESSED
    evidence_refs = SAColumn(Text, nullable=True)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)


class LedgerEvent(Base):
    """
    Tamper-evident append-only ledger entry chaining sequential operations.
    """
    __tablename__ = "ledger_events"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    seq = SAColumn(Integer, nullable=False, unique=True, index=True)
    event_type = SAColumn(String(64), nullable=False)
    payload_json = SAColumn(Text, nullable=False)
    prev_hash = SAColumn(String(64), nullable=False)
    hash = SAColumn(String(64), nullable=False)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)


class BusinessState(Base):
    """
    Tracks overall business data activity and heartbeat timestamp.
    """
    __tablename__ = "business_state"

    id = SAColumn(Integer, primary_key=True, autoincrement=True)
    last_activity = SAColumn(DateTime, nullable=True)
    created_at = SAColumn(DateTime, default=utc_now, nullable=False)

