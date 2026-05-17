"""Agent runma katmani — Windows CMD arg limit safe (system_prompt <= 16KB)."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
)

from . import config_loader, live_log

log = logging.getLogger("teamforge.runtime")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

PROMPT_FILES = {
    "ceo": "ceo.md", "cfo": "cfo.md",
    "project_manager": "pm.md", "business_analyst": "ba.md",
    "tech_lead": "tech_lead.md", "android_dev": "android_dev.md",
    "ios_dev": "ios_dev.md", "uiux_dev": "uiux_dev.md",
    "frontend_dev": "frontend_dev.md", "backend_dev": "backend_dev.md",
    "mobile_tester": "mobile_tester.md", "tester": "tester.md",
    "marketing_sales_specialist": "marketing_sales_specialist.md",
    "devops_engineer": "devops_engineer.md",
}

DISALLOWED_BUILTINS = [
    "Bash", "BashOutput", "KillBash", "KillShell",
    "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "Glob", "Grep", "WebFetch", "WebSearch",
    "Task", "ExitPlanMode", "TodoWrite",
    "SlashCommand", "Skill",
]

BUILTIN_TOOL_MAP = {
    "web_search": "WebSearch",
    "web_fetch": "WebFetch",
}


# KISA referans — full versiyonlar docs/ forde, agent ihtiyac duydugunda okur
SHORT_REFERENCES = """

## Davranis kurallari (summary)

