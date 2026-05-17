"""TeamForge live dashboard — localhost web UI + chat input + analytics."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from . import config_loader, state_store

log = logging.getLogger("teamforge.dashboard")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = Path(__file__).parent / "dashboard.html"


class DashboardServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 7777,
                 history_size: int = 1000):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/api/state", self._handle_state)
        self.app.router.add_get("/api/analytics", self._handle_analytics)
        self.app.router.add_get("/api/analytics/workspaces", self._handle_workspaces)
        self.app.router.add_post("/api/chat", self._handle_chat)
        self.app.router.add_get("/ws", self._handle_ws)
        # Setup wizard (first acilis)
        self.app.router.add_get("/api/setup/status", self._handle_setup_status)
        self.app.router.add_post("/api/setup/generate", self._handle_setup_generate)
        self.app.router.add_post("/api/setup/save", self._handle_setup_save)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._clients: set[web.WebSocketResponse] = set()
        self._history: deque = deque(maxlen=history_size)
        self._agent_state: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"status": "idle", "caller": None, "last_text": "",
                     "last_tool": "", "last_at": None}
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self.chat_queue: asyncio.Queue = asyncio.Queue()

    async def start(self) -> str:
        self._loop = asyncio.get_running_loop()
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        url = f"http://{self.host}:{self.port}/"
        log.info("Dashboard up at %s", url)
        return url

    async def stop(self) -> None:
        # Before all WS client'lari nazikce close (CancelledError noise'u prevents)
        for ws in list(self._clients):
            try:
                if not ws.closed:
                    await ws.close(code=1001, message=b"server shutdown")
            except Exception:
                pass
        self._clients.clear()
        if self._runner:
            try:
                await self._runner.cleanup()
            except Exception:
                pass

    async def _handle_index(self, request: web.Request) -> web.Response:
        try:
            html = HTML_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            html = "<h1>dashboard.html bulunamadi</h1>"
        return web.Response(text=html, content_type="text/html")

    async def _handle_setup_status(self, request: web.Request) -> web.Response:
        from . import setup_wizard
        return web.json_response({
            "completed": setup_wizard.is_setup_complete(),
            "anthropic_key_present": bool(__import__("os").environ.get("ANTHROPIC_API_KEY")),
        })

    async def _handle_setup_generate(self, request: web.Request) -> web.Response:
        """User proje aciklama send, Claude rol/tech spec produces."""
        from . import setup_wizard
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "JSON required"}, status=400)
        desc = (data.get("description") or "").strip()
        if not desc:
            return web.json_response({"ok": False, "error": "description empty can't be"}, status=400)
        try:
            spec = await setup_wizard.generate_team_async(desc)
            return web.json_response({"ok": True, "spec": spec})
        except Exception as e:
            log.exception("setup generate failed")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_setup_save(self, request: web.Request) -> web.Response:
        """Approvallanan spec'i filelara write, setup_complete flag at."""
        from . import setup_wizard
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "JSON required"}, status=400)
        spec = data.get("spec")
        if not isinstance(spec, dict):
            return web.json_response({"ok": False, "error": "spec dict must be"}, status=400)
        try:
            result = await __import__("asyncio").get_running_loop().run_in_executor(
                None, setup_wizard.save_spec, spec)
            return web.json_response({"ok": True, **result})
        except Exception as e:
            log.exception("setup save failed")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_state(self, request: web.Request) -> web.Response:
        from .budget import compute_snapshot
        from . import analytics
        try:
            snap = compute_snapshot()
        except Exception:
            snap = {}
        # Real Anthropic spend — SADECE CACHE'DEN read, /api/state 5sn'de
        # bir calling; rate limit'i tuketmemek for fresh fetch YAPMA.
        # Cache budget_monitor (hourly) and Analytics modal "Refresh" tarafindan
        # populate is done.
        real_cost = {"total": 0.0, "currency": "USD", "available": False}
        if analytics.has_admin_key():
            cost_data = analytics.get_cached_cost(30)
            if cost_data is not None:
                real_cost = {
                    "total": float(cost_data.get("total", 0.0)),
                    "currency": cost_data.get("currency", "USD"),
                    "days": cost_data.get("days", 30),
                    "days_with_data": cost_data.get("days_with_data", 0),
                    "available": True,
                }
            else:
                real_cost["pending"] = True  # cache not yet populate edilmedi
        try:
            team = state_store.read("team_registry", {"agents": []})
        except Exception:
            team = {"agents": []}
        try:
            tasks = state_store.read("tasks", {"tasks": []})
        except Exception:
            tasks = {"tasks": []}
        briefs_dir = PROJECT_ROOT / "state" / "briefs"
        briefs = []
        if briefs_dir.exists():
            for p in sorted(briefs_dir.glob("*.md")):
                try:
                    briefs.append({
                        "role": p.stem,
                        "size": p.stat().st_size,
                        "mtime": datetime.utcfromtimestamp(
                            p.stat().st_mtime).isoformat(timespec="seconds") + "Z",
                    })
                except OSError:
                    pass
        active_count: dict[str, int] = {}
        for a in team.get("agents", []):
            if a.get("status") == "active":
                active_count[a["role"]] = active_count.get(a["role"], 0) + 1
        return web.json_response({
            "budget": snap, "real_cost": real_cost,
            "team": active_count,
            "tasks": tasks.get("tasks", []), "briefs": briefs,
            "agent_state": self._agent_state,
            "history": list(self._history),
        })

    async def _handle_analytics(self, request: web.Request) -> web.Response:
        """Anthropic Admin API — cost + token usage."""
        from . import analytics
        try:
            days = max(1, min(90, int(request.query.get("days", "30"))))
        except ValueError:
            days = 30
        if request.query.get("force") == "1":
            analytics.clear_cache()
        data = await analytics.fetch_combined_async(days)
        return web.json_response(data)

    async def _handle_workspaces(self, request: web.Request) -> web.Response:
        """Admin key'in gordugu workspaces — debug."""
        from . import analytics
        if not analytics.has_admin_key():
            return web.json_response({
                "error": "ANTHROPIC_ADMIN_API_KEY none",
                "workspaces": [], "count": 0,
            })
        import asyncio
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, analytics.fetch_workspaces)
        return web.json_response(data)

    async def _handle_chat(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "json required"}, status=400)
        msg = (data.get("message") or "").strip()
        target = (data.get("target") or "ceo").strip().lower()
        if target not in ("ceo", "cfo"):
            target = "ceo"
        if not msg:
            return web.json_response({"ok": False, "error": "mesaj empty"}, status=400)
        await self.chat_queue.put({"message": msg, "target": target})
        log.info("Browser -> %s: %s", target.upper(), msg[:80])
        return web.json_response({"ok": True, "queued": True, "target": target})

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._clients.add(ws)
        try:
            for ev in list(self._history)[-200:]:
                await ws.send_str(json.dumps(ev))
        except Exception:
            pass
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    log.warning("WS error: %s", ws.exception())
        except (asyncio.CancelledError, ConnectionResetError, ConnectionError):
            # Shutdown (Ctrl+C) or client disconnect — sessizce kapan
            pass
        except Exception as e:
            log.debug("WS handler kapanis: %s", e)
        finally:
            self._clients.discard(ws)
            try:
                if not ws.closed:
                    await ws.close(code=1001, message=b"server shutdown")
            except Exception:
                pass
        return ws

    def emit(self, event: dict) -> None:
        kind = event.get("kind")
        role = event.get("role", "")
        ts = event.get("ts") or time.time()
        if kind == "enter":
            st = self._agent_state[role]
            st["status"] = "working"
            st["caller"] = event.get("caller")
            st["last_at"] = ts
        elif kind == "exit":
            st = self._agent_state[role]
            st["status"] = "idle"
            st["last_at"] = ts
        elif kind == "text":
            st = self._agent_state[role]
            st["last_text"] = (event.get("text") or "")[:200]
            st["last_at"] = ts
        elif kind == "tool":
            st = self._agent_state[role]
            st["last_tool"] = event.get("tool", "")
            st["last_at"] = ts
        self._history.append(event)
        if not self._loop or not self._clients:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(event), self._loop)
        except Exception:
            pass

    async def _broadcast(self, event: dict) -> None:
        if not self._clients:
            return
        msg = json.dumps(event)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_str(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)


_server: DashboardServer | None = None


def get_server() -> DashboardServer | None:
    return _server


def set_server(server: DashboardServer | None) -> None:
    global _server
    _server = server