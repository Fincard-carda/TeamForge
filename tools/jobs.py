"""Async job yonetimi — fire-and-forget delegation altstructurei + concurrency limit.

Davranisi:
- submit(role, prompt, caller, mode="async") -> job_id
- mode="async": background asyncio.Task, instant job_id drecommend
- mode="sync": tam resultu baddr (eski davranis)
- check_result(job_id, timeout=N): badd or statusu don
- read_inbox(role): role'un yeni resultlarini cekip "okundu" isaretle
- Auto-wake: top-level agent'in inbox'i fillednca external callback tetiklenir
- **CONCURRENCY LIMIT**: asyncio.Semaphore ile same anda max N agent spawn.
  Windows process limiti + paging file (WinError 1455) onlenir.
  Default 4, env var TEAMFORGE_MAX_CONCURRENT ile degistirilebilir.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from claude_agent_sdk import tool

from . import runtime, state_store

log = logging.getLogger("teamforge.jobs")

# Max concurrent agent subprocess — Windows'da claude.exe paralel sayisi limitli
_DEFAULT_MAX_CONCURRENT = int(os.environ.get("TEAMFORGE_MAX_CONCURRENT", "4"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gen_id() -> str:
    return "job-" + uuid.uuid4().hex[:8]


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict) and "content" in result:
        parts = []
        for c in result["content"]:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
        return "\n".join(parts) if parts else str(result)
    return str(result)


class JobManager:
    """All async delegation job'larini yoneten singleton-vari class."""

    _instance: Optional["JobManager"] = None

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._inbox: dict[str, list[str]] = defaultdict(list)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._wake_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
        # CONCURRENCY semaphore — Windows subprocess limitini tetiklemesin
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._max_concurrent = _DEFAULT_MAX_CONCURRENT
        self._restore()

    @classmethod
    def get(cls) -> "JobManager":
        if cls._instance is None:
            cls._instance = JobManager()
        return cls._instance

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        # Loop set olduktan next semaphore'i yarat (loop binding)
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)

    def set_wake_callback(self, cb: Callable[[str, str], Awaitable[None]]) -> None:
        self._wake_callback = cb

    def _persist(self) -> None:
        try:
            state_store.write("async_jobs", {
                "jobs": self._jobs, "inbox": dict(self._inbox),
            })
        except Exception as e:
            log.warning("Job persist error: %s", e)

    def _restore(self) -> None:
        data = state_store.read("async_jobs", {"jobs": {}, "inbox": {}})
        self._jobs = data.get("jobs", {}) or {}
        self._inbox = defaultdict(list, data.get("inbox", {}) or {})

    def submit(self, role: str, prompt: str, caller: str,
               mode: str = "async", subject: str = "") -> str:
        job_id = _gen_id()
        self._jobs[job_id] = {
            "id": job_id, "role": role, "caller": caller,
            "subject": subject or "(adsiz)",
            "status": "pending", "mode": mode,
            "prompt_preview": prompt[:200],
            "created_at": _now(),
        }
        self._persist()
        if mode == "async":
            if not self._loop:
                self._loop = asyncio.get_event_loop()
                if self._semaphore is None:
                    self._semaphore = asyncio.Semaphore(self._max_concurrent)
            task = self._loop.create_task(
                self._run_job(job_id, role, prompt, caller),
                name=f"job-{job_id}",
            )
            self._tasks[job_id] = task
        return job_id

    async def run_sync(self, role: str, prompt: str, caller: str,
                        subject: str = "") -> tuple[str, str]:
        job_id = self.submit(role, prompt, caller, mode="sync", subject=subject)
        text = await self._run_job(job_id, role, prompt, caller, push_inbox=False)
        return job_id, text

    async def _run_job(self, job_id: str, role: str, prompt: str,
                        caller: str, push_inbox: bool = True) -> str:
        """CONCURRENCY GUARD: semaphore ile same anda max N agent."""
        # Semaphore nonesa (test ortami) skip
        if self._semaphore is None:
            try:
                self._semaphore = asyncio.Semaphore(self._max_concurrent)
            except Exception:
                pass

        job = self._jobs.get(job_id)
        if job is None:
            return ""

        # Queue'da baddme state — yarisi spawn'da, yarisi waiting
        job["status"] = "queued"
        self._persist()

        async def _exec() -> str:
            job["status"] = "running"
            job["started_at"] = _now()
            self._persist()
            text = ""
            try:
                result = await runtime.run_agent(role, prompt, caller=caller)
                text = _as_text(result)
                job["status"] = "done"
                job["result"] = text[:8000]
                job["completed_at"] = _now()
            except Exception as e:
                log.exception("Job %s failed", job_id)
                job["status"] = "failed"
                job["error"] = str(e)
                job["completed_at"] = _now()
                text = f"[HATA] {e}"
            finally:
                self._persist()
                if push_inbox:
                    self._push_to_inbox(caller, job_id)
            return text

        if self._semaphore is not None:
            async with self._semaphore:
                return await _exec()
        return await _exec()

    def _push_to_inbox(self, caller: str, job_id: str) -> None:
        if caller not in self._inbox:
            self._inbox[caller] = []
        if job_id not in self._inbox[caller]:
            self._inbox[caller].append(job_id)
        self._persist()
        if self._wake_callback and caller in ("ceo", "cfo"):
            try:
                if self._loop:
                    self._loop.create_task(
                        self._wake_callback(caller, job_id),
                        name=f"wake-{caller}-{job_id}",
                    )
            except Exception as e:
                log.warning("Wake callback error: %s", e)

    def get_job(self, job_id: str) -> Optional[dict]:
        return self._jobs.get(job_id)

    def inbox_for(self, role: str, drain: bool = False) -> list[dict]:
        ids = list(self._inbox.get(role, []))
        items = [self._jobs[jid] for jid in ids if jid in self._jobs]
        if drain:
            self._inbox[role] = []
            self._persist()
        return items

    def list_pending(self) -> list[dict]:
        return [j for j in self._jobs.values()
                if j.get("status") in ("pending", "queued", "running")]

    async def wait_for(self, job_id: str, timeout: float = 30.0) -> Optional[dict]:
        task = self._tasks.get(job_id)
        if task and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            j = self._jobs.get(job_id)
            if j:
                j["status"] = "cancelled"
                j["completed_at"] = _now()
                self._persist()
            return True
        return False

    def concurrency_status(self) -> dict:
        """That anki concurrency state — debug for."""
        running = sum(1 for j in self._jobs.values() if j.get("status") == "running")
        queued = sum(1 for j in self._jobs.values() if j.get("status") == "queued")
        max_c = self._max_concurrent
        return {
            "max_concurrent": max_c,
            "running": running,
            "queued": queued,
            "available_slots": max_c - running,
        }


