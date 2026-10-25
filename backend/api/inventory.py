import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.db.models import Dataset, Column, ETLIssue, IdentifierFinding, VersionDiff
from backend.services.inventory import InventoryService
from backend.services.purge import touch_activity
from backend.etl.adapters import SUPPORTED_SOURCES
from backend.etl.ocr_engine import OCRError
from backend.schemas import (
    DatasetUploadResponse,
    DatasetListItemResponse,
    DatasetDetailResponse,
    IdentifierFindingResponse,
    VersionDiffResponse,
    SupportedSourceResponse,
    ConsolidatedInventoryResponse,
    PrivacyAnalysisResponse,
    AuditLogResponse,
)

# TODO: Add authentication & authorization layer before production deployment

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/supported-sources", response_model=List[SupportedSourceResponse])
def get_supported_sources():
    """
    Returns supported source types, formats, options, and descriptions for data ingestion.
    """
    return SUPPORTED_SOURCES


@router.post("/upload", response_model=DatasetUploadResponse, status_code=status.HTTP_200_OK)
async def upload_dataset(
    file: UploadFile = File(...),
    source_type: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Upload file (CSV, Excel multi-sheet, Google Forms export, WhatsApp chat .txt, JSON,
    selectable/scanned PDF, or PNG/JPEG/TIFF images), execute multi-source ETL pipeline,
    run AI column classification, generate 5-category EDA, and persist results atomically.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename must be provided.")

    ext = "." + file.filename.split(".")[-1].lower() if "." in file.filename else ""
    valid_exts = [
        ".csv", ".xlsx", ".xls", ".json", ".txt",
        ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif",
    ]
    if ext not in valid_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Allowed formats: {', '.join(valid_exts)}."
        )

    content = await file.read()
    try:
        result = InventoryService.process_upload(
            db=db,
            original_filename=file.filename,
            file_bytes=content,
            source_type=source_type,
            sheet_name=sheet_name,
            language=language,
        )
        touch_activity(db)
        return result
    except (ValueError, OCRError) as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process upload: {str(e)}")


@router.get("/datasets", response_model=List[DatasetListItemResponse])
def list_datasets(db: Session = Depends(get_db)):
    """
    Lists all inventory datasets with status and row counts.
    """
    datasets = db.query(Dataset).order_by(Dataset.upload_timestamp.desc()).all()
    return datasets


