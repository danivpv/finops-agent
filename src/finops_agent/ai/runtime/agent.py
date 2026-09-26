"""Strands-based FinOps investigation agent running inside AgentCore Runtime.

Plans at most two typed queries. The single tool `run_finops_query` calls the
Data Lambda: through the AgentCore Gateway when `GATEWAY_URL` is set, and
through `make dev-api` otherwise. It never imports the store and never sees
raw rows. Streams the same `status`/`sql`/`text`/`meta` SSE event contract
the frontend drawer already reads (`AssistantDrawer.tsx` via `lib/api.ts`'s
`investigate()`).

Local runs use this same module: `python -m finops_agent.ai.runtime.agent`
starts the HTTP contract on `AGENT_PORT` (`POST /invocations`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Literal

import boto3
import httpx
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from pydantic import ValidationError
from starlette.responses import StreamingResponse
from strands import Agent, tool
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from strands.types.content import Messages

from ...constants import GATEWAY_TOOL_NAME, INVESTIGATE_PATH
from ...schemas import ErrorBody, InvestigateQuery, InvestigateResult
from ..constants import ACTOR_ID, MAX_MEMORY_EVENTS, MAX_QUERY_STEPS, MODEL_ID
from ..exceptions import (
    FinopsException,
    PromptUnavailableError,
    QueryBudgetError,
    QueryFailedError,
    UnexpectedGatewayResponse,
)
from ..services.prompt import load_system_prompt
from .config import Settings, get_settings

Dimension = Literal[
    "service", "account", "region", "usage_kind", "instance_type", "commitment_scope"
]
Metric = Literal["on_demand_cost", "amortized_cost", "usage_amount"]

_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive"}


class _QueryBudget:
    """Enforces the "at most two typed queries" plan limit server-side.

    The system prompt also asks the model nicely, but this is what actually
    stops a third `run_finops_query` call from reaching the Data Lambda.
    """

    def __init__(self, max_steps: int = MAX_QUERY_STEPS) -> None:
        self.max_steps = max_steps
        self.used = 0

    def reserve(self) -> bool:
        if self.used >= self.max_steps:
            return False
        self.used += 1
        return True


def _read_body(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and "rows" in data:
        return InvestigateResult.model_validate(data).model_dump()
    if isinstance(data, dict) and "error" in data:
        return ErrorBody.model_validate(data).model_dump()
    raise UnexpectedGatewayResponse()


def _fetch(settings: Settings, query: InvestigateQuery) -> Any:
    payload = query.model_dump(exclude_none=True)
    if not settings.gateway_url:
        response = httpx.post(
            settings.data_api_base_url.rstrip("/") + INVESTIGATE_PATH,
            json=payload,
            timeout=30.0,
        )
        return response.json()
    endpoint = settings.gateway_url.rstrip("/")
    if not endpoint.endswith("/mcp"):
        endpoint = f"{endpoint}/mcp"
    with MCPClient(
        lambda: aws_iam_streamablehttp_client(
            endpoint=endpoint,
            aws_service="bedrock-agentcore",
        )
    ) as client:
        result = client.call_tool_sync("finops-query", GATEWAY_TOOL_NAME, payload)
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    text = next(
        (block.get("text") for block in result.get("content", []) if block.get("text")),
        "",
    )
    return json.loads(text) if text else {}


async def execute_query(settings: Settings, query: InvestigateQuery) -> dict[str, Any]:
    """Call the Data Lambda. Gateway when configured, otherwise `make dev-api`."""
    try:
        return _read_body(await asyncio.to_thread(_fetch, settings, query))
    except FinopsException as exc:
        return exc.as_dict()
    except (ValidationError, httpx.HTTPError, json.JSONDecodeError) as exc:
        return QueryFailedError(detail=f"{type(exc).__name__}: {exc}").as_dict()


def _make_query_tool(
    *,
    settings: Settings,
    screen_period: str,
    budget: _QueryBudget,
    sink: list[tuple[str, dict[str, Any]]],
):
    """Build the one query tool the model may call for this request.

    Closes over per-request state (the screen period as the default, the
    budget, and a `sink` list that the outer `stream_investigation` generator
    drains each loop iteration) so `status`/`sql` events surface inline with
    the model's streamed text, without threads or an `asyncio.Queue`.
    """

    @tool
    async def run_finops_query(
        group_by: Dimension,
        metric: Metric,
        period: str | None = None,
        comparison_period: str | None = None,
        top_n: int = 8,
    ) -> dict[str, Any]:
        """Run one grouped-aggregation query over the FinOps cost dice.

        Returns an aggregated result set only. You never see raw rows and you
        never write SQL. Call this at most twice total for one question.

        Args:
            group_by: dimension to group spend by.
            metric: cost or usage metric to aggregate.
            period: billing period, YYYY-MM. Omit this to use the screen period.
            comparison_period: earlier billing period, YYYY-MM. Omit unless
                the user is comparing two months.
            top_n: maximum rows to return (1-12).
        """
        chosen_period = (period or "").strip() or screen_period
        chosen_comparison = (comparison_period or "").strip() or None
        if not budget.reserve():
            return QueryBudgetError(max_steps=budget.max_steps).as_dict()
        sink.append(
            (
                "status",
                {"message": f"Running query {budget.used} of {budget.max_steps}..."},
            )
        )
        query = InvestigateQuery(
            group_by=group_by,
            metric=metric,
            period=chosen_period,
            comparison_period=chosen_comparison,
            top_n=top_n,
        )
        result = await execute_query(settings, query)
        parsed = InvestigateResult.model_validate(result) if "rows" in result else None
        if parsed is None:
            return ErrorBody.model_validate(result).model_dump()
        sink.append(("sql", {"sql": parsed.sql, "rows": len(parsed.rows)}))
        return {"rows": parsed.rows}

    return run_finops_query


def _events_to_messages(events: list[dict[str, Any]]) -> Messages:
    """AgentCore Memory events (newest-first from `list_events`) -> Strands history."""
    messages: Messages = []
    for event in sorted(events, key=lambda e: e["eventTimestamp"]):
        for item in event.get("payload", []):
            conversational = item.get("conversational")
            if not conversational:
                continue
            text = conversational.get("content", {}).get("text")
            if not text:
                continue
            role = "user" if conversational.get("role") == "USER" else "assistant"
            messages.append({"role": role, "content": [{"text": text}]})
    return messages


def _read_memory(
    client: Any, settings: Settings, session_id: str
) -> list[dict[str, Any]]:
    response = client.list_events(
        memoryId=settings.memory_id,
        actorId=ACTOR_ID,
        sessionId=session_id,
        maxResults=MAX_MEMORY_EVENTS,
        includePayloads=True,
    )
    return response.get("events", [])


def _write_memory_event(
    client: Any, settings: Settings, session_id: str, role: str, text: str
) -> None:
    if not text:
        return
    client.create_event(
        memoryId=settings.memory_id,
        actorId=ACTOR_ID,
        sessionId=session_id,
        eventTimestamp=datetime.now(timezone.utc),
        payload=[{"conversational": {"content": {"text": text}, "role": role}}],
    )


async def stream_investigation(
    question: str,
    context: dict[str, Any],
    session_id: str,
    settings: Settings | None = None,
    prompt_client: Any | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield `(event_name, data)` pairs: `status`(es), `sql`(s), `text` deltas, `meta`.

    When `MEMORY_ID` is unset, memory reads and writes are skipped. History is
    only the current actor and session: no cross-session recall, no long-term
    strategies.

    A prompt-load failure yields `meta.error` and returns. The drawer shows
    that string as status. The model is not called.
    """
    settings = settings or get_settings()
    try:
        system_prompt = load_system_prompt(
            prompt_client or boto3.client("bedrock-agent"),
            settings.prompt_arn,
        )
    except PromptUnavailableError as exc:
        yield "meta", {"error": exc.message}
        return

    started = time.perf_counter()
    yield "status", {"message": "Planning investigation..."}

    screen_period = str(context.get("period") or "2026-05")

    budget = _QueryBudget()
    sink: list[tuple[str, dict[str, Any]]] = []
    query_tool = _make_query_tool(
        settings=settings,
        screen_period=screen_period,
        budget=budget,
        sink=sink,
    )

    history: Messages = []
    existing_event_count = 0
    memory_client = None
    if settings.memory_id:
        memory_client = boto3.client("bedrock-agentcore")
        existing_events = _read_memory(memory_client, settings, session_id)
        existing_event_count = len(existing_events)
        history = _events_to_messages(existing_events)

    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID),
        tools=[query_tool],
        messages=history,
        system_prompt=system_prompt,
    )

    prompt = f"Screen context: {json.dumps(context, default=str)}\nQuestion: {question}"

    full_text = ""
    async for event in agent.stream_async(prompt):
        while sink:
            yield sink.pop(0)
        delta = event.get("data")
        if delta:
            full_text += delta
            yield "text", {"delta": delta}
    while sink:
        yield sink.pop(0)

    # "refuse to append past 10": a full page back from list_events means the
    # session is already at (or over) the read cap, so skip writing more this
    # turn rather than paginating to find an exact total.
    if memory_client is not None and existing_event_count < MAX_MEMORY_EVENTS:
        _write_memory_event(memory_client, settings, session_id, "USER", question)
        _write_memory_event(memory_client, settings, session_id, "ASSISTANT", full_text)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    yield "meta", {"latency_ms": elapsed_ms, "query_count": budget.used}