# =================== MCP TOOLS ===================

def _mgr() -> JobManager:
    return JobManager.get()


@tool(
    "check_result",
    ("Bir async job'in resultunu check et. timeout_seconds 0 = instant state, "
     "if missing o until saniye baddr."),
    {"job_id": str, "timeout_seconds": int},
)
async def check_result(args: dict) -> dict:
    job_id = args.get("job_id", "").strip()
    timeout = float(args.get("timeout_seconds") or 0)
    if not job_id:
        return {"content": [{"type": "text", "text": "job_id mandatory"}], "is_error": True}
    mgr = _mgr()
    if timeout > 0:
        job = await mgr.wait_for(job_id, timeout=timeout)
    else:
        job = mgr.get_job(job_id)
    if not job:
        return {"content": [{"type": "text", "text": f"Bilinmeyen job: {job_id}"}],
                "is_error": True}
    status = job.get("status")
    parts = [
        f"Job {job_id}",
        f"  rol: {job.get('role')}",
        f"  caller: {job.get('caller')}",
        f"  topic: {job.get('subject')}",
        f"  status: {status}",
        f"  initial: {job.get('created_at')}",
    ]
    if status == "done":
        parts.append(f"  bitis: {job.get('completed_at')}")
        parts.append("")
        parts.append("--- SONUC ---")
        parts.append(job.get("result", "(empty)"))
    elif status == "failed":
        parts.append(f"  error: {job.get('error')}")
    elif status in ("pending", "queued", "running"):
        parts.append(f"  ({status} — concurrency slot waiting olabilir)")
    return {"content": [{"type": "text", "text": "\n".join(parts)}]}


@tool(
    "read_inbox",
    ("Cagiran role's async result inbox'ini read. drain=true ise okunan resultlar "
     "inbox'tan dusurulur."),
    {"role": str, "drain": bool},
)
async def read_inbox(args: dict) -> dict:
    role = args.get("role", "").strip().lower()
    drain = bool(args.get("drain", True))
    if not role:
        return {"content": [{"type": "text", "text": "role mandatory"}], "is_error": True}
    mgr = _mgr()
    items = mgr.inbox_for(role, drain=drain)
    if not items:
        return {"content": [{"type": "text", "text": f"{role} inbox empty."}]}
    lines = [f"{role} inbox: {len(items)} result"]
    for j in items:
        lines.append("")
        lines.append(f"=== Job {j['id']}  [{j.get('status')}] ===")
        lines.append(f"  Yapildi: {j.get('role')} (callan: {j.get('caller')})")
        lines.append(f"  Topic: {j.get('subject')}")
        if j.get("status") == "done":
            res = (j.get("result") or "")[:1500]
            lines.append("  Result:")
            for line in res.splitlines():
                lines.append(f"    {line}")
        elif j.get("status") == "failed":
            lines.append(f"  HATA: {j.get('error')}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "list_pending",
    ("That an calismakta or queueta olan all async job'lari list. "
     "Concurrency state da gosterir."),
    {},
)
async def list_pending(args: dict) -> dict:
    mgr = _mgr()
    items = mgr.list_pending()
    status = mgr.concurrency_status()
    head = (f"Concurrency: {status['running']}/{status['max_concurrent']} slot filled, "
            f"{status['queued']} queueta, {status['available_slots']} empty")
    if not items:
        return {"content": [{"type": "text",
                              "text": f"{head}\n\nBaddyen job none."}]}
    lines = [head, "", f"Active job sayisi: {len(items)}"]
    for j in items:
        lines.append(f"  {j['id']}  [{j['status']:8s}]  "
                      f"{j.get('caller'):>12s} -> {j.get('role'):<12s}  "
                      f"{j.get('subject', '')[:60]}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "cancel_job",
    "Calismakta olan bir async job'i iptal et.",
    {"job_id": str},
)
async def cancel_job(args: dict) -> dict:
    job_id = args.get("job_id", "").strip()
    if not job_id:
        return {"content": [{"type": "text", "text": "job_id mandatory"}], "is_error": True}
    mgr = _mgr()
    ok = mgr.cancel(job_id)
    if ok:
        return {"content": [{"type": "text", "text": f"Job {job_id} iptal was done."}]}
    job = mgr.get_job(job_id)
    if job:
        return {"content": [{"type": "text",
                              "text": f"Job {job_id} already {job.get('status')} in state."}]}
    return {"content": [{"type": "text", "text": f"Bilinmeyen job: {job_id}"}],
            "is_error": True}


JOB_TOOLS = [check_result, read_inbox, list_pending, cancel_job]
