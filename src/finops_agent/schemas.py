"""Shared query contract. No DuckDB or FastAPI imports: both images load this module."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .constants import QUERY_DIMENSIONS, QUERY_METRICS
from .data.runtime.exceptions import UnknownDimensionError, UnknownMetricError


class InvestigateQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    group_by: str
    metric: str
    period: str
    comparison_period: str | None = None
    top_n: int = Field(default=8, ge=1, le=12)

    @field_validator("comparison_period", mode="before")
    @classmethod
    def empty_comparison(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("group_by")
    @classmethod
    def known_dimension(cls, value: str) -> str:
        if value not in QUERY_DIMENSIONS:
            raise UnknownDimensionError(name=value)
        return value

    @field_validator("metric")
    @classmethod
    def known_metric(cls, value: str) -> str:
        if value not in QUERY_METRICS:
            raise UnknownMetricError(name=value)
        return value


class InvestigateResult(BaseModel):
    rows: list[dict[str, Any]]
    sql: str


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: str
    code: str | None = None
