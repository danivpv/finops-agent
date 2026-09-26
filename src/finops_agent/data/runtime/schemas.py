"""HTTP request bodies for the Data API. The shared query model stays in `schemas.py`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..services.domain import DEFAULT_PROPOSAL, Proposal


class EconomicsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scope: str = DEFAULT_PROPOSAL.scope
    commitment_per_hour: float = DEFAULT_PROPOSAL.commitment_per_hour
    term_months: int = DEFAULT_PROPOSAL.term_months
    payment_option: str = DEFAULT_PROPOSAL.payment_option

    def proposal(self) -> Proposal:
        return Proposal(
            scope=self.scope,
            commitment_per_hour=self.commitment_per_hour,
            term_months=self.term_months,
            payment_option=self.payment_option,
        )


class SliceBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    group_by: str = "service"
    metric: str = "on_demand_cost"
    window: tuple[str, str] | None = None
    top_n: int = 12


class DeltaBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    group_by: str = "service"
    metric: str = "on_demand_cost"
    window_a: tuple[str, str]
    window_b: tuple[str, str]
    top_n: int = 12


class DrillBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    group_by: str = "service"
    value: str = ""
    window: tuple[str, str] | None = None
    limit: int = 30


class GatewayCustom(BaseModel):
    """Tool name from an AgentCore Gateway Lambda context. Other fields are ignored."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    bedrock_agent_core_tool_name: str | None = Field(
        default=None, alias="bedrockAgentCoreToolName"
    )


class GatewayClientContext(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    custom: GatewayCustom | None = None


class LambdaContextView(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    client_context: GatewayClientContext | None = None

    @property
    def tool_name(self) -> str | None:
        custom = self.client_context.custom if self.client_context else None
        raw = custom.bedrock_agent_core_tool_name if custom else None
        if not raw:
            return None
        if "___" in raw:
            return raw.split("___", 1)[1]
        return raw


class HttpEvent(BaseModel):
    """API Gateway fields that mark an HTTP call. The rest of the event is kept."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    http_method: str | None = Field(default=None, alias="httpMethod")
    path: str | None = None
    raw_path: str | None = Field(default=None, alias="rawPath")
    request_context: dict[str, Any] | None = Field(default=None, alias="requestContext")

    @property
    def is_http(self) -> bool:
        return bool(
            self.http_method or self.request_context or self.raw_path or self.path
        )