def _sse(event_name: str, data: dict[str, Any]) -> bytes:
    return f"event: {event_name}\ndata: {json.dumps(data, default=str)}\n\n".encode()


async def _sse_body(
    question: str, context: dict[str, Any], session_id: str
) -> AsyncIterator[bytes]:
    try:
        async for event_name, data in stream_investigation(
            question, context, session_id
        ):
            yield _sse(event_name, data)
    except Exception as exc:  # noqa: BLE001 — degrade, never drop the stream uncleanly
        yield _sse("meta", {"error": f"{type(exc).__name__}: {exc}"[:300]})


app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload: dict[str, Any], context: Any) -> StreamingResponse:
    """AgentCore Runtime entrypoint.

    Returns a `StreamingResponse` directly (rather than being an async
    generator itself) so `BedrockAgentCoreApp` passes our own SSE framing
    through untouched instead of its default `data: {json}\\n\\n` wrapper,
    which has no `event:` line and would break `lib/api.ts`'s parser.

    `session_id` comes from AgentCore's own session header
    (`X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`, surfaced here as
    `context.session_id`) — set by the Next.js proxy from the browser's
    `sessionStorage` id via `runtimeSessionId` on `InvokeAgentRuntimeCommand`.
    """
    question = payload.get(
        "question", "Which are the most expensive on demand services in september 9?"
    )
    screen_context = payload.get("context", {})
    session_id = getattr(context, "session_id", None) or "local"
    return StreamingResponse(
        _sse_body(question, screen_context, session_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(port=get_settings().agent_port)
