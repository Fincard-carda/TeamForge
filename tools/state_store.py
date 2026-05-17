"""Disk tabanli simple state store.

JSON filelarini atomic yazim ile currentlemek for thread-safe bir wrapper.
Her tool this modul over state/ altindaki filelari okur and yazar.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)

_locks: dict[str, threading.Lock] = {}


def _lock_for(name: str) -> threading.Lock:
    if name not in _locks:
        _locks[name] = threading.Lock()
    return _locks[name]


def path_for(name: str) -> Path:
    return STATE_DIR / f"{name}.json"


def read(name: str, default: Any) -> Any:
    p = path_for(name)
    with _lock_for(name):
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default


def write(name: str, data: Any) -> None:
    p = path_for(name)
    with _lock_for(name):
        fd, tmp = tempfile.mkstemp(dir=str(STATE_DIR), prefix=f".{name}.", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, p)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def update(name: str, mutator, default: Any):
    """Read-modify-write yardimcisi. mutator(data) -> new_data."""
    with _lock_for(name):
        p = path_for(name)
        data = default
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = default
        new_data = mutator(data)
        fd, tmp = tempfile.mkstemp(dir=str(STATE_DIR), prefix=f".{name}.", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(new_data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, p)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return new_data
