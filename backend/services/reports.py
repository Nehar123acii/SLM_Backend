"""
backend/services/reports.py
===========================
Compliance readiness reports engine.
Generates comprehensive summaries, prioritized recommended actions,
and printable self-contained reports without CDNs or raw personal data.
"""

from html import escape
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.db.models import (
    BreachSimulation,
    Column,
    Dataset,
    ErasurePlan,
    LedgerEvent,
    Person,
    RightsCase,
)
from backend.services.graphs import get_purpose_coverage
from backend.services.ledger import append_event, get_head_hash, verify_chain
from backend.services.rules import ALLOWED_FIX_ACTIONS, get_latest_flags


DEFAULT_LIMITATIONS = """# Kavach Compliance Evidence Pack — Limitations & Scope

1. **Pseudonymisation, Not Anonymisation**: Personal data within the Kavach system is pseudonymised using keyed HMAC-SHA256; it is not irreversibly anonymised.
2. **External Head Hash Requirement**: The cryptographic tamper-evidence of this evidence pack holds only if the ledger head hash is preserved outside the database or independently timestamped.
3. **Out of Scope**: Off-site backups, secondary cold storage, and third-party data processor copies are out of scope of this local evidence snapshot.
4. **Statutory Citations**: Statutory citations in rules and retention schedules are unverified hints provided for human review and verification.
5. **Regulatory Disclaimer**: This platform and evidence pack serve as an operational readiness aid and technical compliance audit trail, not formal legal advice.
"""


def get_limitations_content() -> str:
    """Loads limitations.md content from disk, with fallback."""
    candidates = [
        Path("limitations.md"),
        Path(__file__).resolve().parent.parent / "rules" / "limitations.md",
        Path(__file__).resolve().parent.parent.parent / "limitations.md",
        Path(__file__).resolve().parent.parent.parent / "docs" / "limitations.md",
    ]
    for p in candidates:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                pass
    return DEFAULT_LIMITATIONS


