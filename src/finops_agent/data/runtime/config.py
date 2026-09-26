"""Env for the Data Lambda. Fixed rates stay in `data/constants.py`."""

from __future__ import annotations

from pathlib import Path

from ...config import EnvSettings

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "precomputed"


class Settings(EnvSettings):
    cc_data_dir: Path = _DEFAULT_DATA_DIR
    """`CC_DATA_DIR`. Baked dice and lines. The image and CDK set this."""


settings = Settings()
