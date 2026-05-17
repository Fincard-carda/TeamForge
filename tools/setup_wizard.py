"""TeamForge first-acilis setup wizard.

Single bir HTTP heregiyle:
  1. User's proje description (example: "B2B SaaS platformu, GDPR uyumlu")
     alinir.
  2. Anthropic API over Claude calllir; o projeye uyday rol list,
     her role's persona/responsibility/delegation iskelet, and tech_stack
     recommendisi produces.
  3. Output dashboard'da preview olarak gosterilir.
  4. User approval verirse config/* and prompts/* filelari is written,
     state/setup_complete.json flag olusur.

Uretim Anthropic standart API key'i kullanir (ANTHROPIC_API_KEY).
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("teamforge.setup_wizard")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "prompts.template" / "base_agent.md"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
CONFIG_DIR = PROJECT_ROOT / "config"
STATE_DIR = PROJECT_ROOT / "state"
SETUP_FLAG = STATE_DIR / "setup_complete.json"


def is_setup_complete() -> bool:
    """Setup tamamlandi mi?"""
    if not SETUP_FLAG.exists():
        return False
    try:
        data = json.loads(SETUP_FLAG.read_text(encoding="utf-8"))
        return bool(data.get("completed"))
    except Exception:
        return False


def _slugify(text: str) -> str:
    """Human-okur 'Project Manager' -> 'project_manager'."""
    t = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return t or "agent"


SYSTEM_PROMPT = """You are a TeamForge setup assistant. The user describes their project in 1-2 sentences. \
You must produce a JSON object that defines a multi-agent team optimized for that project.

The JSON MUST be valid (no comments, no trailing commas) and follow this exact schema:

{
  "project": {
    "name": "<short project name>",
    "domain": "<one of: fintech, ecommerce, saas, healthtech, edtech, devtools, social, gaming, ai_product, other>",
    "summary": "<one-paragraph summary>",
    "compliance": ["<list of relevant compliance regimes, e.g. PCI-DSS, GDPR, HIPAA, SOC2 — may be empty>"]
  },
  "tech_stack": {
    "backend": "<one-line tech choice>",
    "frontend": "<one-line tech choice>",
    "mobile": "<one-line tech choice OR empty if N/A>",
    "data": "<one-line tech choice>",
    "infra": "<one-line tech choice>"
  },
  "roles": [
    {
      "id": "<snake_case role id, e.g. ceo, project_manager, backend_dev>",
      "label": "<human-readable label, e.g. CEO, Project Manager>",
      "tier": "<leader OR worker>",
      "model": "<claude-opus-4-6 for leaders, claude-sonnet-4-6 for senior workers, claude-haiku-4-5 for fast workers>",
      "persona": "<2-3 sentences describing background, expertise, personality>",
      "responsibilities": ["<bullet point>", "<bullet point>", "..."],
      "delegates_to": ["<role_id>", "..."],
      "delegation_notes": "<1-2 sentences about how this role hands off work>"
    }
  ]
}

Rules:
- ALWAYS include exactly one ceo and one cfo as leaders (these are framework essentials).
- Include 1 project_manager and 1 business_analyst or equivalent as leaders.
- Include 1 tech_lead as a leader.
- Include 3-7 workers (devs, testers, designers, ops) appropriate to the project.
- Workers must have tier "worker" and writes_code-equivalent role.
- Leaders delegate to workers; workers do not delegate.
- Total team size: 6-12 roles.
- delegates_to should reflect realistic hierarchy: ceo -> [project_manager, cfo], pm -> [business_analyst, tech_lead], tech_lead -> [<workers>], etc.

