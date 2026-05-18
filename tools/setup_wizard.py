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

CRITICAL: Every text field in the JSON (project.name, project.domain, project.summary, \
tech_stack.*, every role's label/persona/responsibilities/delegation_notes/etc.) MUST be \
written in ENGLISH. This rule holds regardless of the language the user used in their \
project description. If the user wrote in Turkish, French, Spanish, or any other \
language, you still produce English output.

The JSON MUST be valid (no comments, no trailing commas) and follow this exact schema:

{
  "project": {
    "name": "<short project name>",
    "domain": "<one of: fintech, ecommerce, saas, healthtech, edtech, devtools, social, gaming, ai_product, other>",
    "summary": "<one-paragraph summary>",
    "compliance": ["<list of relevant compliance regimes, e.g. PCI-DSS, GDPR, HIPAA, SOC2 - may be empty>"]
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
- Leaders have tier "leader", workers have tier "worker".
- Leaders delegate to workers; workers do not delegate.
- delegates_to reflects realistic hierarchy: ceo -> [project_manager, cfo], pm -> [business_analyst, tech_lead], tech_lead -> [<workers>], etc.
- Each role id appears at most once.

{{SIZE_RULES}}

Output ONLY the JSON. No prose before or after.
"""


async def generate_team_async(description: str, language: str = "English",
                                size: str = "min",
                                api_key: str | None = None) -> dict[str, Any]:
    """Call the Anthropic API and return a JSON team spec.

    Args:
        description: 1-3 sentence project description from the user.
        language: language for all generated content AND the runtime
                  communication language of the agents.
        size: "min" (lean MVP, 4-7 roles) or "max" (comprehensive, 8-14 roles).
              "custom" maps to "max" — the user filters roles in the UI.
        api_key: optional override (defaults to ANTHROPIC_API_KEY).
    """
    desc = (description or "").strip()
    if not desc:
        raise ValueError("Project description cannot be empty")
    lang = (language or "English").strip() or "English"
    sz = (size or "min").strip().lower()
    if sz == "custom":
        sz = "max"
    if sz not in ("min", "max"):
        sz = "min"
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY env var not found")

    model = os.environ.get("CLAUDE_MODEL_LEAD") or os.environ.get("CLAUDE_MODEL") or "claude-opus-4-6"

    # Size-specific guidance injected into the prompt
    if sz == "min":
        size_rules = (
            "Size: LEAN MVP team — output 4-7 roles total. The smallest team that can still "
            "deliver the project end-to-end. Combine multiple skills per role when reasonable "
            "(e.g. a single 'full_stack_dev' instead of separate frontend/backend). "
            "Be ruthless about cutting roles that aren't strictly necessary."
        )
    else:
        size_rules = (
            "Size: COMPREHENSIVE team — output 8-14 roles total. A full team with specialized "
            "coverage. Include dedicated business analyst, separate frontend/backend/mobile "
            "developers, dedicated tester, devops, designer, and other specialists that earn "
            "their seat for this specific project."
        )

    # Language directive on top of the base SYSTEM_PROMPT
    system_with_lang = SYSTEM_PROMPT.replace("{{SIZE_RULES}}", size_rules).replace(
        "MUST be \\\nwritten in ENGLISH",
        f"MUST be \\\nwritten in {lang.upper()}"
    ).replace(
        "you still produce English output.",
        f"you still produce {lang} output."
    )

    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": system_with_lang,
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


def _validate_role(r: dict[str, Any], seen: set) -> None:
    if not isinstance(r, dict):
        raise ValueError("role entries must be dicts")
    for f in ("id", "label", "tier", "model", "persona", "responsibilities"):
        if f not in r:
            raise ValueError(f"role '{r.get('id','?')}' is missing required field '{f}'")
    if r.get("tier") not in ("leader", "worker"):
        raise ValueError(f"role '{r['id']}' has invalid tier")
    if r["id"] in seen:
        raise ValueError(f"duplicate role id '{r['id']}'")
    seen.add(r["id"])


def _validate_spec(spec: dict[str, Any]) -> None:
    if not isinstance(spec, dict):
        raise ValueError("Spec must be a dict")
    for k in ("project", "tech_stack", "roles"):
        if k not in spec:
            raise ValueError(f"Spec is missing '{k}'")
    roles = spec.get("roles") or []
    if not isinstance(roles, list) or len(roles) < 3:
        raise ValueError("Spec must contain at least 3 roles")
    seen: set = set()
    for r in roles:
        _validate_role(r, seen)
    # CEO + CFO must exist
    ids = {r["id"] for r in roles}
    for required in ("ceo", "cfo"):
        if required not in ids:
            raise ValueError(f"Spec is missing required role '{required}'")


def render_prompt(role: dict[str, Any], template: str,
                  language: str = "English") -> str:
    """Fill the base template with role data, delegation notes, language directive."""
    resp = role.get("responsibilities") or []
    resp_md = "\n".join(f"{i+1}. {r}" for i, r in enumerate(resp))
    delegates = role.get("delegates_to") or []
    if delegates:
        del_notes = (role.get("delegation_notes") or
                     f"You delegate work to: {', '.join(delegates)}.")
        del_notes += "\n\nUse the `delegate.to_<role>(payload)` tool."
    else:
        del_notes = "This role does not delegate; you carry out your own work directly."

    extra = ""
    if role.get("id") == "ceo":
        extra = ("\n\n## Budget management\n\n"
                 "When the user asks about budget, call BOTH `analytics.usage_check` "
                 "(real Anthropic spend) and `budget.get_report` (local cap) and "
                 "report them together.")
    elif role.get("id") == "cfo":
        extra = ("\n\n## Financial reporting\n\n"
                 "FP&A, unit economics, runway projections are your responsibility. "
                 "Pull real spend via `analytics.usage_check` and reconcile with "
                 "`budget.sync_from_analytics`.")

    text = (template
            .replace("{{ROLE_LABEL}}", role.get("label", role["id"]))
            .replace("{{ROLE_ID}}", role["id"])
            .replace("{{PERSONA}}", role.get("persona", ""))
            .replace("{{RESPONSIBILITIES}}", resp_md)
            .replace("{{DELEGATION_NOTES}}", del_notes)
            .replace("{{BUDGET_HINTS}}",
                     "BUDGET WARNING / HARD BLOCK"
                     if role.get("tier") == "leader" else "PM forwards budget alerts"))
    # Language section — drives runtime communication style
    lang_section = (
        f"\n\n## Communication language\n\n"
        f"All your responses, internal reasoning summaries, tool outputs, briefs, "
        f"and decisions MUST be written in **{language}**. The user and the rest "
        f"of the team will read your output in {language}. If you receive a "
        f"message in another language, still respond in {language}."
    )
    text = text.replace("{{EXTRA_SECTIONS}}", extra + lang_section)
    return text


def save_spec(spec: dict[str, Any], language: str = "English",
              monthly_budget: float = 100.0,
              selected_role_ids: list[str] | None = None) -> dict[str, Any]:
    """Save the approved spec to config/ and prompts/.

    Args:
        spec: dict with shape {"project": ..., "tech_stack": ..., "roles": [...]}
        language: communication language for the agents
        monthly_budget: USD cap for config/budget.yaml
        selected_role_ids: if provided (custom mode), only these role ids are
                           installed. CEO and CFO are always included.
    """
    if "roles" not in spec or not isinstance(spec["roles"], list):
        raise ValueError("Spec must contain a 'roles' list")

    all_roles = spec["roles"]
    if selected_role_ids is not None:
        wanted = set(selected_role_ids) | {"ceo", "cfo"}  # CEO+CFO mandatory
        roles_to_install = [r for r in all_roles if r.get("id") in wanted]
    else:
        roles_to_install = all_roles

    if len(roles_to_install) < 3:
        raise ValueError("Selected team must include at least 3 roles")
    role_ids = {r["id"] for r in roles_to_install}
    for required in ("ceo", "cfo"):
        if required not in role_ids:
            raise ValueError(f"Required role '{required}' missing from selection")

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    written: list[str] = []

    # 1) prompts/<role>.md
    for role in roles_to_install:
        rid = _slugify(role["id"])
        role["id"] = rid
        (PROMPTS_DIR / f"{rid}.md").write_text(render_prompt(role, template, language), encoding="utf-8")
        written.append(f"prompts/{rid}.md")

    # 2) config/team.yaml
    team_roles: dict[str, dict] = {}
    for role in roles_to_install:
        rid = role["id"]
        model_env = "${CLAUDE_MODEL_LEAD}" if role["tier"] == "leader" else "${CLAUDE_MODEL}"
        team_roles[rid] = {
            "count": 1,
            "model": model_env,
            "max_turns": 40 if role["tier"] == "leader" else 30,
            "profile": role.get("persona", ""),
            "tier": role["tier"],
        }
    (CONFIG_DIR / "team.yaml").write_text(
        "# TeamForge team composition - generated by the setup wizard\n" +
        yaml.safe_dump({"roles": team_roles}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    written.append("config/team.yaml")

    # 3) config/tech_stack.yaml
    project = spec.get("project", {})
    (CONFIG_DIR / "tech_stack.yaml").write_text(
        "# TeamForge tech stack - generated by the setup wizard\n" +
        yaml.safe_dump({
            "project": {
                "name": project.get("name", "TeamForge Project"),
                "domain": project.get("domain", "general"),
                "summary": project.get("summary", ""),
                "compliance": project.get("compliance", []),
            },
            "tech_stack": spec.get("tech_stack", {}),
        }, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    written.append("config/tech_stack.yaml")

    # 4) config/policies.yaml - keep _defaults, replace roles
    try:
        existing = yaml.safe_load((CONFIG_DIR / "policies.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        existing = {}
    defaults = existing.get("_defaults") or {}
    leader_baseline = (defaults.get("leader") or {}).get("tools_baseline") or []
    worker_baseline = (defaults.get("worker") or {}).get("tools_baseline") or []
    new_policies: dict[str, dict] = {}
    for role in roles_to_install:
        rid = role["id"]
        is_leader = role["tier"] == "leader"
        tools = list(leader_baseline if is_leader else worker_baseline)
        if is_leader:
            tools += [f"delegate.to_{d}" for d in (role.get("delegates_to") or [])]
        if rid == "ceo":
            tools += ["budget.get_report", "budget.log_expense", "budget.sync_from_analytics",
                      "budget.request_user_approval", "analytics.usage_check",
                      "analytics.cost_report", "analytics.usage_report"]
        elif rid == "cfo":
            tools += ["analytics.usage_check", "analytics.cost_report",
                      "analytics.usage_report", "budget.sync_from_analytics"]
        new_policies[rid] = {
            "delegate_to": role.get("delegates_to") or [],
            "can_request_new_agent": is_leader,
            "can_approve_budget": rid == "ceo",
            "can_escalate_to_user": is_leader,
            "writes_code": not is_leader,
            "allow_subagent_spawn": is_leader,
            "tools": tools,
        }
    existing["roles"] = new_policies
    (CONFIG_DIR / "policies.yaml").write_text(
        "# Hierarchy and permissions policies - generated by the setup wizard\n" +
        yaml.safe_dump(existing, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    written.append("config/policies.yaml")

    # 5) config/budget.yaml - update monthly_cap
    try:
        budget_doc = yaml.safe_load((CONFIG_DIR / "budget.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        budget_doc = {}
    budget_doc.setdefault("currency", "USD")
    budget_doc.setdefault("totals", {})
    budget_doc["totals"]["monthly_cap"] = float(monthly_budget)
    budget_doc["totals"].setdefault("soft_warning_at", 0.75)
    budget_doc["totals"].setdefault("hard_block_at", 0.95)
    budget_doc.setdefault("thresholds", {"single_decision_cap": max(10.0, float(monthly_budget) * 0.5)})
    budget_doc.setdefault("agent_costs_monthly", {})
    (CONFIG_DIR / "budget.yaml").write_text(
        "# TeamForge budget settings - monthly_cap set via setup wizard\n" +
        yaml.safe_dump(budget_doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    written.append("config/budget.yaml")

    # 6) state/setup_complete.json
    SETUP_FLAG.write_text(json.dumps({
        "completed": True,
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_name": project.get("name", ""),
        "domain": project.get("domain", ""),
        "language": language,
        "monthly_budget": float(monthly_budget),
        "role_count": len(roles_to_install),
        "selected_from_custom": selected_role_ids is not None,
    }, indent=2), encoding="utf-8")
    written.append("state/setup_complete.json")

    return {"written": written, "role_count": len(roles_to_install),
            "monthly_budget": float(monthly_budget), "language": language}
