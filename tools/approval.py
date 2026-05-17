"""User approval kopsusu.

CEO agenti `budget.request_user_approval` ile proposal senddiginde,
orchestrator'in forden bir asyncio Queue araciligiyla user's
terminaline mesaj dusurur, approvali baddr, responsei donduruluyor.

Design note: this modul tool sarmalayicisi DEGILDIR — `budget.py` altindaki
`request_user_approval` tool'u forden calllir.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ApprovalRequest:
    """Bir approval talebi — CEO -> user."""
    id: str
    title: str
    summary: str
    details: dict
    response: Optional[str] = None
    event: asyncio.Event = field(default_factory=asyncio.Event)


class ApprovalBroker:
    """Single bir broker instance'i global olarak orchestrator'de tutulur.

    Tool'lar `submit(...)` calls → queue'ya connects → orchestrator REPL'i
    userdan response receives → `resolve(id, text)` calls.
    """

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._notify = asyncio.Queue()

    async def submit(self, title: str, summary: str, details: dict | None = None) -> str:
        req = ApprovalRequest(
            id=uuid.uuid4().hex[:8],
            title=title,
            summary=summary,
            details=details or {},
        )
        self._pending[req.id] = req
        await self._notify.put(req)
        await req.event.wait()
        self._pending.pop(req.id, None)
        return req.response or "(no response)"

    async def next_pending(self) -> ApprovalRequest:
        return await self._notify.get()

    def resolve(self, req_id: str, response: str) -> bool:
        req = self._pending.get(req_id)
        if not req:
            return False
        req.response = response
        req.event.set()
        return True

    def has_pending(self) -> bool:
        return bool(self._pending)


# Surec boyunca single bir broker
_broker: ApprovalBroker | None = None


def broker() -> ApprovalBroker:
    global _broker
    if _broker is None:
        _broker = ApprovalBroker()
    return _broker
