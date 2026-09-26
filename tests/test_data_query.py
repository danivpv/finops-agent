"""The Data Lambda is the only query entry. Both front doors call `run_query`."""

import json
from types import SimpleNamespace

from finops_agent.constants import (
    GATEWAY_TARGET_NAME,
    GATEWAY_TOOL_NAME,
    QUERY_TOOL_NAME,
)
from finops_agent.data.runtime import handler, routes


def _gateway_context(tool_name: str = GATEWAY_TOOL_NAME):
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool_name})
    )


def _http(path: str, body: dict) -> dict:
    return {
        "resource": "/{proxy+}",
        "path": path,
        "httpMethod": "POST",
        "headers": {"content-type": "application/json"},
        "requestContext": {"httpMethod": "POST", "path": path},
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def _fake_investigate(**kwargs):
    return ([{"service": "AmazonEC2", "value": 12}], "SELECT 1")


def test_gateway_invocation_returns_rows_and_sql_without_auth(monkeypatch) -> None:
    monkeypatch.setenv(
        "CC_AUTH_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:1:secret:x"
    )
    monkeypatch.setattr(routes._store, "investigate", _fake_investigate)

    result = handler.handler(
        {
            "group_by": "service",
            "metric": "on_demand_cost",
            "period": "2026-05",
            "top_n": 8,
        },
        _gateway_context(),
    )

    assert "statusCode" not in result
    assert result["sql"] == "SELECT 1"
    assert result["rows"] == [{"service": "AmazonEC2", "value": 12}]


def test_gateway_shape_without_context_still_runs_the_query(monkeypatch) -> None:
    monkeypatch.setattr(routes._store, "investigate", _fake_investigate)
    result = handler.handler(
        {"group_by": "service", "metric": "amortized_cost", "period": "2026-05"},
        SimpleNamespace(client_context=None),
    )
    assert result["rows"][0]["service"] == "AmazonEC2"


def test_unknown_gateway_tool_does_not_query(monkeypatch) -> None:
    def _boom(**kwargs):
        raise AssertionError("store should not run")

    monkeypatch.setattr(routes._store, "investigate", _boom)
    result = handler.handler(
        {"group_by": "service", "metric": "on_demand_cost", "period": "2026-05"},
        _gateway_context(f"{GATEWAY_TARGET_NAME}___other"),
    )
    assert result["code"] == "DAT-1400"
    assert result["error"] == "Unknown tool: other"


def test_http_investigate_returns_the_same_body(monkeypatch) -> None:
    monkeypatch.setattr(routes._store, "investigate", _fake_investigate)
    response = handler.handler(
        _http(
            "/investigate",
            {
                "group_by": "service",
                "metric": "on_demand_cost",
                "period": "2026-05",
                "comparison_period": "2026-04",
            },
        ),
        None,
    )
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["sql"] == "SELECT 1"


def test_http_investigate_rejects_unknown_dimension(monkeypatch) -> None:
    def _boom(**kwargs):
        raise AssertionError("store should not run")

    monkeypatch.setattr(routes._store, "investigate", _boom)
    response = handler.handler(
        _http(
            "/investigate",
            {"group_by": "nope", "metric": "on_demand_cost", "period": "2026-05"},
        ),
        None,
    )
    assert response["statusCode"] == 400
    assert "Unknown dimension" in json.loads(response["body"])["error"]


def test_query_tool_name_matches_the_gateway_prefix() -> None:
    assert GATEWAY_TOOL_NAME.endswith(f"___{QUERY_TOOL_NAME}")
