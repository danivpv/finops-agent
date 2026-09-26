"""Data API routes. Paths are the frontend contract."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder

from ...constants import INVESTIGATE_PATH
from ...schemas import InvestigateQuery, InvestigateResult
from ..services.domain import DEFAULT_PROPOSAL, economics, get_connection
from ..services.store import Store
from .schemas import DeltaBody, DrillBody, EconomicsBody, SliceBody

router = APIRouter()
_store = Store()


def run_query(query: InvestigateQuery) -> InvestigateResult:
    """The one typed query. HTTP and the Gateway both call this."""
    rows, sql = _store.investigate(
        group_by=query.group_by,
        metric=query.metric,
        period=query.period,
        comparison_period=query.comparison_period,
        top_n=query.top_n,
    )
    return InvestigateResult.model_validate(
        jsonable_encoder({"rows": rows, "sql": sql})
    )


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "ready": _store.impact_ready()}


@router.get("/economics")
def get_economics() -> dict[str, Any]:
    return economics(get_connection(), DEFAULT_PROPOSAL)


@router.post("/econ/economics")
def post_economics(body: EconomicsBody) -> dict[str, Any]:
    return economics(get_connection(), body.proposal())


@router.post(INVESTIGATE_PATH)
def investigate(query: InvestigateQuery) -> InvestigateResult:
    return run_query(query)


@router.get("/vocab")
def vocab() -> dict[str, Any]:
    return _store.vocab()


@router.post("/slice")
def slice_route(body: SliceBody) -> dict[str, Any]:
    rows = _store.slice(body.group_by, body.metric, body.window, body.top_n)
    return {
        "rows": rows,
        "group_by": body.group_by,
        "metric": body.metric,
        "window": body.window,
    }


@router.post("/delta")
def delta_route(body: DeltaBody) -> dict[str, Any]:
    rows = _store.delta(
        body.group_by, body.metric, body.window_a, body.window_b, body.top_n
    )
    return {
        "rows": rows,
        "group_by": body.group_by,
        "metric": body.metric,
        "window_a": body.window_a,
        "window_b": body.window_b,
    }


@router.post("/drill")
def drill_route(body: DrillBody) -> dict[str, Any]:
    rows = _store.drill(body.group_by, body.value, body.window, body.limit)
    return {"rows": rows, "group_by": body.group_by, "value": body.value}


@router.get("/impact-status")
def impact_status() -> dict[str, bool]:
    return {"ready": _store.impact_ready()}


@router.post("/warm")
def warm() -> dict[str, Any]:
    return {"warming": False, "ready": _store.impact_ready()}


@router.get("/narration")
def narration() -> dict[str, Any]:
    rows = _store.slice("service", "on_demand_cost", top_n=50)
    total = sum(r["value"] for r in rows) if rows else 0
    top = rows[0] if rows else {"service": "N/A", "value": 0}
    items = [
        {
            "title": "Spend by service",
            "body": (
                f"{top['service']} is the largest service at ${top['value']:,.0f} "
                f"({top['value'] / total * 100:.0f}% of total spend)."
                if total
                else "No data."
            ),
        },
        {
            "title": "Long tail",
            "body": f"{len(rows)} services account for ${total:,.0f} of compute spend.",
        },
    ]
    return {"items": items}
