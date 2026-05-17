"""Session brief tool'lari — agents session sonunda where kaldigini
saklayip next sessionda continue edebilme provides.

Her rol for bir brief filesi: state/briefs/<role>.md (markdown, human-is read).
Last record uzerine is written; eski recordlar state/briefs/history/ under tutulur.

Cascade closema akisi (user -> CEO -> PM -> BA -> workers):
  1) User: "This the session guvenli close"
  2) CEO delegate.to_pm("close your session and cascade")
  3) PM delegate.to_ba("close session, cascade to workers")
  4) BA her active worker'a delegate.to_worker(role, "close your session")
  5) Her agent brief.save calls, outsideya summary drecommend
  6) Upper layer kendi brief'ini yazar, more ustune summary verir

Next sessionda: orchestrator.load_prompt() automatically relevant role
ait last brief file prompt'a prepend eder — agent direkt "kaldigim
yerden continue ediyorum" diyebilir.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from . import state_store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRIEFS_DIR = PROJECT_ROOT / "state" / "briefs"
HISTORY_DIR = BRIEFS_DIR / "history"
BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _brief_path(role: str) -> Path:
    safe = role.replace("/", "_").replace("..", "_")
    return BRIEFS_DIR / f"{safe}.md"


def _archive(role: str) -> None:
    """Yeni yazim beforesi eski brief'i history/ altina tasi."""
    p = _brief_path(role)
    if not p.exists():
        return
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    target = HISTORY_DIR / f"{role}.{ts}.md"
    try:
        shutil.copy2(p, target)
    except Exception:  # pragma: no cover
        pass


def _audit(kind: str, role: str, detail: str = "") -> None:
    entry = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "kind": kind,
        "role": role,
        "detail": detail,
    }

    def mutate(data):
        data.setdefault("entries", []).append(entry)
        return data

    state_store.update("brief_audit", mutate, {"entries": []})


def render_brief_markdown(
    role: str,
    agent_id: str,
    summary: str,
    in_progress: str,
    blockers: str,
    next_steps: str,
    handoff_notes: str,
    artifacts: str,
) -> str:
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return (
        f"# Session Brief — {role}\n"
        f"\n"
        f"- **Saved at:** {ts}\n"
        f"- **Agent ID:** {agent_id or '(primary)'}\n"
        f"\n"
        f"## Summary — this sessionda what yapildi\n\n{summary.strip() or '_(empty)_'}\n\n"
        f"## In-progress — yarida kalan isler\n\n{in_progress.strip() or '_(yok)_'}\n\n"
        f"## Blockers — neyi I wait\n\n{blockers.strip() or '_(yok)_'}\n\n"
        f"## Next steps — bir next sessionda before yapilacaklar\n\n{next_steps.strip() or '_(yok)_'}\n\n"
        f"## Handoff notes — upper katmana not\n\n{handoff_notes.strip() or '_(yok)_'}\n\n"
        f"## Artifacts — uretilen filelar / linkler\n\n{artifacts.strip() or '_(yok)_'}\n"
    )


def get_brief_text(role: str) -> str | None:
    """runtime.load_prompt this calls — brief if exists text drecommend, nonesa None."""
    p = _brief_path(role)
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:  # pragma: no cover
        return None


# ------------------------------------------------------------------
# @tool'lar
# ------------------------------------------------------------------

@tool(
    "save",
    (
        "Session brief'ini state/briefs/<role>.md'e yazar. Her taking zorunludur "
        "(empty string verilebilir but open olsun). Eski brief automatic history'ye arsivlenir."
    ),
    {
        "role": str,
        "agent_id": str,
        "summary": str,
        "in_progress": str,
        "blockers": str,
        "next_steps": str,
        "handoff_notes": str,
        "artifacts": str,
    },
)
async def save(args: dict) -> dict:
    role = args.get("role", "").strip()
    if not role:
        return {"content": [{"type": "text", "text": "role mandatory"}], "is_error": True}

    md = render_brief_markdown(
        role=role,
        agent_id=args.get("agent_id", "").strip(),
        summary=args.get("summary", ""),
        in_progress=args.get("in_progress", ""),
        blockers=args.get("blockers", ""),
        next_steps=args.get("next_steps", ""),
        handoff_notes=args.get("handoff_notes", ""),
        artifacts=args.get("artifacts", ""),
    )

    _archive(role)
    path = _brief_path(role)
    try:
        path.write_text(md, encoding="utf-8")
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Brief yazilamadi: {e}"}], "is_error": True}

    _audit("save", role, f"{len(md)}B")
    return {"content": [{"type": "text",
                         "text": f"Brief kaydedildi: {path.relative_to(PROJECT_ROOT)}  ({len(md)} byte)"}]}


@tool(
    "load",
    "state/briefs/<role>.md file okur. role mandatory. File nonesa 'brief none' drecommend.",
    {"role": str},
)
async def load(args: dict) -> dict:
    role = args.get("role", "").strip()
    if not role:
        return {"content": [{"type": "text", "text": "role mandatory"}], "is_error": True}
    text = get_brief_text(role)
    if text is None:
        return {"content": [{"type": "text", "text": f"Brief none: {role}"}]}
    _audit("load", role)
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "list_all",
    "All role's brief state (var/yok, last writing zamani) listr.",
    {},
)
async def list_all(args: dict) -> dict:
    lines = ["Session briefs:"]
    any_found = False
    for p in sorted(BRIEFS_DIR.glob("*.md")):
        role = p.stem
        try:
            mtime = datetime.utcfromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds") + "Z"
            size = p.stat().st_size
        except Exception:
            mtime, size = "?", 0
        lines.append(f"  - {role:28s}  {mtime}  ({size}B)")
        any_found = True
    if not any_found:
        lines.append("  (not yet record none)")

    hist = list(HISTORY_DIR.glob("*.md"))
    lines.append("")
    lines.append(f"Arsivde total: {len(hist)} eski brief")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


BRIEF_TOOLS = [save, load, list_all]
