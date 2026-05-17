"""Paylasimli info tabani tool'lari.

Spec'ler, decisions, production artifactlari (markdown) docs/ or artifacts/
under file olarak saklanir. All agents okuyabilir, permissionli olanlar
yazabilir.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from . import state_store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)


def _safe_rel(base: Path, path: str) -> Path:
    p = (base / path).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise ValueError(f"Path escapes base: {path}")
    return p


@tool(
    "read_docs",
    "docs/ altindaki bir fileyi okur. path docs/ forde relative verilmeli.",
    {"path": str},
)
async def read_docs(args: dict) -> dict:
    rel = args.get("path", "").strip()
    if not rel:
        return {"content": [{"type": "text", "text": "path mandatory"}], "is_error": True}
    try:
        p = _safe_rel(DOCS_DIR, rel)
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    if not p.exists():
        return {"content": [{"type": "text", "text": f"File none: {rel}"}], "is_error": True}
    text = p.read_text(encoding="utf-8")
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "write_spec",
    "docs/specs/<name>.md under BA'nin readyladigi spec'i kaydeder.",
    {"name": str, "content": str},
)
async def write_spec(args: dict) -> dict:
    name = args.get("name", "").strip().replace(" ", "-")
    body = args.get("content", "")
    if not name or not body:
        return {"content": [{"type": "text", "text": "name and content mandatory"}], "is_error": True}
    out = DOCS_DIR / "specs" / f"{name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return {"content": [{"type": "text", "text": f"Spec yazildi: {out.relative_to(PROJECT_ROOT)}"}]}


@tool(
    "write_artifact",
    (
        "artifacts/<role>/<name> under bir artifact filesi createur. "
        "Kod, spec, report — everything olabilir. role and name mandatory, content serbest."
    ),
    {"role": str, "name": str, "content": str},
)
async def write_artifact(args: dict) -> dict:
    role = args.get("role", "").strip()
    name = args.get("name", "").strip()
    body = args.get("content", "")
    if not role or not name:
        return {"content": [{"type": "text", "text": "role and name mandatory"}], "is_error": True}
    out = ARTIFACTS_DIR / role / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return {"content": [{"type": "text", "text": f"Artifact yazildi: {out.relative_to(PROJECT_ROOT)}"}]}


@tool(
    "read_artifact",
    (
        "Baska bir agent'in artifacts/<role>/<name> under yazdigi fileyi okur. "
        "role + name mandatory. role belirtilmezse list_artifacts ile bak."
    ),
    {"role": str, "name": str},
)
async def read_artifact(args: dict) -> dict:
    role = args.get("role", "").strip()
    name = args.get("name", "").strip()
    if not role or not name:
        return {"content": [{"type": "text",
                              "text": "role and name mandatory. Existing artifact'leri gormek for list_artifacts kullan."}],
                "is_error": True}
    try:
        p = _safe_rel(ARTIFACTS_DIR / role, name)
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    if not p.exists():
        return {"content": [{"type": "text",
                              "text": f"Artifact none: {role}/{name}. list_artifacts ile mevcutlari check et."}],
                "is_error": True}
    text = p.read_text(encoding="utf-8")
    header = f"=== artifacts/{role}/{name} ({p.stat().st_size} byte) ===\n\n"
    return {"content": [{"type": "text", "text": header + text}]}


@tool(
    "list_artifacts",
    (
        "artifacts/ altindaki all filelari rol per list. "
        "Optional role parametresi only o role's artifact'lerini gosterir."
    ),
    {"role": str},
)
async def list_artifacts(args: dict) -> dict:
    role_filter = (args.get("role") or "").strip()
    if not ARTIFACTS_DIR.exists():
        return {"content": [{"type": "text", "text": "artifacts/ klasoru empty or none."}]}
    lines = []
    total = 0
    if role_filter:
        role_dir = ARTIFACTS_DIR / role_filter
        if not role_dir.exists():
            return {"content": [{"type": "text",
                                  "text": f"{role_filter} for artifact none."}]}
        lines.append(f"=== {role_filter} ===")
        for f in sorted(role_dir.glob("*")):
            if f.is_file():
                lines.append(f"  - {f.name}  ({f.stat().st_size}B)")
                total += 1
    else:
        for role_dir in sorted(ARTIFACTS_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            files = sorted([f for f in role_dir.glob("*") if f.is_file()])
            if not files:
                continue
            lines.append(f"=== {role_dir.name} ({len(files)}) ===")
            for f in files:
                lines.append(f"  - {f.name}  ({f.stat().st_size}B)")
                total += 1
    if not lines:
        return {"content": [{"type": "text", "text": "Hicbir artifact none."}]}
    lines.append("")
    lines.append(f"Total: {total} artifact")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "write_decision",
    (
        "Stratejik / technical decisions state/decisions.json'a kaydeder. "
        "CEO and PM this tool ile ADR tarzi decision gecmisi leaves."
    ),
    {"title": str, "author_role": str, "context": str, "decision": str, "consequences": str},
)
async def write_decision(args: dict) -> dict:
    entry = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "title": args.get("title", "").strip(),
        "author_role": args.get("author_role", "").strip(),
        "context": args.get("context", "").strip(),
        "decision": args.get("decision", "").strip(),
        "consequences": args.get("consequences", "").strip(),
    }
    if not entry["title"] or not entry["decision"]:
        return {"content": [{"type": "text", "text": "title and decision mandatory"}], "is_error": True}

    def mutate(data):
        data.setdefault("decisions", []).append(entry)
        return data

    state_store.update("decisions", mutate, {"decisions": []})
    return {"content": [{"type": "text", "text": f"Decision kaydedildi: {entry['title']}"}]}


# ONEMLI: orchestrator._global_registry'de this order kullaniing:
#   [0]=read_docs [1]=write_spec [2]=write_artifact [3]=write_decision
#   [4]=read_artifact [5]=list_artifacts
KNOWLEDGE_TOOLS = [read_docs, write_spec, write_artifact, write_decision,
                    read_artifact, list_artifacts]
