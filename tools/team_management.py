"""Team yonetimi tool'lari."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from claude_agent_sdk import tool

from . import config_loader, state_store
from .budget import compute_snapshot


def _empty_registry() -> dict[str, Any]:
    return {"agents": [], "requests": []}


def _sync_team_yaml_count(role: str, delta: int) -> str:
    """Spawn aftersi team.yaml'in count: valueini delta until arttirir.

    Error olursa registry yazildi, sessizce yumak — sync optional.
    """
    try:
        from . import config_io
        current = int(
            config_loader.team().get("roles", {}).get(role, {}).get("count", 0)
        )
        new_count = max(1, current + delta)
        old, new = config_io.set_team_count(role, new_count)
        if old == new:
            return f"team.yaml count already {new}"
        return f"team.yaml senkronize: {role}.count {old} -> {new}"
    except Exception as e:
        return f"team.yaml sync failed (registry yazildi): {e}"


def ensure_baseline_registry() -> dict[str, Any]:
    """Registry'yi team.yaml ile **additive** sync eder.

    - Empty registry: all rolesi seed olarak add.
    - Existing registry: team.yaml'da olup registry'de missing rolesi add
      (existing agent'lara dokunma — role's active sayisi count'tan azsa fark until add).
    - team.yaml'dan bir rol silindiyse registry'deki agent'lar BIRAKILIR (silmek riskli;
      user bilincli decision versin). Only audit'e info.
    """
    data = state_store.read("team_registry", _empty_registry())
    cfg = config_loader.team()
    roles = cfg.get("roles", {})
    existing_agents = data.setdefault("agents", [])

    # Active rol -> count
    active_by_role: dict[str, int] = {}
    for a in existing_agents:
        if a.get("status") == "active":
            r = a["role"]
            active_by_role[r] = active_by_role.get(r, 0) + 1

    added: list[str] = []
    for role, conf in roles.items():
        target = int(conf.get("count", 1))
        current = active_by_role.get(role, 0)
        if current >= target:
            continue
        # Missing agent until yeni seed add
        for i in range(target - current):
            agent = {
                "id": f"{role}-{current + i + 1}-{uuid.uuid4().hex[:6]}",
                "role": role,
                "model": conf.get("model"),
                "profile": conf.get("profile", "").strip(),
                "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "status": "active",
                "seed": True,
                "auto_synced": current > 0,  # existing registry'ye afterdan addnmis mi
            }
            existing_agents.append(agent)
            added.append(role)

    data["requests"] = data.get("requests", [])
    if added:
        # Audit: which roles addndi
        from collections import Counter
        c = Counter(added)
        notes = ", ".join(f"{r} x{n}" for r, n in c.items())
        data.setdefault("sync_log", []).append({
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "added": dict(c),
            "note": f"Auto-sync: {notes}",
        })
    state_store.write("team_registry", data)
    return data


@tool(
    "list_team",
    "Active team listni dondurur.",
    {},
)
async def list_team(args: dict) -> dict:
    data = state_store.read("team_registry", _empty_registry())
    agents = data.get("agents", [])
    by_role: dict[str, int] = {}
    for a in agents:
        if a.get("status") == "active":
            by_role[a["role"]] = by_role.get(a["role"], 0) + 1
    lines = ["Active team:"]
    for role, n in sorted(by_role.items()):
        lines.append(f"  - {role:20s} x {n}")
    lines.append("")
    lines.append(f"Total active agent: {sum(by_role.values())}")
    pending = [r for r in data.get("requests", []) if r.get("status") == "pending"]
    if pending:
        lines.append("")
        lines.append(f"Baddyen agent requests: {len(pending)}")
        for r in pending:
            lines.append(f"  - {r['id']}: {r['role']} x{r['count']}  ({r['urgency']})")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "request_new_agent",
    "PM'den CEO'ya yeni agent talebi.",
    {"role": str, "count": int, "reason": str, "expected_impact": str, "urgency": str},
)
async def request_new_agent(args: dict) -> dict:
    role = args.get("role", "").strip()
    count = int(args.get("count", 1))
    reason = args.get("reason", "").strip()
    impact = args.get("expected_impact", "").strip()
    urgency = args.get("urgency", "medium").strip().lower()
    if not role or count < 1:
        return {"content": [{"type": "text", "text": "role and count mandatory"}], "is_error": True}

    req = {
        "id": "req-" + uuid.uuid4().hex[:6],
        "role": role,
        "count": count,
        "reason": reason,
        "expected_impact": impact,
        "urgency": urgency,
        "status": "pending",
        "requested_by": "project_manager",
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

    def mutate(data):
        data.setdefault("requests", []).append(req)
        return data

    state_store.update("team_registry", mutate, _empty_registry())
    msg = (
        f"Request createuldu: {req['id']}\n"
        f"  role: {role} x {count}\n"
        f"  urgency: {urgency}\n"
        f"  reason: {reason}\n"
        f"  expected impact: {impact}\n"
        "CEO this talebi valuelendirmeli."
    )
    return {"content": [{"type": "text", "text": msg}]}


@tool(
    "evaluate_new_agent_request",
    "CEO'nun yeni agent talebini valuelendirme tool'u.",
    {"request_id": str},
)
async def evaluate_new_agent_request(args: dict) -> dict:
    rid = args.get("request_id", "").strip()
    data = state_store.read("team_registry", _empty_registry())
    req = next((r for r in data.get("requests", []) if r["id"] == rid), None)
    if not req:
        return {"content": [{"type": "text", "text": f"Request bulunamadi: {rid}"}], "is_error": True}

    snap = compute_snapshot()
    monthly_cost = float(snap["agent_costs_monthly"].get(req["role"], 0)) * int(req["count"])
    new_month_spend = snap["month_spend"] + monthly_cost
    new_ratio = (new_month_spend / snap["monthly_cap"]) if snap["monthly_cap"] else 0.0

    urgency = req.get("urgency", "medium")
    urgency_score = {"low": 1, "medium": 2, "high": 3}.get(urgency, 2)
    budget_risk = "low" if new_ratio < 0.75 else "medium" if new_ratio < 0.95 else "high"

    reasoning = [
        f"Request: {req['role']} x {req['count']}  (urgency={urgency})",
        f"Single agent cost ~ {snap['agent_costs_monthly'].get(req['role'], 0):.0f} {snap['currency']}/ay",
        f"Total ek cost: {monthly_cost:.0f} {snap['currency']}/ay",
        f"This ay budget projeksiyon: {new_month_spend:.0f} / {snap['monthly_cap']:.0f}  ({new_ratio*100:.1f}%)",
        f"Budget risk: {budget_risk}",
        f"Urgency skoru: {urgency_score}/3",
        f"Gerekce: {req.get('reason','')}",
        f"Baddnen etki: {req.get('expected_impact','')}",
    ]
    return {"content": [{"type": "text", "text": "\n".join(reasoning)}]}


@tool(
    "spawn_agent",
    "PM talebi + user approvali aftersi agent addr. request_id mandatory.",
    {"request_id": str, "approval_note": str},
)
async def spawn_agent(args: dict) -> dict:
    rid = args.get("request_id", "").strip()
    note = args.get("approval_note", "").strip()
    cfg = config_loader.team()

    added: list[dict] = []

    def mutate(data):
        req = next((r for r in data.get("requests", []) if r["id"] == rid), None)
        if not req:
            raise ValueError(f"Request bulunamadi: {rid}")
        if req["status"] != "pending":
            raise ValueError(f"Request already {req['status']}")
        role_cfg = cfg.get("roles", {}).get(req["role"], {})
        for i in range(req["count"]):
            agent_id = f"{req['role']}-{uuid.uuid4().hex[:6]}"
            data.setdefault("agents", []).append({
                "id": agent_id,
                "role": req["role"],
                "model": role_cfg.get("model"),
                "profile": role_cfg.get("profile", "").strip(),
                "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "status": "active",
                "seed": False,
                "spawned_from_request": rid,
                "approval_note": note,
            })
            added.append({"id": agent_id, "role": req["role"]})
        req["status"] = "approved"
        req["approved_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        return data

    try:
        state_store.update("team_registry", mutate, _empty_registry())
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}

    sync_note = ""
    if added:
        sync_note = "\n" + _sync_team_yaml_count(added[0]["role"], len(added))

    summary = "\n".join([f"  + {a['role']}  (id={a['id']})" for a in added])
    return {"content": [{"type": "text",
                         "text": f"Yeni agents addndi:\n{summary}{sync_note}"}]}


@tool(
    "direct_spawn_agent",
    (
        "User directly request ettiginde CEO'nun kullandigi agent addme tool'u. "
        "PM talebi and user approval ZINCIRINI ATLAR. role, count, user_request_summary, "
        "ceo_opinion mandatory. single_decision_cap or hard block asan requests rejects."
    ),
    {"role": str, "count": int, "user_request_summary": str, "ceo_opinion": str},
)
async def direct_spawn_agent(args: dict) -> dict:
    role = args.get("role", "").strip()
    count = int(args.get("count", 1))
    user_req = args.get("user_request_summary", "").strip()
    opinion = args.get("ceo_opinion", "").strip()

    if not role or count < 1:
        return {"content": [{"type": "text", "text": "role and count mandatory"}], "is_error": True}
    if not user_req:
        return {"content": [{"type": "text",
                             "text": "user_request_summary mandatory"}], "is_error": True}
    if not opinion:
        return {"content": [{"type": "text",
                             "text": "ceo_opinion mandatory"}], "is_error": True}

    cfg = config_loader.team()
    if role not in cfg.get("roles", {}):
        return {"content": [{"type": "text",
                             "text": f"Bilinmeyen rol: {role}"}], "is_error": True}

    snap = compute_snapshot()
    role_cost = float(snap["agent_costs_monthly"].get(role, 0)) * count
    single_cap = float(snap.get("single_decision_cap", 0))
    if single_cap and role_cost > single_cap:
        return {"content": [{"type": "text",
                             "text": (f"Red: ek cost {role_cost:.0f} USD > "
                                      f"single_decision_cap ({single_cap:.0f}). "
                                      "budget.request_user_approval yoluna late.")}],
                "is_error": True}
    projected = snap["month_spend"] + role_cost
    if snap["monthly_cap"] and (projected / snap["monthly_cap"]) >= snap["hard_block_threshold"]:
        return {"content": [{"type": "text",
                             "text": (f"Red: budget hard block. Projeksiyon "
                                      f"{projected:.0f}/{snap['monthly_cap']:.0f}.")}],
                "is_error": True}

    role_cfg = cfg["roles"][role]
    rid = "direct-" + uuid.uuid4().hex[:6]
    added: list[dict] = []

    def mutate(data):
        data.setdefault("requests", []).append({
            "id": rid,
            "role": role,
            "count": count,
            "reason": user_req,
            "expected_impact": "(user direkt talebi)",
            "urgency": "user-direct",
            "status": "approved",
            "requested_by": "user",
            "ceo_opinion": opinion,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "approved_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        })
        for _ in range(count):
            agent_id = f"{role}-{uuid.uuid4().hex[:6]}"
            data.setdefault("agents", []).append({
                "id": agent_id,
                "role": role,
                "model": role_cfg.get("model"),
                "profile": role_cfg.get("profile", "").strip(),
                "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "status": "active",
                "seed": False,
                "spawned_from_request": rid,
                "user_initiated": True,
                "ceo_opinion": opinion,
            })
            added.append({"id": agent_id, "role": role})
        return data

    state_store.update("team_registry", mutate, _empty_registry())

    sync_note = _sync_team_yaml_count(role, count)

    summary = "\n".join([f"  + {a['role']}  (id={a['id']})" for a in added])
    return {"content": [{"type": "text",
                         "text": (f"User direkt talebi ile addndi "
                                  f"(request_id={rid}):\n{summary}\n{sync_note}\n"
                                  f"CEO opinion kaydedildi: {opinion[:200]}")}]}


TEAM_TOOLS = [
    list_team,
    request_new_agent,
    evaluate_new_agent_request,
    spawn_agent,
    direct_spawn_agent,
]
