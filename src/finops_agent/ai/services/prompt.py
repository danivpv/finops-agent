"""Load the published system prompt from Bedrock Prompt Management."""

from __future__ import annotations

import logging
from typing import Any, NoReturn

from botocore.exceptions import BotoCoreError, ClientError

from ..exceptions import PromptUnavailableError

logger = logging.getLogger(__name__)


def base_prompt_arn(arn: str | None) -> str:
    """`...:prompt/ID:1` and `...:prompt/ID:DRAFT` become `...:prompt/ID`."""
    text = (arn or "").strip()
    head, _, tail = text.rpartition(":")
    if (tail.isdigit() or tail == "DRAFT") and ":prompt/" in head:
        return head
    return text


def load_system_prompt(client: Any, prompt_arn: str | None) -> str:
    """Text of the highest numbered version. The DRAFT is ignored.

    Failure raises `PromptUnavailableError`. Its message is the customer
    sentence. The AWS error stays in the log.
    """
    arn = base_prompt_arn(prompt_arn)
    if not arn:
        _fail(arn, "PROMPT_ARN is empty")
    try:
        version = _latest_published_version(client, arn)
        response = client.get_prompt(promptIdentifier=arn, promptVersion=version)
    except (ClientError, BotoCoreError) as exc:
        _fail(arn, "prompt read failed", exc)
    text = _variant_text(response)
    if not text.strip():
        _fail(arn, "published prompt text is empty")
    return text


def _latest_published_version(client: Any, prompt_arn: str) -> str:
    versions = [
        int(version)
        for page in client.get_paginator("list_prompts").paginate(
            promptIdentifier=prompt_arn
        )
        for summary in page.get("promptSummaries", [])
        if (version := str(summary.get("version", ""))).isdigit()
    ]
    if not versions:
        _fail(prompt_arn, "no published version")
    return str(max(versions))


def _variant_text(response: dict[str, Any]) -> str:
    variants = response.get("variants") or []
    if not variants:
        return ""
    body = (variants[0].get("templateConfiguration") or {}).get("text") or {}
    text = body.get("text") or ""
    return text if isinstance(text, str) else ""


def _fail(prompt_arn: str, reason: str, exc: BaseException | None = None) -> NoReturn:
    error = PromptUnavailableError()
    logger.error(
        "Bedrock prompt unavailable code=%s arn=%s reason=%s",
        error.error_code,
        prompt_arn or "(empty)",
        reason,
        exc_info=exc,
    )
    raise error from exc
