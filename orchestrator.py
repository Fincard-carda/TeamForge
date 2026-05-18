"""TeamForge agent team's giris noktasi — dual-agent (CEO + CFO)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
)

from tools import config_loader, dashboard, live_log, runtime  # noqa: E402
from tools.approval import broker  # noqa: E402
from tools.briefs import BRIEF_TOOLS  # noqa: E402
from tools.budget import BUDGET_TOOLS, compute_snapshot  # noqa: E402
from tools.config_io import CONFIG_TOOLS  # noqa: E402
from tools.delegation import DELEGATION_TOOLS  # noqa: E402
from tools.jobs import JOB_TOOLS, JobManager  # noqa: E402
from tools.knowledge import KNOWLEDGE_TOOLS  # noqa: E402
from tools.runtime import DISALLOWED_BUILTINS  # noqa: E402
from tools.scrum import SCRUM_TOOLS  # noqa: E402
from tools.task_board import TASK_TOOLS  # noqa: E402
from tools.team_management import TEAM_TOOLS, ensure_baseline_registry  # noqa: E402
from tools.analytics import ANALYTICS_TOOLS  # noqa: E402
from tools.viz import VIZ_TOOLS  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)


def setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "orchestrator.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


log = logging.getLogger("teamforge.orchestrator")


# All tool'larin single bir registry'de toplanmasi — top-level agent'lar (CEO, CFO)
# this registry'den policy.tools listne gore kendi tool setini receives.
def _global_registry() -> dict[str, object]:
    return {
        "budget.get_report": BUDGET_TOOLS[0],
        "budget.log_expense": BUDGET_TOOLS[1],
        "budget.request_user_approval": BUDGET_TOOLS[2],
        "budget.sync_from_analytics": BUDGET_TOOLS[3],
        "team.list_team": TEAM_TOOLS[0],
        "team.request_new_agent": TEAM_TOOLS[1],
        "team.evaluate_new_agent_request": TEAM_TOOLS[2],
        "team.spawn_agent": TEAM_TOOLS[3],
        "team.direct_spawn_agent": TEAM_TOOLS[4],
        "tasks.create": TASK_TOOLS[0],
        "tasks.list": TASK_TOOLS[1],
        "tasks.list_mine": TASK_TOOLS[2],
        "tasks.update": TASK_TOOLS[3],
        "tasks.assign": TASK_TOOLS[4],
        "tasks.review": TASK_TOOLS[5],
        "knowledge.read_docs": KNOWLEDGE_TOOLS[0],
        "knowledge.write_spec": KNOWLEDGE_TOOLS[1],
        "knowledge.write_artifact": KNOWLEDGE_TOOLS[2],
        "knowledge.write_decision": KNOWLEDGE_TOOLS[3],
        "knowledge.read_artifact": KNOWLEDGE_TOOLS[4],
        "knowledge.list_artifacts": KNOWLEDGE_TOOLS[5],
        "delegate.to_pm": DELEGATION_TOOLS[0],
        "delegate.to_ba": DELEGATION_TOOLS[1],
        "delegate.to_worker": DELEGATION_TOOLS[2],
        "delegate.to_tech_lead": DELEGATION_TOOLS[3],
        "delegate.to_cfo": DELEGATION_TOOLS[4],
        "delegate.to_ceo": DELEGATION_TOOLS[5],
        "delegate.peer_review": DELEGATION_TOOLS[6],
        "delegate.check_result": JOB_TOOLS[0],
        "delegate.read_inbox": JOB_TOOLS[1],
        "delegate.list_pending": JOB_TOOLS[2],
        "delegate.cancel_job": JOB_TOOLS[3],
        "config.update_team_count": CONFIG_TOOLS[0],
        "config.update_budget_cost": CONFIG_TOOLS[1],
        "config.show_config_audit": CONFIG_TOOLS[2],
        "config.update_role_profile": CONFIG_TOOLS[3],
        "config.update_role_model": CONFIG_TOOLS[4],
        "config.update_role_max_turns": CONFIG_TOOLS[5],
        "config.read_prompt": CONFIG_TOOLS[6],
        "config.write_prompt": CONFIG_TOOLS[7],
        "config.append_to_prompt": CONFIG_TOOLS[8],
        "brief.save": BRIEF_TOOLS[0],
        "brief.load": BRIEF_TOOLS[1],
        "brief.list_all": BRIEF_TOOLS[2],
        "scrum.start_sprint": SCRUM_TOOLS[0],
        "scrum.current_sprint": SCRUM_TOOLS[1],
        "scrum.list_sprints": SCRUM_TOOLS[2],
        "scrum.close_sprint": SCRUM_TOOLS[3],
        "scrum.log_ceremony": SCRUM_TOOLS[4],
        "scrum.list_ceremonies": SCRUM_TOOLS[5],
        "scrum.report_to_ceo": SCRUM_TOOLS[6],
        "scrum.read_ceo_inbox": SCRUM_TOOLS[7],
        "scrum.mark_inbox_read": SCRUM_TOOLS[8],
        "analytics.usage_check": ANALYTICS_TOOLS[0],
        "analytics.cost_report": ANALYTICS_TOOLS[1],
        "analytics.usage_report": ANALYTICS_TOOLS[2],
        "analytics.audit_log": ANALYTICS_TOOLS[3],
        "viz.table": VIZ_TOOLS[0],
        "viz.bar_chart": VIZ_TOOLS[1],
        "viz.line_chart": VIZ_TOOLS[2],
        "viz.kpi_card": VIZ_TOOLS[3],
        "viz.mermaid": VIZ_TOOLS[4],
    }


def _build_agent_options(role: str) -> ClaudeAgentOptions:
    """Top-level agent (CEO or CFO) for ClaudeAgentOptions produces."""
    policy = config_loader.policies().get("roles", {}).get(role, {})
    allowed = set(policy.get("tools", []))
    registry = _global_registry()
    tools = [registry[n] for n in allowed if n in registry]

    server_name = f"teamforge-{role}"
    server = create_sdk_mcp_server(name=server_name, version="1.0.0", tools=tools)

    allowed_tool_names: list[str] = []
    for t in tools:
        tn = getattr(t, "name", None) or getattr(t, "__name__", None)
        if tn:
            allowed_tool_names.append(f"mcp__{server_name}__{tn}")

    sys_prompt = runtime.load_prompt(role)
    model = os.environ.get("CLAUDE_MODEL_LEAD") or os.environ.get("CLAUDE_MODEL")
    kwargs: dict[str, object] = {
        "system_prompt": sys_prompt,
        "mcp_servers": {server_name: server},
        "allowed_tools": allowed_tool_names,
        "disallowed_tools": list(DISALLOWED_BUILTINS),
        "permission_mode": "bypassPermissions",
        "max_turns": 80,
        "cwd": str(PROJECT_ROOT),
    }
    if model:
        kwargs["model"] = model
    return ClaudeAgentOptions(**kwargs)


def print_user(text: str, target: str = "ceo") -> None:
    color = "\033[36m" if target == "ceo" else "\033[35m"
    print(f"\n{color}you -> {target}\033[0m> {text}")


def print_system(text: str) -> None:
    print(f"\n\033[33m[system]\033[0m {text}")


def print_approval(req) -> None:
    print("\n" + "=" * 60)
    print(f"\033[31m[APPROVAL NEEDED]\033[0m  {req.title}  (id={req.id})")
    print("-" * 60)
    print(req.summary)
    if req.details:
        print("-" * 60)
        for k, v in req.details.items():
            print(f"  {k}: {v}")
    print("=" * 60)


async def stdin_reader(q: asyncio.Queue) -> None:
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input)
        except EOFError:
            await q.put("/quit")
            return
        await q.put(line)


async def dashboard_chat_reader(q: asyncio.Queue) -> None:
    """Browser /api/chat'tan gelen mesajlari (target ile together) stdin_q'ya pump eder.

    Dashboard mesajlari `<target>:<message>` seklinde formskipnir, REPL same
    parser'i kullanir. target= "ceo" or "cfo".
    """
    srv = dashboard.get_server()
    if srv is None:
        return
    while True:
        try:
            item = await srv.chat_queue.get()
        except asyncio.CancelledError:
            return
        # item: dict {message, target} or plain str (legacy)
        if isinstance(item, dict):
            target = (item.get("target") or "ceo").lower()
            msg = item.get("message", "")
            line = f"/{target} {msg}" if target in ("ceo", "cfo") else msg
        else:
            line = str(item)
        await q.put(line)
        print_system(f"Browser'dan: {line[:80]}{'...' if len(line) > 80 else ''}")


async def approval_handler(stdin_q: asyncio.Queue) -> None:
    b = broker()
    while True:
        req = await b.next_pending()
        print_approval(req)
        ans = await stdin_q.get()
        b.resolve(req.id, ans.strip() or "approve")
        print_system(f"Approval sendildi ({req.id}): {ans.strip() or 'approve'}")


async def run_agent_turn(client: ClaudeSDKClient, role: str, user_msg: str) -> None:
    with live_log.scope(role, caller="user"):
        await client.query(user_msg)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        live_log.text(role, block.text)
                    elif isinstance(block, ToolUseBlock):
                        live_log.tool(role, getattr(block, "name", "?"),
                                      getattr(block, "input", {}))


def parse_target(line: str) -> tuple[str, str]:
    """`/cfo merhaba` -> ('cfo', 'merhaba'). Default: ceo."""
    s = line.strip()
    for tag in ("/cfo ", "/CFO "):
        if s.startswith(tag):
            return ("cfo", s[len(tag):].strip())
    if s.lower() == "/cfo":
        return ("cfo", "")
    for tag in ("/ceo ", "/CEO "):
        if s.startswith(tag):
            return ("ceo", s[len(tag):].strip())
    if s.lower() == "/ceo":
        return ("ceo", "")
    return ("ceo", s)


HELP_TEXT = """
Routing:
  /ceo <mesaj>   — CEO'ya mesaj (default; prefix writingsan da CEO'ya goes)
  /cfo <mesaj>   — CFO'ya mesaj (finansal, fiyskipndirma, marketing yonetimi)

