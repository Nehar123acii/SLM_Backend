import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import Dataset, Column, ETLIssue, IdentifierFinding, VersionDiff, utc_now
from backend.etl.reader import read_file_to_df
from backend.etl.cleaner import clean_dataset
from backend.etl.identifier_checks import run_identifier_checks
from backend.etl.reconciler import reconcile_datasets
from backend.ai_client.mock_client import get_ai_client

logger = logging.getLogger("inventory_service")


def generate_dataset_id(db: Session) -> str:
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"ds_{today_str}_"
    count = db.query(Dataset).filter(Dataset.dataset_id.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:03d}"


class InventoryService:
    @staticmethod
    def process_upload(
        db: Session,
        original_filename: str,
        file_bytes: bytes,
    ) -> Dict[str, Any]:
        os.makedirs(settings.upload_temp_dir, exist_ok=True)
        dataset_id = generate_dataset_id(db)
        
        # Save staging file safely
        safe_name = os.path.basename(original_filename)
        staged_path = os.path.join(settings.upload_temp_dir, f"{dataset_id}_{safe_name}")
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

        # 1. Reader
        raw_df, reader_warnings = read_file_to_df(staged_path)
        total_raw_rows = len(raw_df)

        # 2. Cleaner
        cleaned_df, etl_issue_dicts, col_types = clean_dataset(raw_df)
        duplicate_count = sum(1 for iss in etl_issue_dicts if iss["issue_type"] == "DUPLICATE")
        rejected_count = sum(1 for iss in etl_issue_dicts if iss["issue_type"] == "REJECTED")
        accepted_count = len(cleaned_df)

        # 3. Identifier checks
        identifier_finding_dicts = run_identifier_checks(cleaned_df)

        # 4. Mock AI Column Classification
        ai_cols_payload = []
        for c in cleaned_df.columns:
            samples = cleaned_df[c].dropna().head(5).astype(str).tolist()
            ai_cols_payload.append({
                "name": c,
                "inferred_type": col_types.get(c, "TEXT"),
                "sample_values": samples,
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

        ai_result = ai_resp.get("result", {})
        classifications = {
            c["column_name"]: c for c in ai_result.get("classifications", [])
        }

        # 5. Version Diff (if previous version exists)
        if prev_dataset:
            prev_file_path = os.path.join(settings.upload_temp_dir, f"{prev_dataset.dataset_id}_{safe_name}")
            if os.path.exists(prev_file_path):
                try:
                    prev_raw, _ = read_file_to_df(prev_file_path)
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

        # 6. Persist to DB
        dataset_obj = Dataset(
            dataset_id=dataset_id,
            original_filename=safe_name,
            version=version,
            row_count=total_raw_rows,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
            status="AI_CLASSIFIED",
            temp_file_path=staged_path,
        )
        db.add(dataset_obj)

        for col_name, inferred_type in col_types.items():
            ai_data = classifications.get(col_name, {})
            # Check if any identifier findings matched this column
            flags = [
                f["pattern_type"]
                for f in identifier_finding_dicts
                if f["column_name"] == col_name
            ]
            col_obj = Column(
                dataset_id=dataset_id,
                column_name=col_name,
                inferred_type=inferred_type,
                ai_category=ai_data.get("category"),
                ai_sensitivity=ai_data.get("sensitivity"),
                ai_confidence=ai_data.get("confidence"),
                ai_explanation=ai_data.get("explanation"),
                dpdp_basis=ai_data.get("dpdp_basis"),
                identifier_flags=json.dumps(flags) if flags else None,
            )
            db.add(col_obj)

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

        db.commit()
        db.refresh(dataset_obj)

        return {
            "dataset_id": dataset_id,
            "version": version,
            "filename": safe_name,
            "row_count": total_raw_rows,
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "duplicate_count": duplicate_count,
            "etl_issues": etl_issue_dicts,
            "identifier_findings": identifier_finding_dicts,
            "columns": [
                {
                    "column_name": c.column_name,
                    "inferred_type": c.inferred_type,
                    "ai_category": c.ai_category,
                    "ai_sensitivity": c.ai_sensitivity,
                    "ai_confidence": c.ai_confidence,
                    "ai_explanation": c.ai_explanation,
                    "dpdp_basis": c.dpdp_basis,
                    "identifier_flags": json.loads(c.identifier_flags) if c.identifier_flags else [],
                }
                for c in dataset_obj.columns
            ],
            "ai_result": {
                "needs_human_review": ai_resp.get("needs_human_review", False),
                "classifications": ai_result.get("classifications", []),
            },
            "status": "AI_CLASSIFIED",
        }

    @staticmethod
    def approve_dataset(db: Session, dataset_id: str) -> Optional[Dataset]:
        dataset = db.query(Dataset).filter_by(dataset_id=dataset_id).first()
        if not dataset:
            return None
        dataset.status = "APPROVED"
        dataset.temp_file_path = None  # Clears temp file path, does not delete file automatically
        db.commit()
        db.refresh(dataset)
        return dataset

    @staticmethod
    def reject_dataset(db: Session, dataset_id: str) -> Optional[Dataset]:
        dataset = db.query(Dataset).filter_by(dataset_id=dataset_id).first()
        if not dataset:
            return None
        dataset.status = "REJECTED"
        db.commit()
        db.refresh(dataset)
        return dataset

    @staticmethod
    def cleanup_temp_file(db: Session, dataset_id: str) -> bool:
        """
        Owner-triggered cleanup of staging file.
        """
        dataset = db.query(Dataset).filter_by(dataset_id=dataset_id).first()
        if not dataset:
            return False
        # Remove from disk if present
        safe_name = os.path.basename(dataset.original_filename)
        expected_path = os.path.join(settings.upload_temp_dir, f"{dataset_id}_{safe_name}")
        if os.path.exists(expected_path):
            try:
                os.remove(expected_path)
            except OSError:
                pass
        dataset.temp_file_path = None
        db.commit()
        return True
