"""YAML config loader — env variable expansion ile.

config/*.yaml filelarini okur, ${VAR} referanslarini .env/os.environ
valueleriyle degistirir. Modulu import eden her place cache'den okur.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def sub(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), m.group(0))
        return _VAR_RE.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@lru_cache(maxsize=8)
def load(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _expand(raw or {})


def reload_all() -> None:
    load.cache_clear()


def team() -> dict[str, Any]:
    return load("team")


def tech_stack() -> dict[str, Any]:
    return load("tech_stack")


def budget() -> dict[str, Any]:
    return load("budget")


def policies() -> dict[str, Any]:
    return load("policies")