def build_compliance_summary(session: Session) -> Dict[str, Any]:
    """
    Builds compliance readiness summary from existing data without any 0-100 score:
    - upload and source counts
    - latest flags (state, whats_right, whats_not, how_to_fix, citation chip marked 'to verify')
    - purpose coverage (confirmed, inferred, unknown)
    - cases and their status
    - erasure receipts
    - breach simulations
    - ledger status (chain ok, head hash)
    - limitations.md contents
    - up to 8 prioritized actions (RED -> YELLOW -> unknown -> NOT_ASSESSED)
    """
    # 1. Sources & inventory counts
    datasets = session.query(Dataset).order_by(Dataset.id.asc()).all()
    sources_count = len(datasets)
    records_count = sum(d.row_count or 0 for d in datasets)
    columns_count = session.query(Column).count()
    distinct_people = session.query(Person).count()

    sources_list = [
        {
            "id": d.id,
            "dataset_id": d.dataset_id,
            "name": d.original_filename,
            "filename": d.original_filename,
            "source_type": d.source_type,
            "record_count": d.row_count or 0,
            "created_at": d.upload_timestamp.isoformat() if getattr(d, "upload_timestamp", None) else None,
        }
        for d in datasets
    ]

    # 2. Latest compliance flags
    raw_flags = get_latest_flags(session)
    flags: List[Dict[str, Any]] = []
    for f in raw_flags:
        rule_id = f.get("rule_id", "")
        state = f.get("state", "NOT_ASSESSED")
        citation_hint = f.get("citation_hint", "")
        verify = f.get("verify", True)
        verified = f.get("verified", False)

        whats_right = f.get("whats_right", "No issue found by Kavach's checks")
        if state == "GREEN" and not whats_right.startswith("No issue found by Kavach's checks"):
            whats_right = f"No issue found by Kavach's checks: {whats_right}"

        flags.append({
            "rule_id": rule_id,
            "state": state,
            "title": f.get("title", rule_id),
            "citation": citation_hint,
            "citation_hint": citation_hint,
            "citation_chip": f"{citation_hint} (to verify)" if citation_hint else "to verify",
            "verify": verify,
            "verified": verified,
            "whats_right": whats_right,
            "whats_not": f.get("whats_not", ""),
            "how_to_fix": f.get("how_to_fix", ""),
            "fix_action": f.get("fix_action", "review_columns"),
            "evidence_refs": f.get("evidence_refs", []),
            "created_at": f.get("created_at"),
        })

    # 3. Purpose coverage
    coverage_sources = get_purpose_coverage(session)
    confirmed_purposes = sum(s.get("confirmed", 0) for s in coverage_sources)
    inferred_purposes = sum(s.get("inferred", 0) for s in coverage_sources)
    unknown_purposes = sum(s.get("unknown", 0) for s in coverage_sources)

    purpose_coverage = {
        "confirmed": confirmed_purposes,
        "inferred": inferred_purposes,
        "unknown": unknown_purposes,
        "sources": coverage_sources,
    }

    # 4. Rights desk cases
    cases_rows = session.query(RightsCase).order_by(RightsCase.id.asc()).all()
    counts_by_status: Dict[str, int] = {}
    cases_items = []
    for c in cases_rows:
        counts_by_status[c.status] = counts_by_status.get(c.status, 0) + 1
        cases_items.append({
            "id": c.id,
            "case_ref": c.case_ref,
            "intent": c.intent,
            "sender_masked": c.sender_masked,
            "status": c.status,
            "received_at": c.received_at.isoformat() if c.received_at else None,
            "due_at": c.due_at.isoformat() if c.due_at else None,
            "due_verify": c.due_verify,
        })

    cases_summary = {
        "total": len(cases_rows),
        "counts_by_status": counts_by_status,
        "items": cases_items,
    }

    # 5. Erasure receipts
    plans = (
        session.query(ErasurePlan)
        .filter(ErasurePlan.status == "executed")
        .order_by(ErasurePlan.id.asc())
        .all()
    )
    receipts_items = []
    for p in plans:
        counts = {}
        residual_unexpected = 0
        if p.receipt_json:
            try:
                rec_data = json.loads(p.receipt_json)
                counts = rec_data.get("action_counts", {})
                res_report = rec_data.get("residual_report", {})
                if isinstance(res_report, dict):
                    for file_info in res_report.values():
                        if isinstance(file_info, dict):
                            for cat_info in file_info.values():
                                if isinstance(cat_info, dict):
                                    residual_unexpected += int(cat_info.get("unexpected", 0))
            except Exception:
                pass

        receipts_items.append({
            "id": p.id,
            "person_id": p.person_id,
            "plan_hash": p.plan_hash,
            "executed_at": p.executed_at.isoformat() if p.executed_at else None,
            "counts": counts,
            "residual_unexpected": residual_unexpected,
        })

    erasure_receipts = {
        "total": len(receipts_items),
        "items": receipts_items,
    }

    # 6. Breach simulations
    sim_rows = (
        session.query(BreachSimulation)
        .order_by(BreachSimulation.id.desc())
        .all()
    )
    sims_items = []
    for s in sim_rows:
        cnt_payload = {}
        if s.counts_json:
            try:
                cnt_payload = json.loads(s.counts_json)
            except Exception:
                pass

        people_counts = cnt_payload.get("people", {
            "total": cnt_payload.get("people_count", 0),
            "confirmed": cnt_payload.get("confirmed_count", 0),
            "possible": cnt_payload.get("possible_count", 0),
            "range": cnt_payload.get("range", ""),
        })

        sims_items.append({
            "id": s.id,
            "scenario": s.scenario,
            "severity": s.severity,
            "people_counts": people_counts,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "marked": "SIMULATION",
            "is_simulation": True,
        })

    breach_simulations = {
        "total": len(sims_items),
        "items": sims_items,
    }

    # 7. Ledger verification
    chain_res = verify_chain(session)
    head_hash = get_head_hash(session)
    ledger_status = {
        "chain_ok": bool(chain_res.get("ok", False)),
        "checked": int(chain_res.get("checked", 0)),
        "head_hash": head_hash,
    }

    # 8. Limitations
    limitations_md = get_limitations_content()

    # 9. Prioritized Actions (Max 8)
    # Order strictly: RED first -> YELLOW -> unknown purposes -> NOT_ASSESSED
    # Each action points to an existing fix_action in ALLOWED_FIX_ACTIONS
    red_actions: List[Dict[str, Any]] = []
    yellow_actions: List[Dict[str, Any]] = []
    unknown_actions: List[Dict[str, Any]] = []
    not_assessed_actions: List[Dict[str, Any]] = []

    for f in flags:
        st = f.get("state")
        rid = f.get("rule_id", "")
        fix_act = f.get("fix_action", "review_columns")
        if fix_act not in ALLOWED_FIX_ACTIONS:
            fix_act = "review_columns"

        if rid == "unknown_purposes":
            # Handled in dedicated unknown category below
            continue

        item = {
            "rule_id": rid,
            "title": f.get("title", rid),
            "state": st,
            "level": st,
            "category": st,
            "reason": f.get("whats_not") or f.get("how_to_fix") or "Compliance gap identified",
            "how_to_fix": f.get("how_to_fix", ""),
            "fix_action": fix_act,
        }

        if st == "RED":
            red_actions.append(item)
        elif st == "YELLOW":
            yellow_actions.append(item)
        elif st == "NOT_ASSESSED":
            not_assessed_actions.append(item)

    # Unknown purposes check
    unknown_rule_flag = next((f for f in flags if f.get("rule_id") == "unknown_purposes"), None)
    unknown_purposes_present = unknown_purposes > 0 or (
        unknown_rule_flag and unknown_rule_flag.get("state") in ("RED", "YELLOW")
    )
    if unknown_purposes_present:
        unknown_actions.append({
            "rule_id": "unknown_purposes",
            "title": "Unconfirmed processing purposes for personal data columns",
            "state": "unknown",
            "level": "unknown",
            "category": "unknown",
            "reason": (
                f"{unknown_purposes} column(s) lack a confirmed processing purpose under DPDP Act."
                if unknown_purposes > 0
                else "Unconfirmed processing purposes detected for personal data columns."
            ),
            "how_to_fix": "Review unconfirmed data columns and link each to a legitimate business purpose.",
            "fix_action": "answer_question",
        })

    all_actions = red_actions + yellow_actions + unknown_actions + not_assessed_actions
    selected_actions = all_actions[:8]
    for idx, act in enumerate(selected_actions):
        act["priority"] = idx + 1

    summary = {
        "sources_count": sources_count,
        "total_sources": sources_count,
        "records_count": records_count,
        "total_records": records_count,
        "columns_count": columns_count,
        "total_columns": columns_count,
        "distinct_people": distinct_people,
        "people_count": distinct_people,
        "sources": sources_list,
        "flags": flags,
        "flags_count": len(flags),
        "purpose_coverage": purpose_coverage,
        "cases": cases_summary,
        "rights_requests": cases_summary,
        "erasure_receipts": erasure_receipts,
        "breach_simulations": breach_simulations,
        "ledger_status": ledger_status,
        "limitations": limitations_md,
        "actions": selected_actions,
        "recommended_actions": selected_actions,
        "footer": "Readiness aid, not legal advice. Citations unverified.",
    }
    return summary