Commandlar:
  /team /budget /tasks /briefs /sprint /quiet /loud /chain /help /quit
  /closeall      — CEO + CFO + all lower to layers guvenli closema broadcast
                   (her one kendi brief.save'ini calls; next /quit you can do)
  /inbox         — CEO/CFO inbox filledluk summaryi (async result donors)
  /jobs          — Calismakta olan async job list

Tarayicidan: http://localhost:7777  (target dropdown ile CEO/CFO choicei)
""".strip()


async def budget_monitor(stdin_q: asyncio.Queue) -> None:
    """Periodic real-spend checke — esik asilirsa CEO'yu triggers.

    - Her TEAMFORGE_BUDGET_CHECK_INTERVAL_MIN minuteda Anthropic API'den
      last 30 daily real spendyi cek (cache'li, cheap).
    - monthly_cap'e gore ratio:
        >= hard_block_threshold (default 0.95) -> CEO'ya ACIL mesaji enjekte
        >= soft_warning_threshold (default 0.75) -> CEO'ya warning mesaji enjekte
        under -> silent
    - Defensive: error olursa only log'lar, orchestrator'i doesn't break.
    """
    try:
        interval_min = max(5, int(os.environ.get(
            "TEAMFORGE_BUDGET_CHECK_INTERVAL_MIN", "60")))
    except (TypeError, ValueError):
        interval_min = 60
    # First check kisa initial gecikmesi aftersi (orchestrator ssubjectlize olsun)
    # This first fetch same zamanda /api/state cache'ini populate eder — dashboard
    # header'da real spend hizla gozuksun.
    await asyncio.sleep(5)
    last_alert_level: str | None = None  # "warn", "block" — spam prevents
    while True:
        try:
            from tools import analytics, budget as budget_mod
            if not analytics.has_admin_key():
                # Admin key none — ses cikarma, but 30 dk next tekrar bak
                await asyncio.sleep(min(interval_min, 30) * 60)
                continue
            loop = asyncio.get_running_loop()
            cost = await loop.run_in_executor(
                None, analytics.fetch_cost_report, 30)
            real_total = float(cost.get("total") or 0)
            snap = budget_mod.compute_snapshot()
            cap = float(snap.get("monthly_cap") or 0)
            soft = float(snap.get("soft_warning_threshold") or 0.75)
            hard = float(snap.get("hard_block_threshold") or 0.95)
            if cap > 0:
                ratio = real_total / cap
                if ratio >= hard:
                    level = "block"
                    if last_alert_level != level:
                        msg = (f"/ceo BUTCE HARD BLOCK: real spend "
                               f"${real_total:.2f}/${cap:.0f} (%{ratio*100:.0f}). "
                               "Yeni spendyi DURDUR, continue eden async job'lari list, "
                               "userya critical state reportu sun and approval here.")
                        await stdin_q.put(msg)
                        last_alert_level = level
                elif ratio >= soft:
                    level = "warn"
                    if last_alert_level != level:
                        msg = (f"/ceo BUTCE UYARISI: real spend "
                               f"${real_total:.2f}/${cap:.0f} (%{ratio*100:.0f}). "
                               "budget.sync_from_analytics do, state report, "
                               "userya optimization (caching, model downgrade) recommendi sun.")
                        await stdin_q.put(msg)
                        last_alert_level = level
                else:
                    last_alert_level = None  # healthy — bir next esige ready
        except Exception as e:
            print_system(f"Budget monitor error: {e}")
        await asyncio.sleep(interval_min * 60)


async def main_async() -> int:
    setup_logging()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print_system("ANTHROPIC_API_KEY not found.")
        return 2

    transcript = live_log.start_transcript()
    print_system(f"Transcript: {transcript.relative_to(PROJECT_ROOT)}")

    # Prompt cache state — token savings for ENABLE_PROMPT_CACHING_1H recommendation
    cache_1h = os.environ.get("ENABLE_PROMPT_CACHING_1H", "").lower() in ("1", "true", "on")
    cache_disabled = os.environ.get("DISABLE_PROMPT_CACHING", "").lower() in ("1", "true", "on")
    if cache_disabled:
        print_system("UYARI: Prompt caching DISABLE_PROMPT_CACHING=1 ile kapali. Yuksek token costi.")
    elif cache_1h:
        print_system("Prompt caching: 1h TTL active (input token %50-70 savings binding)")
    else:
        print_system("Prompt caching: 5dk default. 1h for .env'e ENABLE_PROMPT_CACHING_1H=1 add")

    if os.environ.get("TEAMFORGE_DASHBOARD", "on").lower() not in ("off", "false", "0"):
        try:
            port = int(os.environ.get("TEAMFORGE_DASHBOARD_PORT", "7777"))
            srv = dashboard.DashboardServer(port=port)
            url = await srv.start()
            dashboard.set_server(srv)
            print_system(f"Dashboard: {url}")
            # Automatic browser ac — TEAMFORGE_AUTO_OPEN=off ile closeilabilir
            if os.environ.get("TEAMFORGE_AUTO_OPEN", "on").lower() not in ("off", "false", "0"):
                try:
                    import webbrowser
                    # Server'in tam ayaga kalkmasi for 0.5s badd, next ac
                    async def _open_later():
                        await asyncio.sleep(0.5)
                        try:
                            webbrowser.open(url)
                            print_system(f"Browser automatic opening: {url}")
                        except Exception as e:
                            print_system(f"Browser auto-open failed: {e}")
                    asyncio.create_task(_open_later())
                except Exception as e:
                    print_system(f"webbrowser import errorsi: {e}")
        except Exception as e:
            print_system(f"Dashboard error: {e}")

    ensure_baseline_registry()
    snap = compute_snapshot()
    print_system(f"Team ready. Budget: {snap['month_spend']:.0f}/{snap['monthly_cap']:.0f} {snap['currency']}")

    from tools.briefs import get_brief_text
    if get_brief_text("ceo"):
        print_system("Beforeki CEO brief'i bulundu.")
    if get_brief_text("cfo"):
        print_system("Beforeki CFO brief'i bulundu.")

    from tools import state_store
    inbox = state_store.read("ceo_inbox", {"messages": []})
    unread = [m for m in inbox.get("messages", []) if not m.get("read")]
    if unread:
        print_system(f"CEO inbox'ta {len(unread)} okunmamis mesaj var.")

    print_system("CEO or CFO ile konusmaya bnever. Default CEO; '/cfo ...' ile CFO.")
    print_system("/help command list for.")

    stdin_q: asyncio.Queue = asyncio.Queue()

    # JobManager auto-wake — async job resultu top-level agent'a gelirse
    # stdin_q'ya wake mesaji push'la.
    job_mgr = JobManager.get()
    job_mgr.set_loop(asyncio.get_running_loop())

    async def _wake_top_level(caller: str, job_id: str) -> None:
        """Async job resultu top-level (CEO/CFO) inbox'una dustuday
        agent'i uyandirmak for stdin_q'ya wake mesaji head.
        """
        if caller not in ("ceo", "cfo"):
            return
        job = job_mgr.get_job(job_id) or {}
        subj = job.get("subject", "(adsiz)")
        from_role = job.get("role", "?")
        wake_line = (
            f"/{caller} [SISTEM-WAKE] Async result geldi: job={job_id} "
            f"({from_role} -> you) topic: {subj[:60]}. "
            f"Inbox'i emptyaltmak for: delegate.read_inbox(role=\"{caller}\", drain=true)"
        )
        try:
            await stdin_q.put(wake_line)
            print_system(f"[wake] {caller} <- job {job_id} ({from_role})")
        except Exception as e:
            print_system(f"Wake failed: {e}")

    job_mgr.set_wake_callback(_wake_top_level)
    tasks = [
        asyncio.create_task(stdin_reader(stdin_q), name="stdin"),
        asyncio.create_task(approval_handler(stdin_q), name="approvals"),
        asyncio.create_task(dashboard_chat_reader(stdin_q), name="dashboard-chat"),
    ]
    # Periodic budget monitoru — esik asilirsa CEO'ya automatic tetikleme
    if os.environ.get("TEAMFORGE_BUDGET_MONITOR", "on").lower() not in ("off", "false", "0"):
        tasks.append(asyncio.create_task(budget_monitor(stdin_q), name="budget-monitor"))
        print_system("Budget monitor: active (her hour real spendyi pulling)")

    # Setup check: prompts/ empty or setup_complete nonesa dashboard'da setup wizard'a redirect
    from tools import setup_wizard
    if not setup_wizard.is_setup_complete():
        print_system("=" * 60)
        print_system("FIRST RUN: setup not completed yet.")
        print_system("Open the dashboard and describe your project — your agent team will be generated.")
        print_system("  -> http://127.0.0.1:7777")
        print_system("After setup finishes, stop the orchestrator with Ctrl+C and start it again.")
        print_system("=" * 60)
        # Dashboard ayakta, only badd (Ctrl+C ile remove)
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            return 0

    # Team.yaml'dan lider rolesi load, dynamic agent startma
    try:
        team_cfg = config_loader.team()
        roles_cfg = team_cfg.get("roles") or {}
        leader_roles = [rid for rid, r in roles_cfg.items()
                        if (r.get("tier") == "leader") or rid in ("ceo", "cfo")]
        if not leader_roles:
            print_system("No leader roles found in team.yaml. Re-run setup.")
            return 1
    except Exception as e:
        print_system(f"team.yaml okuma errorsi: {e}")
        return 1

    if "ceo" not in roles_cfg or "cfo" not in roles_cfg:
        print_system("Both CEO and CFO roles are required. Re-run setup.")
        return 1

    try:
        ceo_options = _build_agent_options("ceo")
        cfo_options = _build_agent_options("cfo")
        async with ClaudeSDKClient(options=ceo_options) as ceo, \
                   ClaudeSDKClient(options=cfo_options) as cfo:
            agents = {"ceo": ceo, "cfo": cfo}
            while True:
                print("\nsen> ", end="", flush=True)
                try:
                    line = await stdin_q.get()
                except asyncio.CancelledError:
                    break
                line = line.rstrip("\n")
                if not line:
                    continue

                if line.startswith("/") and not line.lower().startswith(("/cfo", "/ceo")):
                    cmd = line.strip().lower()
                    if cmd in ("/q", "/quit", "/exit"):
                        break
                    if cmd == "/help":
                        print(HELP_TEXT); continue
                    if cmd == "/quiet":
                        live_log.set_quiet(True); print_system("Silent."); continue
                    if cmd == "/loud":
                        live_log.set_quiet(False); print_system("Active."); continue
                    if cmd == "/chain":
                        print_system(f"Zincir: {live_log.chain_str()}"); continue
                    if cmd in ("/closeall", "/save", "/saveall"):
                        # Both CEO and CFO'ya guvenli closema sinyali — paralel
                        print_system("Guvenli closema broadcast: CEO + CFO + lower layers...")
                        close_msg = (
                            "This the session guvenli close: kendi lower katminstantdaki all agent'lara "
                            "cascade et (her one brief.save should call), next kendi brief.save'ini "
                            "call. Bittiginde how many brief yazildigi and next sessionda nereden "
                            "continue edilecegi about kisa bir report don."
                        )
                        try:
                            await run_agent_turn(agents["ceo"], "ceo", close_msg)
                        except Exception as e:
                            print_system(f"CEO closema errorsi: {e}")
                        try:
                            await run_agent_turn(agents["cfo"], "cfo", close_msg)
                        except Exception as e:
                            print_system(f"CFO closema errorsi: {e}")
                        print_system("All brief'ler yazildi. /quit ile you can exit.")
                        continue
                    if cmd == "/sprint":
                        sd = state_store.read("sprints", {"sprints": []})
                        active = [s for s in sd.get("sprints", []) if s.get("status") == "active"]
                        if active:
                            s = active[-1]
                            print(f"  {s['id']}  {s['name']}  ({s['started_at'][:10]} -> {s['ends_at'][:10]})")
                        else:
                            print("  (active sprint none)")
                        continue
                    if cmd == "/team":
                        reg = state_store.read("team_registry", {"agents": []})
                        by_role: dict[str, int] = {}
                        for a in reg.get("agents", []):
                            if a.get("status") == "active":
                                by_role[a["role"]] = by_role.get(a["role"], 0) + 1
                        for r, n in sorted(by_role.items()):
                            print(f"  {r:28s} x {n}")
                        continue
                    if cmd == "/budget":
                        s = compute_snapshot()
                        print(f"{s['month_spend']:.0f}/{s['monthly_cap']:.0f} {s['currency']} ({s['month_ratio']*100:.1f}%)")
                        continue
                    if cmd == "/tasks":
                        board = state_store.read("tasks", {"tasks": []})
                        for t in board.get("tasks", []):
                            print(f"  {t['id']}  [{t['status']:14s}]  "
                                  f"{t.get('assigned_role','-'):28s}  {t['title']}")
                        if not board.get("tasks"):                            print("  (no tasks)")
                        continue
                    if cmd == "/briefs":
                        briefs_path = Path("state/briefs")
                        if not briefs_path.exists():
                            print("  (none)"); continue
                        for b in sorted(briefs_path.glob("*.md")):
                            print(f"  {b.stem:28s}  {b.stat().st_size}B")
                        continue
                    if cmd == "/inbox":
                        # CEO and CFO inbox'larini quick view (debug)
                        for r in ("ceo", "cfo"):
                            items = JobManager.get().inbox_for(r, drain=False)
                            print(f"  {r}: {len(items)} pending")
                        continue
                    if cmd == "/jobs":
                        items = JobManager.get().list_pending()
                        print(f"  Pending/running: {len(items)}")
                        for j in items:
                            print(f"    {j['id']}  {j.get('caller','?')} -> "
                                  f"{j.get('role','?')}  [{j.get('status')}]")
                        continue
                    print_system(f"Bilinmeyen: {cmd}"); continue
                target, msg = parse_target(line)
                if not msg:
                    print_system(f"{target} for mesaj empty."); continue
                print_user(msg, target=target)
                await run_agent_turn(agents[target], target, msg)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        srv = dashboard.get_server()
        if srv:
            try:
                await srv.stop()
            except Exception:
                pass

    print_system("Gorusmek uzere.")
    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(main_async()))
    except KeyboardInterrupt:
        print_system("Kesildi.")
        sys.exit(130)


if __name__ == "__main__":
    main()
