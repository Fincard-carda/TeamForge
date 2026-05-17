"""Config filelarinda cerrahi (surgical) duzenleme.

Yorumlar and formskipmayi korumak for regex tabanli minimal line
degisikligi yapariz. Her yazimdan before .bak yedek alinir, next
config_loader cache'i invalide is done.

Tool kategoris:
  * Team config: count, profile, model, max_turns
  * Budget: agent_costs_monthly altindaki rakamlar
  * Prompts: prompts/<role>.md filelarini read/write/append
  * Audit: all degisikliklerin gecmisi
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from . import config_loader, state_store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# Roller between gecisli regex'lerde end bulmak for
_NEXT_ROLE_OR_TOP = re.compile(r"^  [a-z_]+:\s*$|^[a-z_]+:\s*$", re.MULTILINE)


# -----------------------------------------------------------------
# Helper
# -----------------------------------------------------------------

def _backup(path: Path) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    bak = path.with_suffix(path.suffix + f".{ts}.bak")
    shutil.copy2(path, bak)
    return bak


def _audit(kind: str, details: dict[str, Any]) -> None:
    entry = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "kind": kind, **details,
    }
    def mutate(data):
        data.setdefault("entries", []).append(entry)
        return data
    state_store.update("config_audit", mutate, {"entries": []})


def _role_block_span(text: str, role: str) -> tuple[int, int]:
    """team.yaml forde verilen role ait bloday (start, end) byte ofsetlerini drecommend."""
    start_re = re.compile(rf"^  {re.escape(role)}:\s*$", re.MULTILINE)
    m = start_re.search(text)
    if not m:
        raise ValueError(f"team.yaml: role {role} bulunamadi")
    block_start = m.start()
    n = _NEXT_ROLE_OR_TOP.search(text, m.end())
    block_end = n.start() if n else len(text)
    return block_start, block_end


# -----------------------------------------------------------------
# team.yaml — count, profile, model, max_turns
# -----------------------------------------------------------------

def set_team_count(role: str, new_count: int) -> tuple[int, int]:
    path = CONFIG_DIR / "team.yaml"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^  {re.escape(role)}:\s*$[\s\S]*?^    count:\s*)(\d+)",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        raise ValueError(f"team.yaml forde {role}.count bulunamadi")
    old = int(m.group(2))
    if old == new_count:
        return old, old
    new_text = pattern.sub(rf"\g<1>{new_count}", text, count=1)
    _backup(path)
    path.write_text(new_text, encoding="utf-8")
    config_loader.reload_all()
    _audit("team_count", {"role": role, "old": old, "new": new_count})
    return old, new_count


def set_role_profile(role: str, new_profile: str) -> bool:
    """profile: > blogundaki all lines again yazar. Yorumlar korunur."""
    path = CONFIG_DIR / "team.yaml"
    text = path.read_text(encoding="utf-8")
    bs, be = _role_block_span(text, role)
    block = text[bs:be]
    prof_re = re.compile(r"(    profile:\s*>\s*\n)((?:      .*\n)+)", re.MULTILINE)
    pm = prof_re.search(block)
    if not pm:
        raise ValueError(f"team.yaml: {role} for 'profile: >' blogu bulunamadi")
    new_lines = []
    for line in new_profile.strip().split("\n"):
        new_lines.append(f"      {line.strip()}\n")
    new_block = block[:pm.start()] + pm.group(1) + "".join(new_lines) + block[pm.end():]
    new_text = text[:bs] + new_block + text[be:]
    _backup(path)
    path.write_text(new_text, encoding="utf-8")
    config_loader.reload_all()
    _audit("role_profile", {"role": role, "new_profile_chars": len(new_profile)})
    return True


def set_role_model(role: str, new_model: str) -> tuple[str, str]:
    path = CONFIG_DIR / "team.yaml"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^  {re.escape(role)}:\s*$[\s\S]*?^    model:\s*)([^\n]+)",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        raise ValueError(f"team.yaml: {role}.model bulunamadi")
    old = m.group(2).strip()
    if old == new_model.strip():
        return old, old
    new_text = pattern.sub(rf"\g<1>{new_model}", text, count=1)
    _backup(path)
    path.write_text(new_text, encoding="utf-8")
    config_loader.reload_all()
    _audit("role_model", {"role": role, "old": old, "new": new_model})
    return old, new_model


def set_role_max_turns(role: str, new_max_turns: int) -> tuple[int, int]:
    path = CONFIG_DIR / "team.yaml"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^  {re.escape(role)}:\s*$[\s\S]*?^    max_turns:\s*)(\d+)",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        raise ValueError(f"team.yaml: {role}.max_turns bulunamadi")
    old = int(m.group(2))
    if old == new_max_turns:
        return old, old
    new_text = pattern.sub(rf"\g<1>{new_max_turns}", text, count=1)
    _backup(path)
    path.write_text(new_text, encoding="utf-8")
    config_loader.reload_all()
    _audit("role_max_turns", {"role": role, "old": old, "new": new_max_turns})
    return old, new_max_turns


# -----------------------------------------------------------------
# budget.yaml
# -----------------------------------------------------------------

def set_budget_cost(role: str, new_monthly: float) -> tuple[float, float]:
    path = CONFIG_DIR / "budget.yaml"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^agent_costs_monthly:\s*$[\s\S]*?^  {re.escape(role)}:\s*)(\d+(?:\.\d+)?)",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if not m:
        raise ValueError(f"budget.yaml forde agent_costs_monthly.{role} bulunamadi")
    old = float(m.group(2))
    if abs(old - new_monthly) < 1e-9:
        return old, old
    new_text = pattern.sub(rf"\g<1>{new_monthly:g}", text, count=1)
    _backup(path)
    path.write_text(new_text, encoding="utf-8")
    config_loader.reload_all()
    _audit("budget_cost", {"role": role, "old": old, "new": new_monthly})
    return old, new_monthly


# -----------------------------------------------------------------
# prompts/*.md
# -----------------------------------------------------------------

def _prompt_path(role: str) -> Path:
    safe = role.replace("/", "_").replace("..", "_")
    return PROMPTS_DIR / f"{safe}.md"


def read_prompt_file(role: str) -> str:
    p = _prompt_path(role)
    if not p.exists():
        raise FileNotFoundError(f"prompts/{role}.md none")
    return p.read_text(encoding="utf-8")


def write_prompt_file(role: str, content: str) -> int:
    p = _prompt_path(role)
    if p.exists():
        _backup(p)
    p.write_text(content, encoding="utf-8")
    _audit("prompt_overwrite", {"role": role, "len": len(content)})
    return len(content)


def append_to_prompt_file(role: str, content: str) -> int:
    p = _prompt_path(role)
    if not p.exists():
        raise FileNotFoundError(f"prompts/{role}.md none")
    _backup(p)
    sep = "" if content.startswith("\n") else "\n\n"
    new_text = p.read_text(encoding="utf-8") + sep + content
    p.write_text(new_text, encoding="utf-8")
    _audit("prompt_append", {"role": role, "appended_chars": len(content),
                              "new_total": len(new_text)})
    return len(new_text)


# -----------------------------------------------------------------
# @tool — MCP arabirim
# -----------------------------------------------------------------

@tool(
    "update_team_count",
    "config/team.yaml forde bir role's count: valueini currentle.",
    {"role": str, "new_count": int, "reason": str},
)
async def update_team_count(args: dict) -> dict:
    role = args.get("role", "").strip()
    new_count = int(args.get("new_count", 0))
    reason = args.get("reason", "").strip()
    if not role or new_count < 1 or not reason:
        return {"content": [{"type": "text",
                             "text": "role, new_count>=1, reason mandatory"}],
                "is_error": True}
    try:
        old, new = set_team_count(role, new_count)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}
    return {"content": [{"type": "text",
                         "text": f"team.yaml: {role}.count {old} -> {new}  (reason: {reason})"}]}


@tool(
    "update_role_profile",
    ("config/team.yaml'da bir role's 'profile' metnini bastan sona again yazar. "
     "Existing profile lines silinir, new_profile is written. Yorumlar korunur."),
    {"role": str, "new_profile": str, "reason": str},
)
async def update_role_profile(args: dict) -> dict:
    role = args.get("role", "").strip()
    new_profile = args.get("new_profile", "")
    reason = args.get("reason", "").strip()
    if not role or not new_profile.strip() or not reason:
        return {"content": [{"type": "text",
                             "text": "role, new_profile, reason mandatory"}],
                "is_error": True}
    try:
        set_role_profile(role, new_profile)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}
    return {"content": [{"type": "text",
                         "text": f"team.yaml: {role}.profile currentlendi ({len(new_profile)} char)  (reason: {reason})"}]}


@tool(
    "update_role_model",
    ("config/team.yaml'da bir role's model: valueini currentle. "
     "Example: 'claude-sonnet-4-6' or '${CLAUDE_MODEL_LEAD}'."),
    {"role": str, "new_model": str, "reason": str},
)
async def update_role_model(args: dict) -> dict:
    role = args.get("role", "").strip()
    new_model = args.get("new_model", "").strip()
    reason = args.get("reason", "").strip()
    if not role or not new_model or not reason:
        return {"content": [{"type": "text",
                             "text": "role, new_model, reason mandatory"}],
                "is_error": True}
    try:
        old, new = set_role_model(role, new_model)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}
    return {"content": [{"type": "text",
                         "text": f"team.yaml: {role}.model {old} -> {new}  (reason: {reason})"}]}


@tool(
    "update_role_max_turns",
    "config/team.yaml'da bir role's max_turns valueini currentle (example: 40, 80).",
    {"role": str, "new_max_turns": int, "reason": str},
)
async def update_role_max_turns(args: dict) -> dict:
    role = args.get("role", "").strip()
    new_max_turns = int(args.get("new_max_turns", 0))
    reason = args.get("reason", "").strip()
    if not role or new_max_turns < 1 or not reason:
        return {"content": [{"type": "text",
                             "text": "role, new_max_turns>=1, reason mandatory"}],
                "is_error": True}
    try:
        old, new = set_role_max_turns(role, new_max_turns)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}
    return {"content": [{"type": "text",
                         "text": f"team.yaml: {role}.max_turns {old} -> {new}  (reason: {reason})"}]}


@tool(
    "update_budget_cost",
    "config/budget.yaml'da agent_costs_monthly.<role> valueini currentle (USD/ay).",
    {"role": str, "new_monthly": float, "reason": str},
)
async def update_budget_cost(args: dict) -> dict:
    role = args.get("role", "").strip()
    new_monthly = float(args.get("new_monthly", -1))
    reason = args.get("reason", "").strip()
    if not role or new_monthly < 0 or not reason:
        return {"content": [{"type": "text",
                             "text": "role, new_monthly>=0, reason mandatory"}],
                "is_error": True}
    try:
        old, new = set_budget_cost(role, new_monthly)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}
    return {"content": [{"type": "text",
                         "text": f"budget.yaml: {role} {old:g} -> {new:g} USD/ay  (reason: {reason})"}]}


@tool(
    "read_prompt",
    "prompts/<role>.md of the file current insidegini drecommend.",
    {"role": str},
)
async def read_prompt(args: dict) -> dict:
    role = args.get("role", "").strip()
    if not role:
        return {"content": [{"type": "text", "text": "role mandatory"}], "is_error": True}
    try:
        text = read_prompt_file(role)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "write_prompt",
    ("prompts/<role>.md of the file all insidegini again yazar. "
     "ESKI ICERIK SILINIR, only backup .bak'a alinir. "
     "Before read_prompt ile existing insidegi al, ona addme yapacaksan append_to_prompt kullan."),
    {"role": str, "new_content": str, "reason": str},
)
async def write_prompt(args: dict) -> dict:
    role = args.get("role", "").strip()
    content = args.get("new_content", "")
    reason = args.get("reason", "").strip()
    if not role or not content.strip() or not reason:
        return {"content": [{"type": "text",
                             "text": "role, new_content, reason mandatory"}],
                "is_error": True}
    try:
        n = write_prompt_file(role, content)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}
    return {"content": [{"type": "text",
                         "text": f"prompts/{role}.md again yazildi ({n} byte)  (reason: {reason})"}]}


@tool(
    "append_to_prompt",
    ("prompts/<role>.md of the file sonuna insidek addr. Ek var olan text "
     "etkilemez; only sonuna addnir. .bak yedegi alinir."),
    {"role": str, "content": str, "reason": str},
)
async def append_to_prompt(args: dict) -> dict:
    role = args.get("role", "").strip()
    content = args.get("content", "")
    reason = args.get("reason", "").strip()
    if not role or not content.strip() or not reason:
        return {"content": [{"type": "text",
                             "text": "role, content, reason mandatory"}],
                "is_error": True}
    try:
        total = append_to_prompt_file(role, content)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}
    return {"content": [{"type": "text",
                         "text": f"prompts/{role}.md'e addndi (yeni size: {total} byte)  (reason: {reason})"}]}


@tool(
    "show_config_audit",
    "Last config filesi degisikliklerini show.",
    {"limit": int},
)
async def show_config_audit(args: dict) -> dict:
    limit = int(args.get("limit", 20))
    data = state_store.read("config_audit", {"entries": []})
    entries = data.get("entries", [])[-limit:]
    if not entries:
        return {"content": [{"type": "text", "text": "(audit record none)"}]}
    lines = []
    for e in entries:
        lines.append(f"{e['ts']}  {e['kind']:18s}  {e.get('role','-'):20s}  "
                     f"{e.get('old', e.get('new', e.get('len', '')))}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


CONFIG_TOOLS = [
    update_team_count,        # 0
    update_budget_cost,       # 1
    show_config_audit,        # 2
    update_role_profile,      # 3
    update_role_model,        # 4
    update_role_max_turns,    # 5
    read_prompt,              # 6
    write_prompt,             # 7
    append_to_prompt,         # 8
]
