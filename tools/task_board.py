"""Task board tool'lari + role-based status guard + Tech Lead review gate."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from claude_agent_sdk import tool

from . import state_store


def _empty_board() -> dict[str, Any]:
    return {"tasks": []}


def _board() -> dict[str, Any]:
    return state_store.read("tasks", _empty_board())


# Worker'larin (kod yazan agent'larin) yapabilecegi status degisikliks.
# done/review_passed YOK — Tech Lead gate'i devrede.
WORKER_ALLOWED_STATUS = {
    "open", "in_progress", "blocked", "pending_review", "needs_changes",
}

# Tech Lead'in yapabilecegi status'lar — code review verdict'leri
TECH_LEAD_REVIEW_STATUS = {"review_passed", "needs_changes", "rejected"}

# All legal status'lar
ALL_STATUS = {
    "open", "in_progress", "blocked", "pending_review",
    "review_passed", "needs_changes", "rejected", "done", "cancelled",
}

# Which rol "done" yapabilir
LEADERSHIP_DONE_ROLES = {"ceo", "project_manager", "business_analyst", "tech_lead"}

# Worker rolesi (kod yazan / artifact ureten)
WORKER_ROLES = {
    "android_dev", "ios_dev", "frontend_dev", "backend_dev",
    "uiux_dev", "mobile_tester", "tester",
    "marketing_sales_specialist", "devops_engineer",
}


@tool(
    "create",
    ("Yeni task ac. title, description, acceptance_criteria, assigned_role, priority, parent_id."),
    {"title": str, "description": str, "acceptance_criteria": str,
     "assigned_role": str, "priority": str, "parent_id": str},
)
async def create(args: dict) -> dict:
    t = {
        "id": "task-" + uuid.uuid4().hex[:8],
        "title": args.get("title", "").strip(),
        "description": args.get("description", "").strip(),
        "acceptance_criteria": args.get("acceptance_criteria", "").strip(),
        "assigned_role": args.get("assigned_role", "").strip(),
        "priority": args.get("priority", "medium").strip().lower(),
        "parent_id": args.get("parent_id", "").strip(),
        "status": "open",
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "history": [],
        "artifacts": [],
        "review_history": [],
    }
    if not t["title"]:
        return {"content": [{"type": "text", "text": "title mandatory"}], "is_error": True}

    def mutate(data):
        data.setdefault("tasks", []).append(t)
        return data

    state_store.update("tasks", mutate, _empty_board())
    return {"content": [{"type": "text", "text": f"Task createuldu: {t['id']} — {t['title']}"}]}


@tool(
    "list",
    "All tasklari or filtrelenmiss dondurur.",
    {"filter_role": str, "filter_status": str},
)
async def list_tasks(args: dict) -> dict:
    role = args.get("filter_role", "").strip()
    status = args.get("filter_status", "").strip()
    tasks = _board().get("tasks", [])
    out = [t for t in tasks
           if (not role or t.get("assigned_role") == role)
           and (not status or t.get("status") == status)]
    if not out:
        return {"content": [{"type": "text", "text": "(eslesen task none)"}]}
    lines = []
    for t in out:
        lines.append(f"{t['id']}  [{t['status']:14s}]  [{t['priority']:7s}]  "
                     f"{t.get('assigned_role','-'):20s}  {t['title']}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "list_mine",
    "Belirli bir role atanmis open tasklari listr.",
    {"role": str},
)
async def list_mine(args: dict) -> dict:
    role = args.get("role", "").strip()
    if not role:
        return {"content": [{"type": "text", "text": "role mandatory"}], "is_error": True}
    tasks = [t for t in _board().get("tasks", [])
             if t.get("assigned_role") == role
             and t.get("status") not in ("done", "cancelled")]
    if not tasks:
        return {"content": [{"type": "text", "text": f"{role} for open task none"}]}
    lines = []
    for t in tasks:
        lines.append(f"{t['id']}  [{t['status']}]  [{t['priority']}]  {t['title']}")
        if t.get("acceptance_criteria"):
            lines.append(f"  AC: {t['acceptance_criteria'][:300]}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "update",
    (
        "Task'i currentle. ROLE-BASED STATUS GUARD active: "
        "Worker'lar (writes_code: android_dev/ios_dev/frontend_dev/backend_dev/devops_engineer/...) "
        "ASLA 'done' or 'review_passed' cannot do — only pending_review yapabilirler. "
        "Tech Lead approvali (tasks.review) required. "
        "Leadership (CEO/PM/BA/TL) all status'lari yapabilir. "
        "as_role parametresi kim that it is belirtir; default olarak guard'you acceptance is done "
        "(orchestrator-side caller bilgisi none)."
    ),
    {"task_id": str, "status": str, "note": str, "as_role": str},
)
async def update_task(args: dict) -> dict:
    tid = args.get("task_id", "").strip()
    new_status = args.get("status", "").strip()
    note = args.get("note", "").strip()
    as_role = args.get("as_role", "").strip()
    if not tid:
        return {"content": [{"type": "text", "text": "task_id mandatory"}], "is_error": True}
    if new_status and new_status not in ALL_STATUS:
        return {"content": [{"type": "text",
                              "text": f"Gecersiz status: {new_status}. Permission verilen: {sorted(ALL_STATUS)}"}],
                "is_error": True}

    # Role-based guard
    if as_role in WORKER_ROLES and new_status in {"done", "review_passed"}:
        return {"content": [{"type": "text",
                              "text": (f"REDDEDILDI: {as_role} kendi basina '{new_status}' cannot do. "
                                       "Tech Lead approvali required. Before status'u 'pending_review' do.")}],
                "is_error": True}

    updated = {"found": False}

    def mutate(data):
        for t in data.get("tasks", []):
            if t["id"] == tid:
                updated["found"] = True
                if new_status:
                    t["status"] = new_status
                t.setdefault("history", []).append({
                    "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "status": new_status or t.get("status"),
                    "note": note,
                    "as_role": as_role or "(unknown)",
                })
        return data

    state_store.update("tasks", mutate, _empty_board())
    if not updated["found"]:
        return {"content": [{"type": "text", "text": f"Task bulunamadi: {tid}"}], "is_error": True}
    return {"content": [{"type": "text",
                         "text": f"Task currentlendi: {tid} -> {new_status or '(status degismedi)'}"}]}


@tool(
    "assign",
    "Task'i bir role ata.",
    {"task_id": str, "role": str},
)
async def assign_task(args: dict) -> dict:
    tid = args.get("task_id", "").strip()
    role = args.get("role", "").strip()
    if not tid or not role:
        return {"content": [{"type": "text", "text": "task_id and role mandatory"}], "is_error": True}
    found = {"ok": False}

    def mutate(data):
        for t in data.get("tasks", []):
            if t["id"] == tid:
                t["assigned_role"] = role
                t.setdefault("history", []).append({
                    "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "note": f"assigned to {role}",
                })
                found["ok"] = True
        return data

    state_store.update("tasks", mutate, _empty_board())
    if not found["ok"]:
        return {"content": [{"type": "text", "text": f"Task bulunamadi: {tid}"}], "is_error": True}
    return {"content": [{"type": "text", "text": f"Task {tid} -> {role}"}]}


@tool(
    "review",
    (
        "TECH LEAD ONLY: bir task'i code review aftersi approvalla, reddet or change request et. "
        "verdict: 'review_passed' (kod acceptance, BA done'a tasiyabilir) | "
        "'needs_changes' (worker'a back goes, tekrar code) | "
        "'rejected' (mimari/yaklasim errorsi, BA again plmeinstantgali). "
        "review_note mandatory — neden approvalladin/reddetin gerekce. "
        "review_artifact_path optional — detailed review feedback of the file yolu "
        "(orn: 'artifacts/tech_lead/review-task-abc.md')."
    ),
    {"task_id": str, "verdict": str, "review_note": str, "review_artifact_path": str},
)
async def review(args: dict) -> dict:
    tid = args.get("task_id", "").strip()
    verdict = args.get("verdict", "").strip()
    note = args.get("review_note", "").strip()
    artifact_path = args.get("review_artifact_path", "").strip()
    if not tid:
        return {"content": [{"type": "text", "text": "task_id mandatory"}], "is_error": True}
    if verdict not in TECH_LEAD_REVIEW_STATUS:
        return {"content": [{"type": "text",
                              "text": f"verdict mutlaka: {sorted(TECH_LEAD_REVIEW_STATUS)}"}],
                "is_error": True}
    if not note:
        return {"content": [{"type": "text",
                              "text": "review_note mandatory — gerekceli approval/red"}],
                "is_error": True}

    found = {"ok": False, "old_status": None}

    def mutate(data):
        for t in data.get("tasks", []):
            if t["id"] == tid:
                found["ok"] = True
                found["old_status"] = t.get("status")
                t["status"] = verdict
                t.setdefault("review_history", []).append({
                    "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "verdict": verdict,
                    "note": note,
                    "artifact": artifact_path,
                    "by": "tech_lead",
                })
                t.setdefault("history", []).append({
                    "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "status": verdict,
                    "note": f"[TECH_LEAD REVIEW] {note}",
                    "as_role": "tech_lead",
                })
        return data

    state_store.update("tasks", mutate, _empty_board())
    if not found["ok"]:
        return {"content": [{"type": "text", "text": f"Task bulunamadi: {tid}"}], "is_error": True}

    msg = (f"Tech Lead review: {tid} {found['old_status']} -> {verdict}\n"
           f"Not: {note[:200]}")
    if artifact_path:
        msg += f"\nFeedback filesi: {artifact_path}"
    return {"content": [{"type": "text", "text": msg}]}


TASK_TOOLS = [create, list_tasks, list_mine, update_task, assign_task, review]