def log_report_exported(session: Session, summary: Dict[str, Any]) -> LedgerEvent:
    """Logs report_exported ledger event with ids and counts only."""
    payload = {
        "sources_count": int(summary.get("sources_count", 0)),
        "records_count": int(summary.get("records_count", 0)),
        "columns_count": int(summary.get("columns_count", 0)),
        "people_count": int(summary.get("distinct_people", 0)),
        "flags_count": int(summary.get("flags_count", 0)),
        "cases_count": int(summary.get("cases", {}).get("total", 0)),
        "erasure_receipts_count": int(summary.get("erasure_receipts", {}).get("total", 0)),
        "breach_simulations_count": int(summary.get("breach_simulations", {}).get("total", 0)),
    }
    return append_event(session, "report_exported", payload)


def generate_html_report(summary: Dict[str, Any]) -> str:
    """
    Renders self-contained printable HTML report.
    - Uses embedded styles and @media print
    - Zero external CDN links or network requests
    - Zero raw sentinel values
    - Empty business: all NOT_ASSESSED, no GREEN anywhere in the HTML
    - GREEN wording: strictly 'No issue found by Kavach's checks'
    - Footer: 'Readiness aid, not legal advice. Citations unverified.'
    """
    sources_count = summary.get("sources_count", 0)
    records_count = summary.get("records_count", 0)
    columns_count = summary.get("columns_count", 0)
    distinct_people = summary.get("distinct_people", 0)

    purpose_cov = summary.get("purpose_coverage", {})
    confirmed_purposes = purpose_cov.get("confirmed", 0)
    inferred_purposes = purpose_cov.get("inferred", 0)
    unknown_purposes = purpose_cov.get("unknown", 0)

    flags = summary.get("flags", [])
    actions = summary.get("actions", [])
    cases = summary.get("cases", {})
    receipts = summary.get("erasure_receipts", {}).get("items", [])
    sims = summary.get("breach_simulations", {}).get("items", [])
    ledger = summary.get("ledger_status", {})
    limitations_text = summary.get("limitations", "")

    # Actions rows
    if actions:
        actions_rows = "".join(
            f"<tr>"
            f"<td><strong>#{act.get('priority')}</strong></td>"
            f"<td><strong>{escape(act.get('title', ''))}</strong></td>"
            f"<td>{escape(act.get('reason', ''))}</td>"
            f"<td><code>{escape(act.get('fix_action', ''))}</code></td>"
            f"</tr>"
            for act in actions
        )
    else:
        actions_rows = "<tr><td colspan='4'><em>No pending recommended actions.</em></td></tr>"

    # Flags rows
    if flags:
        flag_rows_list = []
        for f in flags:
            st = f.get("state", "NOT_ASSESSED")
            if st == "GREEN":
                st_badge = '<span class="badge badge-ok">[No issue found by Kavach\'s checks]</span>'
                rule_desc = "No issue found by Kavach's checks"
            elif st == "RED":
                st_badge = '<span class="badge badge-crit">[RED]</span>'
                rule_desc = escape(f.get("whats_not") or f.get("how_to_fix") or "Issue identified")
            elif st == "YELLOW":
                st_badge = '<span class="badge badge-warn">[YELLOW]</span>'
                rule_desc = escape(f.get("whats_not") or f.get("how_to_fix") or "Caution advised")
            else:
                st_badge = '<span class="badge badge-na">[NOT ASSESSED]</span>'
                rule_desc = "Data not yet collected for this check"

            citation_chip = escape(f.get("citation_chip", "to verify"))
            how_to_fix = escape(f.get("how_to_fix", ""))

            flag_rows_list.append(
                f"<tr>"
                f"<td>{st_badge}</td>"
                f"<td><strong>{escape(f.get('title', ''))}</strong><br><small>{rule_desc}</small></td>"
                f"<td><span class='badge badge-verify'>[{citation_chip}]</span></td>"
                f"<td>{how_to_fix}</td>"
                f"</tr>"
            )
        flags_rows = "".join(flag_rows_list)
    else:
        flags_rows = "<tr><td colspan='4'><em>No compliance rules assessed.</em></td></tr>"

    # Purpose coverage rows
    sources_cov = purpose_cov.get("sources", [])
    if sources_cov:
        cov_rows = "".join(
            f"<tr>"
            f"<td>{escape(str(s.get('filename') or s.get('source_id')))}</td>"
            f"<td>{s.get('total_fields', 0)}</td>"
            f"<td>{s.get('confirmed', 0)}</td>"
            f"<td>{s.get('inferred', 0)}</td>"
            f"<td>{s.get('unknown', 0)}</td>"
            f"</tr>"
            for s in sources_cov
        )
    else:
        cov_rows = "<tr><td colspan='5'><em>No source data files ingested yet.</em></td></tr>"

    # Cases rows
    cases_items = cases.get("items", [])
    if cases_items:
        cases_rows = "".join(
            f"<tr>"
            f"<td>#{c.get('id')} ({escape(c.get('case_ref', ''))})</td>"
            f"<td>{escape(c.get('intent', ''))}</td>"
            f"<td>{escape(c.get('status', ''))}</td>"
            f"<td>{escape(str(c.get('due_at', ''))[:10])}</td>"
            f"</tr>"
            for c in cases_items
        )
    else:
        cases_rows = "<tr><td colspan='4'><em>No data principal rights cases recorded.</em></td></tr>"

    # Erasure receipts rows
    if receipts:
        receipts_rows = "".join(
            f"<tr>"
            f"<td>#{r.get('id')}</td>"
            f"<td>{escape(str(r.get('executed_at', ''))[:19])}</td>"
            f"<td><code>{escape(str(r.get('plan_hash', ''))[:16])}...</code></td>"
            f"<td>{escape(json.dumps(r.get('counts', {})))}</td>"
            f"<td>{r.get('residual_unexpected', 0)}</td>"
            f"</tr>"
            for r in receipts
        )
    else:
        receipts_rows = "<tr><td colspan='5'><em>No completed erasure receipts recorded.</em></td></tr>"

    # Breach simulations rows
    if sims:
        sims_rows = "".join(
            f"<tr>"
            f"<td>#{s.get('id')}</td>"
            f"<td><span class='badge badge-warn'>[SIMULATION]</span> <strong>{escape(s.get('scenario', ''))}</strong></td>"
            f"<td>{escape(str(s.get('severity', '')).upper())}</td>"
            f"<td>{escape(str(s.get('people_counts', {}).get('range') or s.get('people_counts', {}).get('total', 0)))} principals</td>"
            f"<td>{escape(str(s.get('created_at', ''))[:10])}</td>"
            f"</tr>"
            for s in sims
        )
    else:
        sims_rows = "<tr><td colspan='5'><em>No breach simulations recorded.</em></td></tr>"

    # Limitations HTML
    limitations_paras = "".join(
        f"<p style='margin-bottom: 8px;'>{escape(line)}</p>"
        for line in limitations_text.splitlines()
        if line.strip()
    )

    ledger_ok_text = "Verified cryptographic integrity" if ledger.get("chain_ok") else "Chain integrity alert"
    head_hash_text = escape(str(ledger.get("head_hash", ""))[:16]) + "..." if ledger.get("head_hash") else "None"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kavach Compliance Readiness Report</title>
    <style>
        :root {{
            --text-color: #0f172a;
            --text-muted: #475569;
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --border-color: #cbd5e1;
            --primary: #1e3a8a;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: var(--text-color);
            background: var(--bg-color);
            line-height: 1.5;
            padding: 24px;
        }}
        .report-wrapper {{
            max-width: 900px;
            margin: 0 auto;
            background: var(--card-bg);
            padding: 36px 48px;
            border: 1px solid var(--border-color);
            border-radius: 8px;
        }}
        .header {{
            border-bottom: 2px solid var(--primary);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        .title {{
            font-size: 24px;
            font-weight: 700;
            color: var(--primary);
            margin-bottom: 4px;
        }}
        .subtitle {{
            font-size: 14px;
            color: var(--text-muted);
        }}
        .notice-box {{
            background: #eff6ff;
            border-left: 4px solid var(--primary);
            padding: 10px 14px;
            font-size: 13px;
            margin-bottom: 24px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: #f1f5f9;
            padding: 12px;
            border-radius: 6px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 22px;
            font-weight: 700;
            color: var(--primary);
        }}
        .stat-label {{
            font-size: 12px;
            color: var(--text-muted);
            text-transform: uppercase;
        }}
        .section {{
            margin-bottom: 28px;
            page-break-inside: avoid;
        }}
        .section-title {{
            font-size: 16px;
            font-weight: 700;
            color: #0f172a;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 6px;
            margin-bottom: 12px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-bottom: 12px;
        }}
        th, td {{
            text-align: left;
            padding: 8px 10px;
            border-bottom: 1px solid var(--border-color);
            vertical-align: top;
        }}
        th {{
            background: #f1f5f9;
            font-weight: 600;
            color: #334155;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .badge {{
            display: inline-block;
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
        }}
        .badge-crit {{ background: #fee2e2; color: #991b1b; }}
        .badge-warn {{ background: #fef3c7; color: #92400e; }}
        .badge-ok {{ background: #dcfce7; color: #166534; }}
        .badge-na {{ background: #f1f5f9; color: #475569; }}
        .badge-verify {{ background: #e0f2fe; color: #0369a1; }}
        .footer {{
            border-top: 1px solid var(--border-color);
            padding-top: 16px;
            margin-top: 32px;
            font-size: 11px;
            color: var(--text-muted);
            text-align: center;
        }}
        @media print {{
            body {{
                background: #ffffff !important;
                color: #000000 !important;
                font-size: 10pt;
                padding: 0;
            }}
            .report-wrapper {{
                border: none;
                box-shadow: none;
                padding: 0;
                max-width: 100%;
            }}
            th {{
                background: #f1f5f9 !important;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
            .badge {{
                border: 1px solid #475569 !important;
                color: #000000 !important;
                background: transparent !important;
            }}
            .section, tr {{
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="report-wrapper">
        <header class="header">
            <h1 class="title">Kavach Compliance Readiness Report</h1>
            <p class="subtitle">Digital Personal Data Protection Act (DPDP Act) Technical Audit Snapshot</p>
        </header>

        <div class="notice-box">
            <strong>Readiness Aid Notice:</strong> This audit report is an automated readiness tool and technical compliance summary. Citations unverified. Consult legal counsel for formal compliance.
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{sources_count}</div>
                <div class="stat-label">Data Sources</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{records_count}</div>
                <div class="stat-label">Total Records</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{columns_count}</div>
                <div class="stat-label">Columns Mapped</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{distinct_people}</div>
                <div class="stat-label">Distinct Principals</div>
            </div>
        </div>

        <!-- Section 1: Recommended Actions -->
        <section class="section">
            <h2 class="section-title">Prioritised Recommended Actions (Max 8)</h2>
            <table>
                <thead>
                    <tr>
                        <th style="width: 8%;">Rank</th>
                        <th style="width: 35%;">Action</th>
                        <th style="width: 42%;">Reason</th>
                        <th style="width: 15%;">Fix Action</th>
                    </tr>
                </thead>
                <tbody>
                    {actions_rows}
                </tbody>
            </table>
        </section>

        <!-- Section 2: Purpose Coverage -->
        <section class="section">
            <h2 class="section-title">Purpose Specification Coverage</h2>
            <p style="font-size: 13px; margin-bottom: 8px;">
                Confirmed: <strong>{confirmed_purposes}</strong> | Inferred: <strong>{inferred_purposes}</strong> | Unknown: <strong>{unknown_purposes}</strong>
            </p>
            <table>
                <thead>
                    <tr>
                        <th>Source</th><th>Total Fields</th><th>Confirmed</th><th>Inferred</th><th>Unknown</th>
                    </tr>
                </thead>
                <tbody>
                    {cov_rows}
                </tbody>
            </table>
        </section>

        <!-- Section 3: Compliance Flags -->
        <section class="section">
            <h2 class="section-title">Compliance Rule Assessments</h2>
            <table>
                <thead>
                    <tr>
                        <th style="width: 18%;">State</th>
                        <th style="width: 32%;">Rule & Assessment</th>
                        <th style="width: 20%;">Citation</th>
                        <th style="width: 30%;">Remediation</th>
                    </tr>
                </thead>
                <tbody>
                    {flags_rows}
                </tbody>
            </table>
        </section>

        <!-- Section 4: Rights Desk Cases -->
        <section class="section">
            <h2 class="section-title">Data Principal Rights Cases</h2>
            <table>
                <thead>
                    <tr>
                        <th>Case</th><th>Intent</th><th>Status</th><th>Due Date</th>
                    </tr>
                </thead>
                <tbody>
                    {cases_rows}
                </tbody>
            </table>
        </section>

        <!-- Section 5: Erasure Receipts -->
        <section class="section">
            <h2 class="section-title">Erasure Compliance Receipts</h2>
            <table>
                <thead>
                    <tr>
                        <th>Plan ID</th><th>Executed Date</th><th>Plan Hash</th><th>Actions</th><th>Residual</th>
                    </tr>
                </thead>
                <tbody>
                    {receipts_rows}
                </tbody>
            </table>
        </section>

        <!-- Section 6: Breach Simulations -->
        <section class="section">
            <h2 class="section-title">Breach Simulations (Marked SIMULATION)</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th><th>Scenario</th><th>Severity</th><th>Impact</th><th>Date</th>
                    </tr>
                </thead>
                <tbody>
                    {sims_rows}
                </tbody>
            </table>
        </section>

        <!-- Section 7: Ledger Status -->
        <section class="section">
            <h2 class="section-title">Cryptographic Audit Ledger</h2>
            <p style="font-size: 13px;">
                Status: <strong>{ledger_ok_text}</strong> ({ledger.get('checked', 0)} events verified) &bull; Head Hash: <code>{head_hash_text}</code>
            </p>
        </section>

        <!-- Section 8: Limitations & Scope -->
        <section class="section">
            <h2 class="section-title">Scope & Limitations</h2>
            <div style="font-size: 12px; color: #475569; line-height: 1.6;">
                {limitations_paras}
            </div>
        </section>

        <footer class="footer">
            <p>Readiness aid, not legal advice. Citations unverified.</p>
        </footer>
    </div>
</body>
</html>
"""
    return html
