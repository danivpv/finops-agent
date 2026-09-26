"""Prompt load fails closed, without calling Bedrock."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from finops_agent.ai.constants import PROMPT_UNAVAILABLE_MESSAGE
from finops_agent.ai.exceptions import PromptUnavailableError
from finops_agent.ai.runtime.agent import stream_investigation
from finops_agent.ai.runtime.config import Settings
from finops_agent.ai.services.prompt import base_prompt_arn, load_system_prompt

_ARN = "arn:aws:bedrock:us-east-1:111122223333:prompt/ABCDEFGHIJ"


class _PromptClient:
    def __init__(self, pages: list[dict], prompt: dict | None = None, error: str = ""):
        self.pages = pages
        self.prompt = prompt or {}
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def get_paginator(self, name: str) -> _PromptClient:
        assert name == "list_prompts"
        return self

    def paginate(self, **kwargs: object) -> list[dict]:
        self.calls.append(("list", dict(kwargs)))
        if self.error == "list":
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "nope"}},
                "ListPrompts",
            )
        return self.pages

    def get_prompt(self, **kwargs: object) -> dict:
        self.calls.append(("get", dict(kwargs)))
        if self.error == "get":
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "nope"}},
                "GetPrompt",
            )
        return self.prompt


def test_base_arn_strips_a_version_suffix() -> None:
    assert base_prompt_arn(f"{_ARN}:3") == _ARN
    assert base_prompt_arn(f"{_ARN}:DRAFT") == _ARN
    assert base_prompt_arn(_ARN) == _ARN


def test_load_uses_the_highest_published_version() -> None:
    client = _PromptClient(
        [
            {"promptSummaries": [{"version": "DRAFT"}, {"version": "2"}]},
            {"promptSummaries": [{"version": "9"}]},
        ],
        {"variants": [{"templateConfiguration": {"text": {"text": "published"}}}]},
    )
    assert load_system_prompt(client, f"{_ARN}:1") == "published"
    assert client.calls[-1] == (
        "get",
        {"promptIdentifier": _ARN, "promptVersion": "9"},
    )


def test_draft_only_raises_the_catalog_error() -> None:
    client = _PromptClient([{"promptSummaries": [{"version": "DRAFT"}]}])
    with pytest.raises(PromptUnavailableError) as raised:
        load_system_prompt(client, _ARN)
    assert raised.value.message == PROMPT_UNAVAILABLE_MESSAGE
    assert raised.value.error_code == "AGT-2504"
    assert client.calls == [("list", {"promptIdentifier": _ARN})]


def test_aws_error_is_logged_and_not_returned(caplog: pytest.LogCaptureFixture) -> None:
    client = _PromptClient([], error="list")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(PromptUnavailableError) as raised:
            load_system_prompt(client, _ARN)
    assert raised.value.message == PROMPT_UNAVAILABLE_MESSAGE
    assert "nope" not in raised.value.message
    assert "nope" in caplog.text
    assert "AGT-2504" in caplog.text


def test_empty_arn_does_not_call_bedrock() -> None:
    client = _PromptClient([])
    with pytest.raises(PromptUnavailableError):
        load_system_prompt(client, "  ")
    assert client.calls == []


def test_stream_emits_status_error_and_does_not_answer() -> None:
    client = _PromptClient([], error="get")
    client.pages = [{"promptSummaries": [{"version": "1"}]}]
    configured = Settings(
        _env_file=None,
        region="us-east-1",
        prompt_arn=_ARN,
        agent_port=8088,
        local_api_port=3001,
    )

    async def collect() -> list[tuple[str, dict]]:
        return [
            item
            async for item in stream_investigation(
                "Why did this change?",
                {"period": "2026-05"},
                "session",
                settings=configured,
                prompt_client=client,
            )
        ]

    events = asyncio.run(collect())
    assert events == [("meta", {"error": PROMPT_UNAVAILABLE_MESSAGE})]
    payload = json.dumps(events)
    assert "You are a FinOps" not in payload
    assert "nope" not in payload
    assert "PromptUnavailableError" not in payload


def test_agent_source_has_no_prompt_fallback() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "finops_agent"
        / "ai"
        / "runtime"
        / "agent.py"
    ).read_text(encoding="utf-8")
    assert "SYSTEM_PROMPT" not in source
    assert "You are a FinOps" not in source


def test_env_rewrite_changes_only_the_prompt_arn_line() -> None:
    path = Path(__file__).parents[1] / "scripts" / "upload_prompt.py"
    spec = importlib.util.spec_from_file_location("upload_prompt", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = "GITHUB_TOKEN_SECRET_ARN=abc\nLOCAL_API_PORT=3001\nPROMPT_ARN=old\n"
    updated = module.set_prompt_arn_text(original, _ARN)
    assert updated == (
        f"GITHUB_TOKEN_SECRET_ARN=abc\nLOCAL_API_PORT=3001\nPROMPT_ARN={_ARN}\n"
    )
