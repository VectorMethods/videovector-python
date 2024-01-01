"""Shared helpers for runnable VideoVector SDK examples."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Iterable

from videovector import VideoVector


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Set {name} before running this example.")
    return value


def optional_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def api_client() -> VideoVector:
    return VideoVector(api_key=require_env("VIDEO_VECTOR_API_KEY"))


def bearer_client() -> VideoVector:
    return VideoVector(bearer_token=require_env("VIDEO_VECTOR_BEARER_TOKEN"))


def idempotency_key(prefix: str) -> str:
    suffix = optional_env("VIDEO_VECTOR_IDEMPOTENCY_SUFFIX", "example")
    return f"{prefix}-{suffix}"


def load_base64_file(env_name: str) -> str:
    path = Path(require_env(env_name))
    return base64.b64encode(path.read_bytes()).decode("ascii")


def print_results(rows: Iterable[object], limit: int = 5) -> None:
    for index, row in enumerate(rows):
        if index >= limit:
            break
        print(row)

