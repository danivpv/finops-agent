"""Publish `scripts/system_prompt.txt` to Bedrock Prompt Management.

Creates the prompt when `PROMPT_ARN` is empty, then writes the base ARN into
`.env`. Later runs update that prompt and publish the next version. The base
ARN does not change. Only the `PROMPT_ARN` line in `.env` is rewritten.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from finops_agent.ai.constants import PROMPT_NAME, PROMPT_VARIANT_NAME
from finops_agent.ai.services.prompt import base_prompt_arn
from finops_agent.config import Settings
from finops_agent.constants import REPO_ROOT

_PROMPT_FILE = REPO_ROOT / "scripts" / "system_prompt.txt"
_ENV_FILE = REPO_ROOT / ".env"


def read_prompt_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip("\n")
    if not text.strip():
        raise ValueError(f"Prompt file is empty: {path}")
    return text


def set_prompt_arn_text(env_text: str, arn: str) -> str:
    """Replace the `PROMPT_ARN` line, or append it. Leave every other line."""
    lines = env_text.splitlines(keepends=True)
    found = False
    updated: list[str] = []
    for line in lines:
        ending = "\n" if line.endswith("\n") else ""
        body = line[:-1] if ending else line
        if body.startswith("PROMPT_ARN="):
            updated.append(f"PROMPT_ARN={arn}{ending}")
            found = True
        else:
            updated.append(line)
    if not found:
        if updated and not updated[-1].endswith("\n"):
            updated[-1] += "\n"
        updated.append(f"PROMPT_ARN={arn}\n")
    return "".join(updated)


def write_prompt_arn(path: Path, arn: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(set_prompt_arn_text(existing, arn), encoding="utf-8")


def _variant(text: str) -> dict[str, Any]:
    return {
        "name": PROMPT_VARIANT_NAME,
        "templateType": "TEXT",
        "templateConfiguration": {"text": {"text": text}},
    }


def publish(client: Any, prompt_arn: str, text: str, env_path: Path) -> tuple[str, str]:
    """Create or update the prompt, publish a version, and persist the base ARN."""
    arn = base_prompt_arn(prompt_arn)
    variant = _variant(text)
    if not arn:
        created = client.create_prompt(
            name=PROMPT_NAME,
            description="System prompt for the FinOps assistant.",
            defaultVariant=PROMPT_VARIANT_NAME,
            variants=[variant],
        )
        arn = base_prompt_arn(created["arn"])
        write_prompt_arn(env_path, arn)
    else:
        client.update_prompt(
            promptIdentifier=arn,
            name=PROMPT_NAME,
            defaultVariant=PROMPT_VARIANT_NAME,
            variants=[variant],
        )
        write_prompt_arn(env_path, arn)
    published = client.create_prompt_version(
        promptIdentifier=arn,
        description="Published from scripts/system_prompt.txt",
    )
    return arn, str(published["version"])


class UploadSettings(Settings):
    """The first publish runs before `PROMPT_ARN` exists. The agent requires it."""

    prompt_arn: str = ""


def main() -> int:
    try:
        cfg = UploadSettings()
        text = read_prompt_text(_PROMPT_FILE)
        client = boto3.client("bedrock-agent")
        arn, version = publish(client, cfg.prompt_arn, text, _ENV_FILE)
    except (ClientError, BotoCoreError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"PROMPT_ARN={arn}")
    print(f"version={version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