@router.get("/datasets/{dataset_id}", response_model=DatasetDetailResponse)
def get_dataset(dataset_id: str, db: Session = Depends(get_db)):
    """
    Retrieves full details for a dataset, including column classifications and ETL issues.
    """
    dataset = db.query(Dataset).filter_by(dataset_id=dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")

    columns_data = []
    for c in dataset.columns:
        flags = json.loads(c.identifier_flags) if c.identifier_flags else []
        columns_data.append({
            "column_name": c.column_name,
            "original_name": c.original_name,
            "inferred_type": c.inferred_type,
            "ai_category": c.ai_category,
            "ai_sensitivity": c.ai_sensitivity,
            "ai_confidence": c.ai_confidence,
            "ai_explanation": c.ai_explanation,
            "dpdp_basis": c.dpdp_basis,
            "identifier_flags": flags,
            "purpose": c.purpose,
            "purpose_status": c.purpose_status,
        })

    eda_summary = json.loads(dataset.eda_summary) if dataset.eda_summary else None

    return {
        "id": dataset.id,
        "dataset_id": dataset.dataset_id,
        "original_filename": dataset.original_filename,
        "source_type": dataset.source_type,
        "sheet_name": dataset.sheet_name,
        "version": dataset.version,
        "row_count": dataset.row_count,
        "accepted_count": dataset.accepted_count,
        "rejected_count": dataset.rejected_count,
        "duplicate_count": dataset.duplicate_count,
        "upload_timestamp": dataset.upload_timestamp,
        "status": dataset.status,
        "temp_file_path": dataset.temp_file_path,
        "columns": columns_data,
        "etl_issues": dataset.etl_issues,
        "identifier_findings": dataset.identifier_findings,
        "eda_summary": eda_summary,
    }


@router.get("/datasets/{dataset_id}/eda-summary")
def get_dataset_eda_summary(dataset_id: str, db: Session = Depends(get_db)):
    """
    Returns the complete 5-category EDA report for a dataset:
    1. Dataset Overview
    2. Completeness and Duplication
    3. Numeric Distributions (measurements only)
    4. Categorical Distributions (sensitive values redacted)
    5. Time, Text and Data Quality
    """
    eda = InventoryService.get_eda_summary(db, dataset_id)
    if not eda:
        raise HTTPException(status_code=404, detail=f"EDA summary for dataset '{dataset_id}' not found.")
    return eda


@router.get("/datasets/{dataset_id}/identifier-findings", response_model=List[IdentifierFindingResponse])
def get_identifier_findings(dataset_id: str, db: Session = Depends(get_db)):
    """
    Returns deterministic identifier pattern match findings for a dataset.
    """
    findings = db.query(IdentifierFinding).filter_by(dataset_id=dataset_id).all()
    return findings


@router.get("/datasets/{dataset_id}/diff", response_model=VersionDiffResponse)
def get_dataset_diff(dataset_id: str, db: Session = Depends(get_db)):
    """
    Returns version diff metrics compared to the previous dataset version.
    """
    diff = db.query(VersionDiff).filter_by(dataset_id=dataset_id).first()
    if not diff:
        raise HTTPException(
            status_code=404,
            detail=f"Version diff for dataset '{dataset_id}' not found (it may be version 1)."
        )

    diff_data = json.loads(diff.diff_json) if diff.diff_json else {}
    return {
        "dataset_id": diff.dataset_id,
        "previous_dataset_id": diff.previous_dataset_id,
        "added_count": diff.added_count,
        "changed_count": diff.changed_count,
        "removed_count": diff.removed_count,
        "unchanged_count": diff.unchanged_count,
        "diff_json": diff_data,
        "created_at": diff.created_at,
    }


@router.get("/consolidated", response_model=ConsolidatedInventoryResponse)
def get_consolidated_inventory(db: Session = Depends(get_db)):
    """
    Retrieves unified inventory catalog across all ingested data sources,
    including personal data category coverage matrix and unresolved cross-source matches.
    """
    return InventoryService.get_consolidated_inventory(db)


@router.get("/consolidated/export")
def export_consolidated_inventory(
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    """
    Exports the consolidated multi-source inventory catalog as JSON or CSV.
    """
    content = InventoryService.export_consolidated_inventory(db, export_format=format)
    if format == "csv":
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=consolidated_inventory.csv"},
        )
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=consolidated_inventory.json"},
    )


@router.get("/privacy-analysis", response_model=PrivacyAnalysisResponse)
def get_privacy_analysis(db: Session = Depends(get_db)):
    """
    Retrieves case-specific privacy governance analyses:
    - Smart Personal Data Mapper
    - Privacy Leak Detector
    - Privacy Request Manager
    - Data Breach Response Assistant
    """
    return InventoryService.get_privacy_analysis(db)


@router.get("/audit-logs", response_model=List[AuditLogResponse])
def get_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Returns administrative system audit logs. Strictly excludes raw personal data.
    """
    return InventoryService.get_audit_logs(db, limit=limit)


@router.post("/datasets/{dataset_id}/approve", response_model=DatasetListItemResponse)
def approve_dataset(dataset_id: str, db: Session = Depends(get_db)):
    """
    Owner approves dataset; clears staging temp file path without deleting the physical file.
    """
    dataset = InventoryService.approve_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    return dataset


@router.post("/datasets/{dataset_id}/reject", response_model=DatasetListItemResponse)
def reject_dataset(dataset_id: str, db: Session = Depends(get_db)):
    """
    Owner rejects dataset.
    """
    dataset = InventoryService.reject_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    return dataset


@router.delete("/datasets/{dataset_id}/temp-file")
def delete_temp_file(dataset_id: str, db: Session = Depends(get_db)):
    """
    Owner-triggered cleanup of staging file after approval.
    """
    success = InventoryService.cleanup_temp_file(db, dataset_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    return {"message": f"Staging file for dataset '{dataset_id}' successfully cleaned up."}
