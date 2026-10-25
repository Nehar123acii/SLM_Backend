"""
backend/services/graphs.py
==========================
Graph data service for DPDP compliance visualization:
- Heatmap: source x category matrix with people counts and impact tiers
- Purpose Coverage: per-source counts of confirmed, inferred, and unknown purpose fields
- Source-Purpose: Cytoscape-ready nodes and edges for source -> category -> purpose
- Rows: Paged click-through returning masked rows only (row_ref, masked_sample, origin)
- Blast Radius: Per-source summary reusing K9 blast_radius engine
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import (
    Column,
    Dataset,
    Occurrence,
    Person,
    Purpose,
    PurposeLink,
)
from backend.services.breach import blast_radius
from backend.services.provenance import compute_impact_tier

IMPACT_TIER_NOTE = (
    "Impact tier is Kavach's own 'impact if leaked' tier (1-3), "
    "not a statutory or legal classification."
)


def get_heatmap_data(session: Session) -> Dict[str, Any]:
    """
    Computes source x category matrix.
    Returns:
    - sources: list of dataset sources (source_id, filename)
    - categories: sorted list of distinct categories found
    - cells / matrix: per-cell people count and impact tier
    - notes: explicitly explaining that impact tier is Kavach's own tier, not a legal class.
    """
    datasets = session.query(Dataset).order_by(Dataset.id.asc()).all()
    if not datasets:
        return {
            "sources": [],
            "categories": [],
            "cells": [],
            "matrix": [],
            "notes": IMPACT_TIER_NOTE,
        }

    # Fetch all columns and group by dataset and category
    columns = session.query(Column).all()
    col_map: Dict[int, Column] = {c.id: c for c in columns}

    dataset_cols: Dict[str, List[Column]] = {}
    all_categories: Set[str] = set()
    for c in columns:
        cat = (c.category or "other").lower().strip()
        all_categories.add(cat)
        dataset_cols.setdefault(c.dataset_id, []).append(c)

    sorted_categories = sorted(list(all_categories))

    # Fetch all occurrences with person_id
    occurrences = session.query(Occurrence).all()
    # (dataset_id, category) -> Set[person_id]
    cell_people: Dict[Tuple[str, str], Set[int]] = {}
    cell_occs: Dict[Tuple[str, str], int] = {}

    for occ in occurrences:
        col = col_map.get(occ.column_id)
        if not col:
            continue
        ds_id = col.dataset_id
        cat = (col.category or "other").lower().strip()
        key = (ds_id, cat)
        cell_occs[key] = cell_occs.get(key, 0) + 1
        if occ.person_id is not None:
            cell_people.setdefault(key, set()).add(occ.person_id)

    cells: List[Dict[str, Any]] = []
    matrix: List[Dict[str, Any]] = []

    for ds in datasets:
        ds_id = ds.dataset_id
        row_cells = []
        for cat in sorted_categories:
            key = (ds_id, cat)
            people_set = cell_people.get(key, set())
            people_cnt = len(people_set)
            occ_cnt = cell_occs.get(key, 0)

            # Determine impact tier: from column or compute_impact_tier
            matching_cols = [c for c in dataset_cols.get(ds_id, []) if (c.category or "other").lower() == cat]
            impact_tier = "1"
            if matching_cols:
                tiers = [c.impact_tier for c in matching_cols if c.impact_tier]
                impact_tier = max(tiers, key=lambda t: int(t) if str(t).isdigit() else 1) if tiers else compute_impact_tier(cat)
            else:
                impact_tier = compute_impact_tier(cat)

            cell_obj = {
                "source_id": ds_id,
                "filename": ds.original_filename,
                "category": cat,
                "people_count": people_cnt,
                "occurrence_count": occ_cnt,
                "impact_tier": str(impact_tier),
            }
            cells.append(cell_obj)
            row_cells.append(cell_obj)

        matrix.append({
            "source_id": ds_id,
            "filename": ds.original_filename,
            "row": row_cells,
        })

    return {
        "sources": [{"source_id": ds.dataset_id, "filename": ds.original_filename} for ds in datasets],
        "categories": sorted_categories,
        "cells": cells,
        "matrix": matrix,
        "notes": IMPACT_TIER_NOTE,
    }


def get_purpose_coverage(session: Session) -> List[Dict[str, Any]]:
    """
    Per source, counts fields with confirmed, inferred, and unknown purpose.
    A field with no answer/no link counts as unknown.
    """
    datasets = session.query(Dataset).order_by(Dataset.id.asc()).all()
    if not datasets:
        return []

    # Active purpose links (superseded_by is null)
    purpose_links = (
        session.query(PurposeLink)
        .filter(PurposeLink.superseded_by.is_(None))
        .all()
    )
    col_to_link: Dict[int, PurposeLink] = {pl.column_id: pl for pl in purpose_links}

    coverage_list: List[Dict[str, Any]] = []

    for ds in datasets:
        columns = session.query(Column).filter(Column.dataset_id == ds.dataset_id).all()
        confirmed_count = 0
        inferred_count = 0
        unknown_count = 0

        for col in columns:
            link = col_to_link.get(col.id)
            if not link or not link.purpose_id:
                unknown_count += 1
            elif (link.status or "").lower() == "confirmed":
                confirmed_count += 1
            elif (link.status or "").lower() == "inferred":
                inferred_count += 1
            else:
                unknown_count += 1

        coverage_list.append({
            "source_id": ds.dataset_id,
            "filename": ds.original_filename,
            "total_fields": len(columns),
            "confirmed": confirmed_count,
            "inferred": inferred_count,
            "unknown": unknown_count,
        })

    return coverage_list


def get_source_purpose_graph(session: Session) -> Dict[str, Any]:
    """
    Constructs nodes and edges for source -> category -> purpose, ready for Cytoscape.js.
    """
    datasets = session.query(Dataset).order_by(Dataset.id.asc()).all()
    if not datasets:
        return {
            "nodes": [],
            "edges": [],
            "elements": {"nodes": [], "edges": []},
        }

    columns = session.query(Column).all()
    purposes = session.query(Purpose).all()
    purpose_map: Dict[int, Purpose] = {p.id: p for p in purposes}

    active_links = (
        session.query(PurposeLink)
        .filter(PurposeLink.superseded_by.is_(None))
        .all()
    )
    col_to_link: Dict[int, PurposeLink] = {pl.column_id: pl for pl in active_links}

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_node_ids: Set[str] = set()
    seen_edge_ids: Set[str] = set()

    # 1. Source nodes
    for ds in datasets:
        nid = f"source_{ds.dataset_id}"
        if nid not in seen_node_ids:
            seen_node_ids.add(nid)
            nodes.append({
                "data": {
                    "id": nid,
                    "label": ds.original_filename,
                    "type": "source",
                    "source_id": ds.dataset_id,
                }
            })

    # 2. Category nodes and Source -> Category edges
    for col in columns:
        cat = (col.category or "other").lower().strip()
        cat_nid = f"cat_{cat}"
        if cat_nid not in seen_node_ids:
            seen_node_ids.add(cat_nid)
            nodes.append({
                "data": {
                    "id": cat_nid,
                    "label": cat.replace("_", " ").title(),
                    "type": "category",
                    "category": cat,
                }
            })

        # Source -> Category edge
        src_nid = f"source_{col.dataset_id}"
        edge_id = f"edge_{col.dataset_id}_{cat}"
        if edge_id not in seen_edge_ids:
            seen_edge_ids.add(edge_id)
            edges.append({
                "data": {
                    "id": edge_id,
                    "source": src_nid,
                    "target": cat_nid,
                    "label": "contains",
                }
            })

        # Category -> Purpose edge
        link = col_to_link.get(col.id)
        if link and link.purpose_id and link.purpose_id in purpose_map:
            p_obj = purpose_map[link.purpose_id]
            purp_nid = f"purpose_{p_obj.id}"
            if purp_nid not in seen_node_ids:
                seen_node_ids.add(purp_nid)
                nodes.append({
                    "data": {
                        "id": purp_nid,
                        "label": p_obj.label_key.replace("_", " ").title(),
                        "type": "purpose",
                        "purpose_id": p_obj.id,
                        "label_key": p_obj.label_key,
                    }
                })

            cat_purp_edge_id = f"edge_{cat}_{p_obj.id}_{link.status}"
            if cat_purp_edge_id not in seen_edge_ids:
                seen_edge_ids.add(cat_purp_edge_id)
                edges.append({
                    "data": {
                        "id": cat_purp_edge_id,
                        "source": cat_nid,
                        "target": purp_nid,
                        "label": link.status or "linked",
                    }
                })

    return {
        "nodes": nodes,
        "edges": edges,
        "elements": {
            "nodes": nodes,
            "edges": edges,
        },
    }


def get_column_masked_rows(
    session: Session,
    column_id: int,
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """
    Returns paged click-through rows for a column.
    Strictly returns masked values only: row_ref, masked_sample, origin.
    Zero raw personal data.
    """
    col = session.get(Column, column_id)
    if not col:
        raise ValueError(f"Column id {column_id} not found")

    query = session.query(Occurrence).filter(Occurrence.column_id == column_id)
    total_rows = query.count()

    offset = max(0, (page - 1) * page_size)
    occs = query.order_by(Occurrence.id.asc()).offset(offset).limit(page_size).all()

    rows = [
        {
            "row_ref": occ.row_ref or "",
            "masked_sample": occ.masked_sample or "",
            "origin": occ.origin or "rule",
        }
        for occ in occs
    ]

    return {
        "column_id": col.id,
        "column_name": col.column_name,
        "category": col.category or "other",
        "dataset_id": col.dataset_id,
        "total_rows": total_rows,
        "page": page,
        "page_size": page_size,
        "rows": rows,
    }


def get_blast_radius_all_sources(session: Session) -> List[Dict[str, Any]]:
    """
    Per source, 'if this leaks: N confirmed people, M possible people, high-impact categories'.
    Reuses K9 blast_radius function directly without duplication.
    """
    datasets = session.query(Dataset).order_by(Dataset.id.asc()).all()
    if not datasets:
        return []

    summaries: List[Dict[str, Any]] = []
    for ds in datasets:
        # Reuse K9 blast_radius function
        b = blast_radius(session, [ds.dataset_id])

        confirmed = b.get("confirmed_people", 0)
        possible = b.get("possible_people", 0)
        hi_cats = b.get("high_impact_categories", [])
        minors = b.get("minors_involved", 0)
        records = b.get("records_count", 0)

        hi_str = ", ".join(c.replace("_", " ").upper() for c in hi_cats) if hi_cats else "None"
        leak_msg = f"If this leaks: {confirmed} confirmed people, {possible} possible people, high-impact categories: {hi_str}"

        summaries.append({
            "source_id": ds.dataset_id,
            "filename": ds.original_filename,
            "records_count": records,
            "confirmed_people": confirmed,
            "possible_people": possible,
            "total_people": confirmed + possible,
            "high_impact_categories": hi_cats,
            "minors_involved": minors,
            "leak_summary": leak_msg,
        })

    return summaries