Output ONLY the JSON. No prose before or next.
"""


async def generate_team_async(description: str, api_key: str | None = None) -> dict[str, Any]:
    """Anthropic API'ye call yapip JSON spec drecommend.

    Before try: anthropic SDK if exists it kullan.
    Nonesa: urllib ile direct call.
    """
    desc = (description or "").strip()
    if not desc:
        raise ValueError("Proje description empty can't be")
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY env var bulunamadi")

    model = os.environ.get("CLAUDE_MODEL_LEAD") or os.environ.get("CLAUDE_MODEL") or "claude-opus-4-6"

    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": desc}],
    }

    import asyncio
    from urllib import request as urlrequest, error as urlerror

    def _call():
        req = urlrequest.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urlrequest.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urlerror.HTTPError as e:
            body = ""
            try: body = e.read().decode("utf-8")
            except Exception: pass
            raise RuntimeError(f"Anthropic API HTTP {e.code}: {body[:200]}")

    loop = asyncio.get_running_loop()
    resp = await loop.run_in_executor(None, _call)

    # Response structurei: {"content": [{"type": "text", "text": "..."}]}
    text = ""
    for block in resp.get("content") or []:
        if block.get("type") == "text":
            text += block.get("text", "")
    text = text.strip()
    # Bazen ``` ile sarmalanmis olabilir
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n", "", text)
        text = re.sub(r"\n```$", "", text)
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM cevabi JSON not: {e}. Answer basi: {text[:200]}")

    _validate_spec(spec)
    return spec


def _validate_spec(spec: dict[str, Any]) -> None:
    if not isinstance(spec, dict):
        raise ValueError("Spec dict must be")
    for k in ("project", "tech_stack", "roles"):
        if k not in spec:
            raise ValueError(f"Spec'te '{k}' none")
    roles = spec.get("roles") or []
    if not isinstance(roles, list) or len(roles) < 3:
        raise ValueError("En az 3 rol required")
    role_ids = set()
    for r in roles:
        if not isinstance(r, dict): raise ValueError("Rol dict must be")
        for f in ("id", "label", "tier", "model", "persona", "responsibilities"):
            if f not in r: raise ValueError(f"Rolde '{f}' none: {r.get('id', '?')}")
        if r.get("tier") not in ("leader", "worker"):
            raise ValueError(f"tier 'leader' or 'worker' must be: {r.get('id')}")
        if r["id"] in role_ids:
            raise ValueError(f"Tekrarlanan rol id: {r['id']}")
        role_ids.add(r["id"])


def render_prompt(role: dict[str, Any], template: str) -> str:
    """Base template'i rol vaccessyle fill."""
    resp = role.get("responsibilities") or []
    resp_md = "\n".join(f"{i+1}. {r}" for i, r in enumerate(resp))
    delegates = role.get("delegates_to") or []
    if delegates:
        del_notes = (role.get("delegation_notes") or
                     f"That rolesi delege you do: {', '.join(delegates)}.")
        del_notes += f"\n\n`delegate.to_<role>(payload)` tool'unu kullan."
    else:
        del_notes = "This rol delegation doesn't do; kendi gorevini bizzat yurutur."

    extra = ""
    if role.get("id") == "ceo":
        extra = "\n\n## Budget yonetimi\n\nOwner 'budget nadelete?' derse `analytics.usage_check` and `budget.get_report` iki suddenly call."
    elif role.get("id") == "cfo":
        extra = "\n\n## Mali tablo\n\nFP&A, unit economics, runway hesaplari your sorumluluday."

    text = (template
            .replace("{{ROLE_LABEL}}", role.get("label", role["id"]))
            .replace("{{ROLE_ID}}", role["id"])
            .replace("{{PERSONA}}", role.get("persona", ""))
            .replace("{{RESPONSIBILITIES}}", resp_md)
            .replace("{{DELEGATION_NOTES}}", del_notes)
            .replace("{{BUDGET_HINTS}}",
                     "BUTCE UYARISI / HARD BLOCK"
                     if role.get("tier") == "leader" else "PM over"))
    text = text.replace("{{EXTRA_SECTIONS}}", extra)
    return text


