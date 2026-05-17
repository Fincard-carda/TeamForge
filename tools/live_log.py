"""Hierarchyk canli logger + dashboard broadcast koprusu."""
from __future__ import annotations

import contextvars
import json as _json
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_chain: contextvars.ContextVar[tuple] = contextvars.ContextVar(
    "teamforge_chain", default=()
)

_quiet = threading.Event()
if os.environ.get("TEAMFORGE_LIVE", "on").lower() in ("off", "false", "0"):
    _quiet.set()

_transcript_path: Path | None = None
_lock = threading.Lock()

_PALETTE = {
    "ceo": "\033[35m",
    "project_manager": "\033[34m",
    "business_analyst": "\033[36m",
    "android_dev": "\033[32m",
    "ios_dev": "\033[32m",
    "frontend_dev": "\033[32m",
    "backend_dev": "\033[32m",
    "uiux_dev": "\033[33m",
    "mobile_tester": "\033[31m",
    "tester": "\033[31m",
    "marketing_sales_specialist": "\033[33m",
}
_RESET = "\033[0m"
_DIM = "\033[2m"


def set_quiet(quiet: bool) -> None:
    if quiet:
        _quiet.set()
    else:
        _quiet.clear()


def is_quiet() -> bool:
    return _quiet.is_set()


def start_transcript(path: Path | None = None) -> Path:
    global _transcript_path
    if path is None:
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        path = LOGS_DIR / f"session-{ts}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Session transcript started {datetime.utcnow().isoformat()}Z\n",
                    encoding="utf-8")
    _transcript_path = path
    return path


def _color_for(role: str) -> str:
    return _PALETTE.get(role, "\033[37m")


def _indent_for_depth(depth: int) -> str:
    return "  " * max(0, depth - 1)


def _to_dashboard(event: dict) -> None:
    """Dashboard if exists event'i WS'e broadcast eder."""
    try:
        from . import dashboard
        srv = dashboard.get_server()
        if srv is not None:
            srv.emit(event)
    except Exception:
        pass  # dashboard optional — error cikarsa ignore


def _print(line: str) -> None:
    with _lock:
        if not _quiet.is_set():
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        if _transcript_path is not None:
            try:
                with _transcript_path.open("a", encoding="utf-8") as f:
                    clean = re.sub(r"\033\[\d+m", "", line)
                    f.write(clean + "\n")
            except Exception:
                pass


def enter(role: str, caller: str) -> int:
    chain = _chain.get()
    new_chain = chain + ((caller, role),)
    _chain.set(new_chain)
    depth = len(new_chain)

    color = _color_for(role)
    indent = _indent_for_depth(depth)
    _print(f"{indent}{color}[{role}]{_RESET} {_DIM}<- {caller}{_RESET}")
    _to_dashboard({"kind": "enter", "role": role, "caller": caller,
                   "depth": depth, "ts": time.time()})
    return depth


def exit_(role: str) -> None:
    chain = _chain.get()
    if chain:
        _chain.set(chain[:-1])
    depth = len(chain)
    color = _color_for(role)
    indent = _indent_for_depth(depth)
    _print(f"{indent}{color}[{role}]{_RESET} {_DIM}done{_RESET}")
    _to_dashboard({"kind": "exit", "role": role, "depth": depth, "ts": time.time()})


def text(role: str, content: str, max_chars: int = 600) -> None:
    chain = _chain.get()
    depth = max(1, len(chain))
    color = _color_for(role)
    indent = _indent_for_depth(depth) + "  "
    snippet = content.strip().replace("\n", " ")
    short = snippet if len(snippet) <= max_chars else snippet[:max_chars] + "..."
    _print(f"{indent}{color}{role}>{_RESET} {short}")
    _to_dashboard({"kind": "text", "role": role, "depth": depth,
                   "text": content, "ts": time.time()})


def tool(role: str, tool_name: str, args: dict | None = None) -> None:
    chain = _chain.get()
    depth = max(1, len(chain))
    color = _color_for(role)
    indent = _indent_for_depth(depth) + "  "
    arg_summary = ""
    if args:
        try:
            preview = {}
            for k, v in list(args.items())[:3]:
                if isinstance(v, str) and len(v) > 60:
                    preview[k] = v[:60] + "..."
                else:
                    preview[k] = v
            arg_summary = " " + _json.dumps(preview, ensure_ascii=False)[:120]
        except Exception:
            arg_summary = ""
    _print(f"{indent}{color}{role}>{_RESET} {_DIM}tool: {tool_name}{arg_summary}{_RESET}")
    _to_dashboard({"kind": "tool", "role": role, "depth": depth,
                   "tool": tool_name, "args": args or {}, "ts": time.time()})


def current_role() -> str | None:
    """Active call chain'in en lower role — code_io vs path guard'lari for.
    None: top-level (orchestrator user input)."""
    chain = _chain.get()
    if not chain:
        return None
    return chain[-1][1]  # last tuple'in (caller, role) -> role


def chain_str() -> str:
    chain = _chain.get()
    if not chain:
        return "(top)"
    return " -> ".join(role for _, role in chain)


class scope:
    def __init__(self, role: str, caller: str):
        self.role = role
        self.caller = caller

    def __enter__(self):
        enter(self.role, self.caller)
        return self

    def __exit__(self, exc_type, exc, tb):
        exit_(self.role)
        return False
