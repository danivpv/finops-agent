"""Repo-wide constants shared by every CDK stack and construct."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FRONTEND_REPOSITORY = "https://github.com/danivpv/finops-agent.git"
FRONTEND_BRANCH = "main"

# One typed query, exposed by the Data Lambda and called by the agent.
# Gateway tool names are `{target}___{tool}` (AgentCore's prefix).
QUERY_TOOL_NAME = "run_finops_query"
GATEWAY_TARGET_NAME = "finops-data"
GATEWAY_TOOL_NAME = f"{GATEWAY_TARGET_NAME}___{QUERY_TOOL_NAME}"
INVESTIGATE_PATH = "/investigate"

QUERY_DIMENSIONS = (
    "service",
    "account",
    "region",
    "usage_kind",
    "instance_type",
    "commitment_scope",
)
QUERY_METRICS = ("on_demand_cost", "amortized_cost", "usage_amount")