def save_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Spec'i config/ and prompts/ filelarina write, setup_complete bayragini koy.

    Returns: written files list (debug for).
    """
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    written = []

    # 1) prompts/<role>.md
    for role in spec["roles"]:
        rid = _slugify(role["id"])
        role["id"] = rid
        path = PROMPTS_DIR / f"{rid}.md"
        path.write_text(render_prompt(role, template), encoding="utf-8")
        written.append(str(path.relative_to(PROJECT_ROOT)))

    # 2) config/team.yaml
    team_roles = {}
    for role in spec["roles"]:
        rid = role["id"]
        model_env = "${CLAUDE_MODEL_LEAD}" if role["tier"] == "leader" else "${CLAUDE_MODEL}"
        team_roles[rid] = {
            "count": 1,
            "model": model_env,
            "max_turns": 40 if role["tier"] == "leader" else 30,
            "profile": role.get("persona", ""),
            "tier": role["tier"],
        }
    team_doc = {"roles": team_roles}
    (CONFIG_DIR / "team.yaml").write_text(
        "# TeamForge team kompozisyonu — setup wizard tarafindan uretildi\n" +
        yaml.safe_dump(team_doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    written.append("config/team.yaml")

    # 3) config/tech_stack.yaml
    project = spec.get("project", {})
    ts = spec.get("tech_stack", {})
    tech_doc = {
        "project": {
            "name": project.get("name", "TeamForge Project"),
            "domain": project.get("domain", "general"),
            "summary": project.get("summary", ""),
            "compliance": project.get("compliance", []),
        },
        "tech_stack": ts,
    }
    (CONFIG_DIR / "tech_stack.yaml").write_text(
        "# TeamForge teknoloji stack — setup wizard tarafindan uretildi\n" +
        yaml.safe_dump(tech_doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    written.append("config/tech_stack.yaml")

    # 4) config/policies.yaml — defaults korunsun, roles addnsin
    existing = {}
    try:
        existing = yaml.safe_load((CONFIG_DIR / "policies.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        existing = {}
    defaults = existing.get("_defaults") or {}
    leader_baseline = (defaults.get("leader") or {}).get("tools_baseline") or []
    worker_baseline = (defaults.get("worker") or {}).get("tools_baseline") or []

    new_roles_policies = {}
    for role in spec["roles"]:
        rid = role["id"]
        is_leader = role["tier"] == "leader"
        baseline = leader_baseline if is_leader else worker_baseline
        tools = list(baseline)
        if is_leader:
            tools += [f"delegate.to_{d}" for d in (role.get("delegates_to") or [])]
        if rid == "ceo":
            tools += ["budget.get_report", "budget.log_expense",
                      "budget.sync_from_analytics", "budget.request_user_approval",
                      "analytics.usage_check", "analytics.cost_report",
                      "analytics.usage_report"]
        elif rid == "cfo":
            tools += ["analytics.usage_check", "analytics.cost_report",
                      "analytics.usage_report", "budget.sync_from_analytics"]
        new_roles_policies[rid] = {
            "delegate_to": role.get("delegates_to") or [],
            "can_request_new_agent": is_leader,
            "can_approve_budget": rid == "ceo",
            "can_escalate_to_user": is_leader,
            "writes_code": not is_leader,
            "allow_subagent_spawn": is_leader,
            "tools": tools,
        }
    existing["roles"] = new_roles_policies
    (CONFIG_DIR / "policies.yaml").write_text(
        "# Hierarchy and permission policies — setup wizard tarafindan uretildi\n" +
        yaml.safe_dump(existing, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    written.append("config/policies.yaml")

    # 5) setup_complete flag
    SETUP_FLAG.write_text(json.dumps({
        "completed": True,
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_name": project.get("name", ""),
        "domain": project.get("domain", ""),
        "role_count": len(spec["roles"]),
    }, indent=2), encoding="utf-8")
    written.append("state/setup_complete.json")

    return {"written": written, "role_count": len(spec["roles"])}