1. **Built-in tool forbidden** — Edit, Bash, Read, Write, Glob, Grep, Task, Skill kapali. Only MCP tool'lari (config.*, code.*, knowledge.*, brief.*, tasks.*, delegate.*).
2. **Anti-halusinasyon** — Bilmiyorsan "BILMIYORUM" de. Iddia beforesi tool call. Output sonuna "Sources:" add. Detail: `knowledge.read_docs("GUARD_RAILS.md")`
3. **Session acilis/kapanis** — Beforeki brief'i `brief.load` ile cek, closeirken `brief.save`. Detail: `knowledge.read_docs("SESSION_PROTOCOL.md")`
4. **Rol disi gorev** — Manifestondaki "yapmayacaklarim"in bir gorev gelirse reddet, correct role redirect.
"""


def load_prompt(role: str) -> str:
    """System prompt'u create — Windows arg limit safe.

    Only role spec (.md) + kisa davranis summaryi. Brief automatic prepend EDILMEZ;
    agent first turn'de `brief.load(role)` calls. tech_stack inject EDILMEZ;
    agent ihtiyac duyarsa `knowledge.read_docs("tech_stack.yaml")` calls.
    """
    fname = PROMPT_FILES.get(role)
    if not fname:
        raise ValueError(f"Bilinmeyen rol: {role}")
    p = PROMPTS_DIR / fname
    if not p.exists():
        raise FileNotFoundError(f"Prompt filesi none: {p}")

    return p.read_text(encoding="utf-8") + SHORT_REFERENCES


_load_prompt = load_prompt


def get_resume_message(role: str) -> str | None:
    """Beforeki brief if exists first user message olarak sendmek for sting don.
    None: brief none."""
    try:
        from . import briefs
        text = briefs.get_brief_text(role)
        if text:
            return (f"[RESUME] Beforeki the sessionn brief'i:\n\n{text}\n\n"
                    f"Yukaridaki brief'e gore 'In-progress' and 'Next steps' "
                    f"maddelerinden continue et. If brief eski/yanlissa "
                    f"`brief.load(role=\"{role}\")` ile yeni cek.")
    except Exception:
        pass
    return None


def _collect_tools_for_role(role: str) -> list:
    from . import briefs as brief_tools
    from . import budget as budget_tools
    from . import code_io
    from . import config_io
    from . import delegation
    from . import knowledge as knowledge_tools
    from . import task_board
    from . import team_management

    policy = config_loader.policies().get("roles", {}).get(role, {})
    allowed = set(policy.get("tools", []))

    registry: dict[str, Any] = {}

    def _add(prefix: str, funcs: list, names: list[str]):
        for f, n in zip(funcs, names):
            registry[f"{prefix}.{n}"] = f

    _add("budget", budget_tools.BUDGET_TOOLS,
         ["get_report", "log_expense", "request_user_approval", "sync_from_analytics"])
    _add("team", team_management.TEAM_TOOLS,
         ["list_team", "request_new_agent", "evaluate_new_agent_request",
          "spawn_agent", "direct_spawn_agent"])
    _add("tasks", task_board.TASK_TOOLS,
         ["create", "list", "list_mine", "update", "assign", "review"])
    _add("knowledge", knowledge_tools.KNOWLEDGE_TOOLS,
         ["read_docs", "write_spec", "write_artifact", "write_decision",
          "read_artifact", "list_artifacts"])
    _add("delegate", delegation.DELEGATION_TOOLS,
         ["to_pm", "to_ba", "to_worker", "to_tech_lead", "to_cfo",
          "to_ceo", "peer_review"])
    from . import jobs as jobs_module
    _add("delegate", jobs_module.JOB_TOOLS,
         ["check_result", "read_inbox", "list_pending", "cancel_job"])
    _add("code", code_io.CODE_TOOLS, ["write_file", "read_file"])
    _add("config", config_io.CONFIG_TOOLS,
         ["update_team_count", "update_budget_cost", "show_config_audit",
          "update_role_profile", "update_role_model", "update_role_max_turns",
          "read_prompt", "write_prompt", "append_to_prompt"])
    _add("brief", brief_tools.BRIEF_TOOLS, ["save", "load", "list_all"])

    from . import scrum as scrum_tools
    _add("scrum", scrum_tools.SCRUM_TOOLS,
         ["start_sprint", "current_sprint", "list_sprints", "close_sprint",
          "log_ceremony", "list_ceremonies", "report_to_ceo",
          "read_ceo_inbox", "mark_inbox_read"])

    from . import analytics as analytics_tools
    _add("analytics", analytics_tools.ANALYTICS_TOOLS,
         ["usage_check", "cost_report", "usage_report", "audit_log"])

    from . import viz as viz_tools
    _add("viz", viz_tools.VIZ_TOOLS,
         ["table", "bar_chart", "line_chart", "kpi_card", "mermaid"])

    selected = []
    for name in allowed:
        fn = registry.get(name)
        if fn is not None:
            selected.append(fn)
    return selected


def _model_for_role(role: str) -> str | None:
    team = config_loader.team().get("roles", {})
    role_cfg = team.get(role, {})
    model = role_cfg.get("model")
    if isinstance(model, str) and model.startswith("${"):
        return None
    return model


async def run_agent(role: str, prompt: str, caller: str = "user") -> dict:
    log.info("delegation %s -> %s: %s", caller, role, (prompt or "")[:120])
    sys_prompt = load_prompt(role)
    tools = _collect_tools_for_role(role)
    server = create_sdk_mcp_server(
        name=f"teamforge-{role}", version="1.0.0", tools=tools,
    )

    allowed_tool_names = []
    for t in tools:
        tool_name = getattr(t, "name", None) or getattr(t, "__name__", None)
        if tool_name:
            allowed_tool_names.append(f"mcp__teamforge-{role}__{tool_name}")

    max_turns = int(
        config_loader.team().get("roles", {}).get(role, {}).get("max_turns", 40)
    )
    model = _model_for_role(role) or os.environ.get("CLAUDE_MODEL")

    disallowed = list(DISALLOWED_BUILTINS)
    policy = config_loader.policies().get("roles", {}).get(role, {})
    role_tools = set(policy.get("tools", []))
    for policy_name, builtin_name in BUILTIN_TOOL_MAP.items():
        if policy_name in role_tools and builtin_name in disallowed:
            disallowed.remove(builtin_name)

    opts_kwargs: dict[str, Any] = {
        "system_prompt": sys_prompt,
        "mcp_servers": {f"teamforge-{role}": server},
        "allowed_tools": allowed_tool_names,
        "disallowed_tools": disallowed,
        "permission_mode": "bypassPermissions",
        "max_turns": max_turns,
        "cwd": str(PROJECT_ROOT),
    }
    if model:
        opts_kwargs["model"] = model

    options = ClaudeAgentOptions(**opts_kwargs)

    # Brief if exists, prompt'a add (system_prompt instead of user message'a)
    resume = get_resume_message(role)
    effective_prompt = (resume + "\n\n[YENI MESAJ]\n" + prompt) if resume else prompt

    collected: list[str] = []
    with live_log.scope(role, caller):
        try:
            async for msg in query(prompt=effective_prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            collected.append(block.text)
                            live_log.text(role, block.text)
                        elif isinstance(block, ToolUseBlock):
                            live_log.tool(role, getattr(block, "name", "?"),
                                          getattr(block, "input", {}))
        except Exception as e:
            log.exception("Agent error: %s", role)
            live_log.text(role, f"[HATA] {e}")
            return {"content": [{"type": "text",
                                  "text": f"[HATA] {role} callsi failed: {e}"}],
                    "is_error": True}

    full_text = "\n\n".join(t for t in collected if t)
    if not full_text:
        full_text = f"[BOS YANIT] {role} hicbir text uretmedi (only tool calllari yapmis olabilir)"
    return {"content": [{"type": "text", "text": full_text}]}
