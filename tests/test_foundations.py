import os
from datetime import datetime, timezone
import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import RESPONSE_DAYS, BREACH_STAGE_2_HOURS, settings
from backend.db.models import (
    Base,
    QuestionnaireAnswer,
    BreachSimulation,
    EvidencePack,
    LedgerTamperBackup,
)


def test_yaml_files_load_and_parse():
    """Verify all four rules YAML files load and parse successfully."""
    base_rules_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "rules")
    
    # 1. rules.yaml
    rules_path = os.path.join(base_rules_dir, "rules.yaml")
    assert os.path.exists(rules_path), f"rules.yaml not found at {rules_path}"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules_data = yaml.safe_load(f)
    assert isinstance(rules_data, list)
    assert len(rules_data) == 12

    # 2. intents.yaml
    intents_path = os.path.join(base_rules_dir, "intents.yaml")
    assert os.path.exists(intents_path), f"intents.yaml not found at {intents_path}"
    with open(intents_path, "r", encoding="utf-8") as f:
        intents_data = yaml.safe_load(f)
    assert isinstance(intents_data, dict)
    assert "intents" in intents_data
    assert "erase" in intents_data["intents"]
    assert "access" in intents_data["intents"]

    # 3. retention.yaml
    retention_path = os.path.join(base_rules_dir, "retention.yaml")
    assert os.path.exists(retention_path), f"retention.yaml not found at {retention_path}"
    with open(retention_path, "r", encoding="utf-8") as f:
        retention_data = yaml.safe_load(f)
    assert isinstance(retention_data, dict)
    assert "sources" in retention_data
    assert len(retention_data["sources"]) >= 4

    # 4. breach_scenarios.yaml
    scenarios_path = os.path.join(base_rules_dir, "breach_scenarios.yaml")
    assert os.path.exists(scenarios_path), f"breach_scenarios.yaml not found at {scenarios_path}"
    with open(scenarios_path, "r", encoding="utf-8") as f:
        scenarios_data = yaml.safe_load(f)
    assert isinstance(scenarios_data, list)
    assert len(scenarios_data) == 5


def test_verify_true_and_verified_false():
    """Verify every rule and retention entry has verify: true and verified: false."""
    base_rules_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "rules")

    # Check rules.yaml
    with open(os.path.join(base_rules_dir, "rules.yaml"), "r", encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    for rule in rules:
        assert rule.get("verify") is True, f"Rule {rule.get('id')} lacks verify: True"
        assert rule.get("verified") is False, f"Rule {rule.get('id')} lacks verified: False"

    # Check retention.yaml
    with open(os.path.join(base_rules_dir, "retention.yaml"), "r", encoding="utf-8") as f:
        retention = yaml.safe_load(f)

    for src_name, src_cfg in retention.get("sources", {}).items():
        assert src_cfg.get("verify") is True, f"Source {src_name} lacks verify: True"
        assert src_cfg.get("verified") is False, f"Source {src_name} lacks verified: False"
        for field_name, field_cfg in src_cfg.get("fields", {}).items():
            assert field_cfg.get("verify") is True, f"Field {src_name}.{field_name} lacks verify: True"
            assert field_cfg.get("verified") is False, f"Field {src_name}.{field_name} lacks verified: False"


def test_statutory_constants():
    """Verify statutory DPDP constants in backend/config.py."""
    assert RESPONSE_DAYS == 30
    assert BREACH_STAGE_2_HOURS == 72
    assert settings.response_days == 30
    assert settings.breach_stage_2_hours == 72


def test_new_tables_accept_valid_rows():
    """Verify QuestionnaireAnswer, BreachSimulation, EvidencePack, and LedgerTamperBackup accept valid rows."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # 1. QuestionnaireAnswer
        q_row = QuestionnaireAnswer(key="cctv", answer="yes")
        session.add(q_row)
        session.commit()

        queried_q = session.query(QuestionnaireAnswer).filter_by(key="cctv").first()
        assert queried_q is not None
        assert queried_q.answer == "yes"

        # 2. BreachSimulation
        now = datetime.now(timezone.utc)
        sim_row = BreachSimulation(
            scenario="billing_laptop_ransomware",
            aware_at=now,
            device_protected="no",
            severity="critical",
            counts_json='{"records": 150, "people": 85}',
            drafts_json='{"board_draft": "Draft intimation", "principal_draft": "Draft advisory"}',
        )
        session.add(sim_row)
        session.commit()

        queried_sim = session.query(BreachSimulation).filter_by(scenario="billing_laptop_ransomware").first()
        assert queried_sim is not None
        assert queried_sim.severity == "critical"
        assert queried_sim.device_protected == "no"

        # 3. EvidencePack
        pack_row = EvidencePack(
            pack_id="evidence_pack_20261025_001",
            created_at=now.isoformat(),
            head_hash="a" * 64,
            score=92,
            chain_ok=1,
            path="data/out/evidence_pack_20261025_001.zip",
        )
        session.add(pack_row)
        session.commit()

        queried_pack = session.query(EvidencePack).filter_by(pack_id="evidence_pack_20261025_001").first()
        assert queried_pack is not None
        assert queried_pack.score == 92
        assert queried_pack.chain_ok == 1

        # 4. LedgerTamperBackup
        backup_row = LedgerTamperBackup(
            id=101,
            payload_json='{"action": "test_tamper"}',
            prev_hash="0" * 64,
            hash="b" * 64,
            ts=now.isoformat(),
            type="audit_log",
        )
        session.add(backup_row)
        session.commit()

        queried_backup = session.query(LedgerTamperBackup).filter_by(id=101).first()
        assert queried_backup is not None
        assert queried_backup.hash == "b" * 64
        assert queried_backup.type == "audit_log"

    finally:
        session.close()
        engine.dispose()
