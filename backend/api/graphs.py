"""
backend/api/graphs.py
====================
FastAPI router for Graph Data Visualization:
- GET /api/graphs/heatmap
- GET /api/graphs/purpose-coverage
- GET /api/graphs/source-purpose
- GET /api/graphs/rows
- GET /api/graphs/blast-radius
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.services.graphs import (
    get_blast_radius_all_sources,
    get_column_masked_rows,
    get_heatmap_data,
    get_purpose_coverage,
    get_source_purpose_graph,
)

router = APIRouter(prefix="/api/graphs", tags=["graphs"])


@router.get("/heatmap", status_code=status.HTTP_200_OK)
def heatmap_endpoint(db: Session = Depends(get_db)):
    """
    Returns source x category heatmap matrix with people count and impact tier per cell.
    Notes explain that impact tier is Kavach's own 'impact if leaked' tier, not a legal class.
    """
    data = get_heatmap_data(db)
    return data


@router.get("/purpose-coverage", status_code=status.HTTP_200_OK)
def purpose_coverage_endpoint(db: Session = Depends(get_db)):
    """
    Returns per-source counts of fields with confirmed, inferred, and unknown purpose.
    A field with no answer or no purpose link counts as unknown.
    """
    data = get_purpose_coverage(db)
    return data


@router.get("/source-purpose", status_code=status.HTTP_200_OK)
def source_purpose_graph_endpoint(db: Session = Depends(get_db)):
    """
    Returns nodes and edges for source -> category -> purpose, formatted for Cytoscape.js.
    """
    data = get_source_purpose_graph(db)
    return data


@router.get("/rows", status_code=status.HTTP_200_OK)
def column_masked_rows_endpoint(
    column_id: int = Query(..., description="ID of the column to inspect"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    db: Session = Depends(get_db),
):
    """
    Click-through returning masked rows only (row_ref, masked_sample, origin) with paging.
    Zero raw personal data is ever returned.
    """
    try:
        data = get_column_masked_rows(db, column_id=column_id, page=page, page_size=page_size)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch column rows: {str(e)}")


@router.get("/blast-radius", status_code=status.HTTP_200_OK)
def blast_radius_graph_endpoint(db: Session = Depends(get_db)):
    """
    Per-source blast radius: 'if this leaks: N confirmed people, M possible people, high-impact categories'.
    Reuses K9 blast_radius function without duplication.
    """
    data = get_blast_radius_all_sources(db)
    return data
