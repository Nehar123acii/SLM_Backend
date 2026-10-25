import csv
import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import (
    Dataset,
    Column,
    ETLIssue,
    IdentifierFinding,
    VersionDiff,
    AuditLog,
    CrossSourceMatch,
    PrivacyRequest,
    Incident,
    utc_now,
)
from backend.etl.reader import read_file_with_metadata
from backend.etl.cleaner import clean_dataset
from backend.etl.identifier_checks import run_identifier_checks
from backend.etl.reconciler import reconcile_datasets
from backend.etl.eda import compute_complete_eda
from backend.ai_client.mock_client import get_ai_client
from backend.services.provenance import (
    classify_column_category,
    compute_impact_tier,
    compute_locator,
    resolve_entities_and_record_occurrences,
)

logger = logging.getLogger("inventory_service")


def generate_dataset_id(db: Session) -> str:
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"ds_{today_str}_"
    count = db.query(Dataset).filter(Dataset.dataset_id.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:03d}"


def log_audit_event(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    actor: str = "system",
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """Logs non-PII administrative event."""
    log_entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        details=json.dumps(details or {}),
    )
    db.add(log_entry)
    return log_entry


class InventoryService:
    @staticmethod
    def process_upload(
        db: Session,
        original_filename: str,
        file_bytes: bytes,
        source_type: Optional[str] = None,
        sheet_name: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingests upload via source adapter, cleans data, performs identifier checks,
        invokes AI classification, computes 5-category EDA, checks cross-source matches,
        and saves everything atomically inside a database transaction.
        """
        os.makedirs(settings.upload_temp_dir, exist_ok=True)
        dataset_id = generate_dataset_id(db)
        safe_name = os.path.basename(original_filename)
        staged_path = os.path.join(settings.upload_temp_dir, f"{dataset_id}_{safe_name}")

        try:
            with open(staged_path, "wb") as f:
                f.write(file_bytes)

            # Check existing version for this logical filename
            prev_dataset = (
                db.query(Dataset)
                .filter_by(original_filename=safe_name)
                .order_by(Dataset.version.desc())
                .first()
            )
            version = (prev_dataset.version + 1) if prev_dataset else 1

            # 1. Multi-source extraction
            raw_df, reader_warnings, orig_mapping, source_meta = read_file_with_metadata(
                file_path=staged_path,
                source_type=source_type,
                sheet_name=sheet_name,
                language=language,
            )
            total_raw_rows = len(raw_df)
            resolved_source_type = source_meta.get("source_type", "csv")
            actual_sheet_name = source_meta.get("sheet_name", sheet_name)

            # 2. Cleaning & normalisation
            cleaned_df, etl_issue_dicts, col_types = clean_dataset(raw_df)

            # Record any reader warnings as etl issues
            for w in reader_warnings:
                etl_issue_dicts.append({
                    "issue_type": "INVALID",
                    "column_name": None,
                    "row_index": None,
                    "detail": w,
                })

            duplicate_count = sum(1 for iss in etl_issue_dicts if iss["issue_type"] == "DUPLICATE")
            rejected_count = sum(1 for iss in etl_issue_dicts if iss["issue_type"] == "REJECTED")
            accepted_count = len(cleaned_df)

            # 3. Deterministic identifier checks
            identifier_finding_dicts = run_identifier_checks(cleaned_df)

            # 4. AI Column Classification (contract-compliant mock or live)
            ai_cols_payload = []
            for c in cleaned_df.columns:
                samples = cleaned_df[c].dropna().head(5).astype(str).tolist()
                ai_cols_payload.append({
                    "name": c,
                    "inferred_type": col_types.get(c, "TEXT"),
                    "sample_values": samples,
                    "description": f"Source column: {orig_mapping.get(c, c)}",
                })

            ai_client = get_ai_client()
            ai_resp = ai_client.invoke({
                "task": "classify_columns",
                "version": "1",
                "payload": {
                    "dataset_id": dataset_id,
                    "columns": ai_cols_payload,
                },
            })

            ai_result = ai_resp.get("result", {}) or {}
            classifications = {
                c["column_name"]: c for c in ai_result.get("classifications", [])
            }

            # Columns metadata list for EDA
            columns_meta_for_eda = []
            for c in cleaned_df.columns:
                ai_c = classifications.get(c, {})
                columns_meta_for_eda.append({
                    "column_name": c,
                    "ai_category": ai_c.get("category"),
                    "ai_sensitivity": ai_c.get("sensitivity"),
                })

            # Normalization collisions from reader warnings
            collisions = [w for w in reader_warnings if "collision" in w.lower()]

            # 5. Compute complete 5-category EDA
            eda_report = compute_complete_eda(
                df=cleaned_df,
                dataset_id=dataset_id,
                version=version,
                source_type=resolved_source_type,
                original_filename=safe_name,
                col_types=col_types,
                etl_issues=etl_issue_dicts,
                identifier_findings=identifier_finding_dicts,
                raw_row_count=total_raw_rows,
                duplicate_count=duplicate_count,
                rejected_count=rejected_count,
                accepted_count=accepted_count,
                columns_meta=columns_meta_for_eda,
                source_metadata=source_meta,
                normalization_collisions=collisions,
            )

            # 6. Version Diff (if previous version exists)
            if prev_dataset:
                prev_file_path = os.path.join(settings.upload_temp_dir, f"{prev_dataset.dataset_id}_{safe_name}")
                if os.path.exists(prev_file_path):
                    try:
                        prev_raw, _, _, _ = read_file_with_metadata(prev_file_path, source_type=source_type)
                        prev_clean, _, _ = clean_dataset(prev_raw)
                        add_c, chg_c, rem_c, unchg_c, diff_json_str = reconcile_datasets(prev_clean, cleaned_df)
                        v_diff = VersionDiff(
                            dataset_id=dataset_id,
                            previous_dataset_id=prev_dataset.dataset_id,
                            added_count=add_c,
                            changed_count=chg_c,
                            removed_count=rem_c,
                            unchanged_count=unchg_c,
                            diff_json=diff_json_str,
                        )
                        db.add(v_diff)
                    except Exception as e:
                        logger.warning("Version diff computation failed: %s", str(e))

            # 7. Persist to DB within transaction
            from backend.services.purposes import infer_segment_from_filename
            dataset_obj = Dataset(
                dataset_id=dataset_id,
                original_filename=safe_name,
                source_type=resolved_source_type,
                sheet_name=actual_sheet_name,
                version=version,
                row_count=total_raw_rows,
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                duplicate_count=duplicate_count,
                status="AI_CLASSIFIED",
                temp_file_path=staged_path,
                eda_summary=json.dumps(eda_report),
                metadata_json=json.dumps(source_meta),
                segment=infer_segment_from_filename(safe_name),
            )
            db.add(dataset_obj)
            db.flush()

            # Save columns with source lineage and provenance
            col_objs: Dict[str, Column] = {}
            for col_name, inferred_type in col_types.items():
                ai_data = classifications.get(col_name, {})
                flags = [
                    f["pattern_type"]
                    for f in identifier_finding_dicts
                    if f["column_name"] == col_name
                ]
                orig_name = orig_mapping.get(col_name, col_name)

                # Determine default purpose status
                p_status = "DOCUMENTED" if any(k in col_name.lower() for k in ["billing", "invoice", "salary"]) else "AWAITING_REVIEW"
                purpose_hint = "Payment & Billing" if "invoice" in col_name or "amount" in col_name else (
                    "HR & Payroll" if "salary" in col_name else "Customer Service / Communications"
                )

                # Provenance fields (category, impact_tier, locator)
                col_category = classify_column_category(
                    col_name=col_name,
                    inferred_type=inferred_type,
                    flags=flags,
                    ai_data=ai_data,
                )
                col_impact_tier = compute_impact_tier(col_category)
                col_locator = compute_locator(
                    filename=safe_name,
                    sheet_name=actual_sheet_name,
                    col_name=col_name,
                    source_type=resolved_source_type,
                    source_meta=source_meta,
                )

                col_obj = Column(
                    dataset_id=dataset_id,
                    column_name=col_name,
                    original_name=orig_name,
                    inferred_type=inferred_type,
                    locator=col_locator,
                    category=col_category,
                    impact_tier=col_impact_tier,
                    ai_category=ai_data.get("category"),
                    ai_sensitivity=ai_data.get("sensitivity"),
                    ai_confidence=ai_data.get("confidence"),
                    ai_explanation=ai_data.get("explanation"),
                    dpdp_basis=ai_data.get("dpdp_basis"),
                    identifier_flags=json.dumps(flags) if flags else None,
                    purpose=purpose_hint,
                    purpose_status=p_status,
                )
                db.add(col_obj)
                col_objs[col_name] = col_obj

            db.flush()

            # Record identifier occurrences and perform entity resolution
            resolve_entities_and_record_occurrences(
                db=db,
                dataset_id=dataset_id,
                cleaned_df=cleaned_df,
                col_objs=col_objs,
                source_type=resolved_source_type,
            )

            for iss in etl_issue_dicts:
                db.add(ETLIssue(
                    dataset_id=dataset_id,
                    issue_type=iss["issue_type"],
                    column_name=iss["column_name"],
                    row_index=iss["row_index"],
                    detail=iss["detail"],
                ))

            for fnd in identifier_finding_dicts:
                db.add(IdentifierFinding(
                    dataset_id=dataset_id,
                    column_name=fnd["column_name"],
                    pattern_type=fnd["pattern_type"],
                    match_count=fnd["match_count"],
                    caveat=fnd["caveat"],
                ))

            # 8. Detect Cross-Source Overlap with other datasets (Flag as UNRESOLVED)
            existing_datasets = db.query(Dataset).filter(Dataset.dataset_id != dataset_id).all()
            for other_ds in existing_datasets:
                # Find overlapping identifier columns
                other_cols = {c.column_name: c for c in other_ds.columns}
                for cname, itype in col_types.items():
                    if itype in ["EMAIL", "PHONE"] and cname in other_cols:
                        db.add(CrossSourceMatch(
                            source_dataset_id_1=other_ds.dataset_id,
                            source_dataset_id_2=dataset_id,
                            match_field=cname,
                            match_type="POTENTIAL_CANDIDATE",
                            status="UNRESOLVED",
                            caveat=(
                                f"Potential record overlap detected in field '{cname}'. "
                                "Under the DPDP framework, cross-source matches require human verification before combining records."
                            ),
                        ))

            # Log audit event
            log_audit_event(
                db=db,
                action="UPLOAD_PROCESSED",
                entity_type="dataset",
                entity_id=dataset_id,
                details={
                    "filename": safe_name,
                    "version": version,
                    "source_type": resolved_source_type,
                    "rows": total_raw_rows,
                },
            )

            db.commit()
            db.refresh(dataset_obj)

            return {
                "dataset_id": dataset_id,
                "version": version,
                "filename": safe_name,
                "source_type": resolved_source_type,
                "sheet_name": actual_sheet_name,
                "row_count": total_raw_rows,
                "accepted_count": accepted_count,
                "rejected_count": rejected_count,
                "duplicate_count": duplicate_count,
                "etl_issues": etl_issue_dicts,
                "identifier_findings": identifier_finding_dicts,
                "columns": [
                    {
                        "column_name": c.column_name,
                        "original_name": c.original_name,
                        "inferred_type": c.inferred_type,
                        "locator": c.locator,
                        "category": c.category,
                        "impact_tier": c.impact_tier,
                        "ai_category": c.ai_category,
                        "ai_sensitivity": c.ai_sensitivity,
                        "ai_confidence": c.ai_confidence,
                        "ai_explanation": c.ai_explanation,
                        "dpdp_basis": c.dpdp_basis,
                        "identifier_flags": json.loads(c.identifier_flags) if c.identifier_flags else [],
                        "purpose": c.purpose,
                        "purpose_status": c.purpose_status,
                    }
                    for c in dataset_obj.columns
                ],
                "ai_result": {
                    "needs_human_review": ai_resp.get("needs_human_review", False),
                    "classifications": ai_result.get("classifications", []),
                },
                "eda_summary": eda_report,
                "status": "AI_CLASSIFIED",
            }

        except Exception as e:
            db.rollback()
            # Clean up temporary staging file if transaction failed
            if os.path.exists(staged_path):
                try:
                    os.remove(staged_path)
                except OSError:
                    pass
            logger.error("Transactional upload failed for %s: %s", safe_name, str(e))
            raise

    @staticmethod
    def get_eda_summary(db: Session, dataset_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached 5-category EDA summary for a dataset."""
        dataset = db.query(Dataset).filter_by(dataset_id=dataset_id).first()
        if not dataset:
            return None
        if dataset.eda_summary:
            return json.loads(dataset.eda_summary)
        return None

    @staticmethod
    def get_consolidated_inventory(db: Session) -> Dict[str, Any]:
        """
        Builds the consolidated multi-source inventory catalog:
        - Registered sources overview
        - Full column schema catalogue with source provenance
        - Cross-source personal data category matrix
        - Unresolved cross-source identity matches
        """
        datasets = db.query(Dataset).order_by(Dataset.upload_timestamp.desc()).all()
        all_columns = db.query(Column).all()
        cross_matches = db.query(CrossSourceMatch).all()

        sources_summary = []
        for d in datasets:
            meta = json.loads(d.metadata_json) if d.metadata_json else {}
            sources_summary.append({
                "dataset_id": d.dataset_id,
                "original_filename": d.original_filename,
                "source_type": d.source_type,
                "sheet_name": d.sheet_name,
                "version": d.version,
                "row_count": d.row_count,
                "accepted_count": d.accepted_count,
                "status": d.status,
                "upload_timestamp": d.upload_timestamp,
                "metadata": meta,
            })

        columns_catalog = []
        category_set = set()
        for col in all_columns:
            cat = col.ai_category or "NON_PERSONAL"
            category_set.add(cat)
            columns_catalog.append({
                "dataset_id": col.dataset_id,
                "column_name": col.column_name,
                "original_name": col.original_name,
                "inferred_type": col.inferred_type,
                "ai_category": col.ai_category,
                "ai_sensitivity": col.ai_sensitivity,
                "dpdp_basis": col.dpdp_basis,
                "purpose": col.purpose,
                "purpose_status": col.purpose_status,
            })

        # Category coverage matrix: source_id -> list of personal data categories present
        matrix: Dict[str, List[str]] = {}
        for d in datasets:
            cats = {c.ai_category for c in d.columns if c.ai_category and c.ai_category != "NON_PERSONAL"}
            matrix[d.dataset_id] = sorted(list(cats))

        unresolved_matches = []
        for m in cross_matches:
            unresolved_matches.append({
                "match_id": m.id,
                "source_1": m.source_dataset_id_1,
                "source_2": m.source_dataset_id_2,
                "field": m.match_field,
                "match_type": m.match_type,
                "status": m.status,
                "caveat": m.caveat,
            })

        return {
            "total_sources": len(datasets),
            "total_columns": len(all_columns),
            "total_records": sum(d.accepted_count for d in datasets),
            "sources": sources_summary,
            "columns": columns_catalog,
            "category_coverage_matrix": matrix,
            "cross_source_matches": unresolved_matches,
        }

    @staticmethod
    def export_consolidated_inventory(db: Session, export_format: str = "json") -> str:
        """
        Exports the consolidated inventory catalog as JSON string or CSV string.
        """
        inv = InventoryService.get_consolidated_inventory(db)
        if export_format.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "dataset_id", "source_name", "column_name", "original_field_name",
                "inferred_type", "ai_category", "ai_sensitivity", "purpose", "purpose_status"
            ])
            for col in inv["columns"]:
                writer.writerow([
                    col["dataset_id"],
                    col.get("source_name", ""),
                    col["column_name"],
                    col.get("original_name", ""),
                    col["inferred_type"],
                    col.get("ai_category", ""),
                    col.get("ai_sensitivity", ""),
                    col.get("purpose", ""),
                    col.get("purpose_status", ""),
                ])
            return output.getvalue()
        else:
            return json.dumps(inv, default=str, indent=2)

    @staticmethod
    def get_privacy_analysis(db: Session) -> Dict[str, Any]:
        """
        Aggregates case-specific privacy analyses:
        - Smart Personal Data Mapper
        - Privacy Leak Detector
        - Consent & Purpose Checker
        - Privacy Request Manager
        - Breach Assistant Summary
        """
        datasets = db.query(Dataset).all()
        all_cols = db.query(Column).all()
        identifier_findings = db.query(IdentifierFinding).all()
        requests = db.query(PrivacyRequest).all()
        incidents = db.query(Incident).all()

        # 1. Smart Personal Data Mapper
        category_counts: Dict[str, int] = {}
        for c in all_cols:
            cat = c.ai_category or "NON_PERSONAL"
            category_counts[cat] = category_counts.get(cat, 0) + 1

        documented_purposes = sum(1 for c in all_cols if c.purpose_status == "DOCUMENTED")
        undocumented_purposes = sum(1 for c in all_cols if c.purpose_status == "AWAITING_REVIEW")

        # 2. Privacy Leak Detector
        findings_summary = []
        for f in identifier_findings:
            findings_summary.append({
                "dataset_id": f.dataset_id,
                "column_name": f.column_name,
                "pattern_type": f.pattern_type,
                "match_count": f.match_count,
                "caveat": f.caveat,
            })

        # 3. Privacy Request Manager
        requests_by_status: Dict[str, int] = {}
        requests_by_urgency: Dict[str, int] = {}
        for r in requests:
            requests_by_status[r.status] = requests_by_status.get(r.status, 0) + 1
            requests_by_urgency[r.urgency] = requests_by_urgency.get(r.urgency, 0) + 1

        # 4. Breach Assistant Summary
        incidents_by_status: Dict[str, int] = {}
        for inc in incidents:
            incidents_by_status[inc.status] = incidents_by_status.get(inc.status, 0) + 1

        return {
            "smart_personal_data_mapper": {
                "categories_distribution": category_counts,
                "total_classified_fields": len(all_cols),
                "documented_purposes_count": documented_purposes,
                "awaiting_review_purposes_count": undocumented_purposes,
            },
            "privacy_leak_detector": {
                "total_deterministic_findings": len(identifier_findings),
                "findings": findings_summary,
            },
            "privacy_requests_summary": {
                "total_requests": len(requests),
                "by_status": requests_by_status,
                "by_urgency": requests_by_urgency,
            },
            "breach_assistant_summary": {
                "total_incidents": len(incidents),
                "by_status": incidents_by_status,
            },
        }

    @staticmethod
    def get_audit_logs(db: Session, limit: int = 100) -> List[AuditLog]:
        """Returns recent system audit events."""
        return db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()

    @staticmethod
    def approve_dataset(db: Session, dataset_id: str) -> Optional[Dataset]:
        dataset = db.query(Dataset).filter_by(dataset_id=dataset_id).first()
        if not dataset:
            return None
        dataset.status = "APPROVED"
        dataset.temp_file_path = None
        log_audit_event(db, "DATASET_APPROVED", "dataset", dataset_id)
        db.commit()
        db.refresh(dataset)
        return dataset

    @staticmethod
    def reject_dataset(db: Session, dataset_id: str) -> Optional[Dataset]:
        dataset = db.query(Dataset).filter_by(dataset_id=dataset_id).first()
        if not dataset:
            return None
        dataset.status = "REJECTED"
        log_audit_event(db, "DATASET_REJECTED", "dataset", dataset_id)
        db.commit()
        db.refresh(dataset)
        return dataset

    @staticmethod
    def cleanup_temp_file(db: Session, dataset_id: str) -> bool:
        """Owner-triggered cleanup of staging file."""
        dataset = db.query(Dataset).filter_by(dataset_id=dataset_id).first()
        if not dataset:
            return False
        safe_name = os.path.basename(dataset.original_filename)
        expected_path = os.path.join(settings.upload_temp_dir, f"{dataset_id}_{safe_name}")
        if os.path.exists(expected_path):
            try:
                os.remove(expected_path)
            except OSError:
                pass
        dataset.temp_file_path = None
        log_audit_event(db, "TEMP_FILE_CLEANED", "dataset", dataset_id)
        db.commit()
        return True
