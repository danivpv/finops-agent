"""Where environment variables live.

`EnvSettings` is how every process loads the repo-root `.env`. Empty values
count as missing.

`Settings` is the parent for values synth and the agent runtime both read.
Each name is declared once, with no default when the variable is required.

`SynthSettings` adds values only `app.py` reads. Runtime-only values stay on
the subsystem class: `ai/runtime/config.py`, `data/runtime/config.py`.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import REPO_ROOT


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        extra="ignore",
        env_ignore_empty=True,
        populate_by_name=True,
    )


class Settings(EnvSettings):
    """Required values shared by synth and the agent process.

    Account and region stay in the AWS profile. The CDK CLI and boto3 read
    them. They are not fields here.
    """

    prompt_arn: str = Field(min_length=1)
    agent_port: int
    local_api_port: int

    @property
    def data_api_base_url(self) -> str:
        return f"http://127.0.0.1:{self.local_api_port}"


class SynthSettings(Settings):
    """Deploy-time values. The CDK CLI fills account and region from the profile."""

    account: str = Field(
        min_length=12,
        max_length=12,
        validation_alias=AliasChoices("CDK_DEFAULT_ACCOUNT", "AWS_ACCOUNT_ID"),
    )
    region: str = Field(
        min_length=1,
        validation_alias=AliasChoices("CDK_DEFAULT_REGION", "AWS_REGION"),
    )
    github_token_secret_arn: str = Field(min_length=1)
