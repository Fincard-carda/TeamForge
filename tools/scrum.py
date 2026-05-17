"""Scrum framework tool'lari.

TeamForge'de Tech Lead = ScrumMaster, BA = Product Owner, dev/test workers = Dev Team.
1-weekly sprintler. Ceremonies:
  - Sprint Planning (sprint basi)
  - Daily Standup (her day, record optional)
  - Backlog Grooming / Refinement (sprint ortasi, ~mid-week)
  - Sprint Review (sprint end, demo)
  - Retrospective (her 2 haftada bir = 2 sprint'te bir)

Retro action item'lari TL tarafindan CEO inbox'a (state/ceo_inbox.json) forwardr.
CEO these okuyup userya reportr.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from claude_agent_sdk import tool

from . import state_store


CEREMONY_KINDS = {"planning", "daily", "grooming", "review", "retrospective"}


def _empty_sprints() -> dict[str, Any]:
    return {"sprints": []}


def _empty_ceremonies() -> dict[str, Any]:
    return {"entries": []}


def _empty_inbox() -> dict[str, Any]:
    return {"messages": []}


# ============================================================
# Sprint yonetimi
# ============================================================

@tool(
    "start_sprint",
    (
        "Yeni 1-weekly sprint startir. ScrumMaster (Tech Lead) calls. "
        "name: sprint adi (example 'Sprint 2026-W17'). "
        "goals: sprint targets (many satirli ok). "
        "duration_days: default 7. "
        "planned_task_ids: virgulle ayrilmis task id'leri (planning'de selecteden)."
    ),
    {"name": str, "goals": str, "duration_days": int, "planned_task_ids": str},
)
async def start_sprint(args: dict) -> dict:
    name = args.get("name", "").strip()
    goals = args.get("goals", "").strip()
    days = int(args.get("duration_days", 7))
    planned = [t.strip() for t in args.get("planned_task_ids", "").split(",") if t.strip()]
    if not name or not goals:
        return {"content": [{"type": "text", "text": "name and goals mandatory"}], "is_error": True}

    now = datetime.utcnow()
    sprint = {
        "id": "sprint-" + uuid.uuid4().hex[:6],
        "name": name,
        "goals": goals,
        "duration_days": days,
        "started_at": now.isoformat(timespec="seconds") + "Z",
        "ends_at": (now + timedelta(days=days)).isoformat(timespec="seconds") + "Z",
        "status": "active",
        "planned_task_ids": planned,
        "summary": "",
        "closed_at": None,
    }

    def mutate(data):
        # Other active sprints close
        for s in data.setdefault("sprints", []):
            if s.get("status") == "active":
                s["status"] = "stale"
        data["sprints"].append(sprint)
        return data

    state_store.update("sprints", mutate, _empty_sprints())
    return {"content": [{"type": "text",
                         "text": f"Sprint startildi: {sprint['id']} — {name}\n"
                                  f"Hedefler: {goals[:200]}\n"
                                  f"Bitis: {sprint['ends_at']}\n"
                                  f"Planlanan task: {len(planned)}"}]}


@tool(
    "current_sprint",
    "Active sprint bilgisi.",
    {},
)
async def current_sprint(args: dict) -> dict:
    data = state_store.read("sprints", _empty_sprints())
    active = [s for s in data.get("sprints", []) if s.get("status") == "active"]
    if not active:
        return {"content": [{"type": "text", "text": "(active sprint none)"}]}
    s = active[-1]
    msg = (f"{s['id']} — {s['name']}\n"
           f"Status: {s['status']}\n"
           f"Initial: {s['started_at']}\n"
           f"Bitis: {s['ends_at']}\n"
           f"Sure: {s['duration_days']} day\n"
           f"Hedefler:\n{s['goals']}\n"
           f"Planlanan task ({len(s.get('planned_task_ids', []))}): {', '.join(s.get('planned_task_ids', []))}")
    return {"content": [{"type": "text", "text": msg}]}


@tool(
    "list_sprints",
    "All sprint'leri (active + closed) listr.",
    {"limit": int},
)
async def list_sprints(args: dict) -> dict:
    limit = int(args.get("limit", 20))
    data = state_store.read("sprints", _empty_sprints())
    sprints = data.get("sprints", [])[-limit:]
    if not sprints:
        return {"content": [{"type": "text", "text": "(sprint none)"}]}
    lines = [f"  {s['id']:18s}  [{s['status']:8s}]  {s['name']}  ({s['started_at'][:10]} -> {s['ends_at'][:10]})"
             for s in sprints]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "close_sprint",
    "Sprint'i close. summary kisa summary (what basarildi/kacirildi).",
    {"sprint_id": str, "summary": str},
)
async def close_sprint(args: dict) -> dict:
    sid = args.get("sprint_id", "").strip()
    summary = args.get("summary", "").strip()
    if not sid or not summary:
        return {"content": [{"type": "text", "text": "sprint_id and summary mandatory"}], "is_error": True}

    found = {"ok": False}

    def mutate(data):
        for s in data.get("sprints", []):
            if s["id"] == sid:
                s["status"] = "closed"
                s["closed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                s["summary"] = summary
                found["ok"] = True
        return data

    state_store.update("sprints", mutate, _empty_sprints())
    if not found["ok"]:
        return {"content": [{"type": "text", "text": f"Sprint bulunamadi: {sid}"}], "is_error": True}
    return {"content": [{"type": "text", "text": f"Sprint closeildi: {sid}"}]}


# ============================================================
# Ceremony (toplanti) recordlari
# ============================================================

@tool(
    "log_ceremony",
    (
        "Toplanti notu save. kind: planning | daily | grooming | review | retrospective. "
        "sprint_id mandatory. attendees virgulle ayrilmis rol list. "
        "notes: ana text. action_items: madde madde aksiyonlar (many satirli)."
    ),
    {"sprint_id": str, "kind": str, "attendees": str, "notes": str, "action_items": str},
)
async def log_ceremony(args: dict) -> dict:
    sid = args.get("sprint_id", "").strip()
    kind = args.get("kind", "").strip().lower()
    attendees = args.get("attendees", "").strip()
    notes = args.get("notes", "").strip()
    actions = args.get("action_items", "").strip()
    if not sid or kind not in CEREMONY_KINDS:
        return {"content": [{"type": "text",
                              "text": f"sprint_id and valid kind ({sorted(CEREMONY_KINDS)}) mandatory"}],
                "is_error": True}
    if not notes:
        return {"content": [{"type": "text", "text": "notes mandatory"}], "is_error": True}

    entry = {
        "id": "cer-" + uuid.uuid4().hex[:6],
        "sprint_id": sid,
        "kind": kind,
        "attendees": [a.strip() for a in attendees.split(",") if a.strip()],
        "notes": notes,
        "action_items": actions,
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

    def mutate(data):
        data.setdefault("entries", []).append(entry)
        return data

    state_store.update("ceremonies", mutate, _empty_ceremonies())
    return {"content": [{"type": "text",
                         "text": f"Ceremony kaydi: {entry['id']} — {kind} (sprint {sid})\n"
                                  f"Aksiyon sayisi: {len([a for a in actions.split(chr(10)) if a.strip()])}"}]}


@tool(
    "list_ceremonies",
    "Toplanti notlari (filtreli). sprint_id and kind optional. limit: how many record (default 10).",
    {"sprint_id": str, "kind": str, "limit": int},
)
async def list_ceremonies(args: dict) -> dict:
    sid = args.get("sprint_id", "").strip()
    kind = args.get("kind", "").strip().lower()
    limit = int(args.get("limit", 10))
    data = state_store.read("ceremonies", _empty_ceremonies())
    items = data.get("entries", [])
    if sid:
        items = [i for i in items if i.get("sprint_id") == sid]
    if kind:
        items = [i for i in items if i.get("kind") == kind]
    items = items[-limit:]
    if not items:
        return {"content": [{"type": "text", "text": "(eslesen ceremony none)"}]}
    lines = []
    for c in items:
        lines.append(f"--- {c['id']}  {c['kind']:15s}  sprint={c['sprint_id']}  ts={c['ts']}")
        lines.append(f"    Attendees: {', '.join(c.get('attendees', []))}")
        lines.append(f"    Notes: {c.get('notes', '')[:200]}")
        if c.get("action_items"):
            lines.append(f"    Actions: {c['action_items'][:200]}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# ============================================================
# CEO inbox — TL retro report
# ============================================================

@tool(
    "report_to_ceo",
    (
        "TL'den CEO'ya report (retro action item'lari, critical eskalasyon). "
        "subject kisa, body uzun. priority: low|medium|high. "
        "action_items madde madde."
    ),
    {"subject": str, "body": str, "priority": str, "action_items": str},
)
async def report_to_ceo(args: dict) -> dict:
    subject = args.get("subject", "").strip()
    body = args.get("body", "").strip()
    priority = args.get("priority", "medium").strip().lower()
    actions = args.get("action_items", "").strip()
    if priority not in ("low", "medium", "high"):
        priority = "medium"
    if not subject or not body:
        return {"content": [{"type": "text", "text": "subject and body mandatory"}], "is_error": True}

    msg = {
        "id": "inbox-" + uuid.uuid4().hex[:6],
        "from": "tech_lead",
        "subject": subject,
        "body": body,
        "action_items": actions,
        "priority": priority,
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "read": False,
    }

    def mutate(data):
        data.setdefault("messages", []).append(msg)
        return data

    state_store.update("ceo_inbox", mutate, _empty_inbox())

    # Dashboard'a notification — if exists
    try:
        from . import dashboard
        srv = dashboard.get_server()
        if srv is not None:
            import time as _time
            srv.emit({"kind": "ceo_inbox", "role": "tech_lead", "depth": 1,
                      "ts": _time.time(), "subject": subject, "priority": priority})
    except Exception:
        pass

    return {"content": [{"type": "text",
                         "text": f"CEO inbox'a yazildi: {msg['id']}\n"
                                  f"Topic: {subject}\nBeforelik: {priority}\n"
                                  f"CEO bir next turunda gorecek."}]}


@tool(
    "read_ceo_inbox",
    "CEO acilis turunda and heredigi an inbox'i okur. unread_only: only okunmamis (default true).",
    {"unread_only": str, "limit": int},
)
async def read_ceo_inbox(args: dict) -> dict:
    unread_only = (args.get("unread_only", "true") or "true").lower() not in ("false", "0", "no")
    limit = int(args.get("limit", 20))
    data = state_store.read("ceo_inbox", _empty_inbox())
    msgs = data.get("messages", [])
    if unread_only:
        msgs = [m for m in msgs if not m.get("read")]
    msgs = msgs[-limit:]
    if not msgs:
        return {"content": [{"type": "text", "text": "(inbox empty)"}]}
    lines = []
    for m in msgs:
        lines.append(f"=== {m['id']}  [{m['priority']}]  from={m.get('from','?')}  ts={m['ts']}  read={m.get('read', False)}")
        lines.append(f"Subject: {m['subject']}")
        lines.append(f"Body:\n{m['body']}")
        if m.get("action_items"):
            lines.append(f"Action items:\n{m['action_items']}")
        lines.append("")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "mark_inbox_read",
    "CEO bir inbox mesajini okundu flags. id mandatory.",
    {"item_id": str},
)
async def mark_inbox_read(args: dict) -> dict:
    iid = args.get("item_id", "").strip()
    if not iid:
        return {"content": [{"type": "text", "text": "item_id mandatory"}], "is_error": True}
    found = {"ok": False}

    def mutate(data):
        for m in data.get("messages", []):
            if m["id"] == iid:
                m["read"] = True
                m["read_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                found["ok"] = True
        return data

    state_store.update("ceo_inbox", mutate, _empty_inbox())
    if not found["ok"]:
        return {"content": [{"type": "text", "text": f"Inbox mesaji none: {iid}"}], "is_error": True}
    return {"content": [{"type": "text", "text": f"{iid} okundu isaretlendi"}]}


SCRUM_TOOLS = [
    start_sprint,        # 0
    current_sprint,      # 1
    list_sprints,        # 2
    close_sprint,        # 3
    log_ceremony,        # 4
    list_ceremonies,     # 5
    report_to_ceo,       # 6
    read_ceo_inbox,      # 7
    mark_inbox_read,     # 8
]
