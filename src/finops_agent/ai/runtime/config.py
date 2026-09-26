"""Env for the AgentCore process. Fixed policy stays in `ai/constants.py`.

Region, `PROMPT_ARN`, and the ports are inherited from the package settings.
This class adds only what this process reads on its own.
"""

from __future__ import annotations

from ...config import Settings as SharedSettings


class Settings(SharedSettings):
    memory_id: str | None = None
    """`MEMORY_ID`. Unset locally: memory calls are skipped."""

    gateway_url: str | None = None
    """`GATEWAY_URL`. Unset locally: the query tool calls the SAM API."""


settings: Settings | None = None


def get_settings() -> Settings:
    """Load `.env` once. Importing this module does not read it."""
    global settings
    if settings is None:
        settings = Settings()
    return settings
