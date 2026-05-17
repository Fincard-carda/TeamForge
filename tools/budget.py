"""Budget tool'lari — CEO these kullanir.

Tool'lar:
  * get_report           — existing budget state
  * log_expense          — agent costini save (manuel or automatic)
  * request_user_approval — userya proposal sunar and baddr
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from claude_agent_sdk import tool

from . import config_loader, state_store
from .approval import broker


def _empty_ledger() -> dict[str, Any]:
    return {
        "entries": [],  # {ts, category, amount, note, role}
        "totals": {"all_time": 0.0, "month": 0.0},
        "month_key": datetime.utcnow().strftime("%Y-%m"),
    }


def _current_ledger() -> dict[str, Any]:
    data = state_store.read("budget", _empty_ledger())
    # Ayin basinda monthly toplami reset
    current_month = datetime.utcnow().strftime("%Y-%m")
    if data.get("month_key") != current_month:
        data["month_key"] = current_month
        data["totals"]["month"] = 0.0
        state_store.write("budget", data)
    return data


def _write_ledger(data: dict[str, Any]) -> None:
    state_store.write("budget", data)


def compute_snapshot() -> dict[str, Any]:
    """CEO'nun herwhich bir anda bakabilecegi budget snapshot'i."""
    cfg = config_loader.budget()
    ledger = _current_ledger()
    cap = float(cfg.get("totals", {}).get("monthly_cap", 0))
    soft = float(cfg.get("totals", {}).get("soft_warning_at", 0.75))
    hard = float(cfg.get("totals", {}).get("hard_block_at", 0.95))
    month_spend = float(ledger["totals"]["month"])
    ratio = (month_spend / cap) if cap else 0.0
    return {
        "currency": cfg.get("currency", "USD"),
        "monthly_cap": cap,
        "month_spend": month_spend,
        "month_ratio": round(ratio, 3),
        "soft_warning_threshold": soft,
        "hard_block_threshold": hard,
        "soft_warning_hit": ratio >= soft,
        "hard_block_hit": ratio >= hard,
        "agent_costs_monthly": cfg.get("agent_costs_monthly", {}),
        "single_decision_cap": cfg.get("thresholds", {}).get("single_decision_cap", 0),
        "recent_entries": ledger["entries"][-10:],
    }


@tool(
    "get_report",
    "Existing budget state and last spendlari dondurur. CEO stratejik decision beforesi this calls.",
    {},
)
async def get_report(args: dict) -> dict:
    snap = compute_snapshot()
    lines = [
        f"Budget state ({snap['currency']}):",
        f"  Monthly upper limit:  {snap['monthly_cap']:.2f}",
        f"  This ay spend:   {snap['month_spend']:.2f}  ({snap['month_ratio']*100:.1f}%)",
        f"  Soft warning:    {snap['soft_warning_threshold']*100:.0f}%  (hit: {snap['soft_warning_hit']})",
        f"  Hard block:      {snap['hard_block_threshold']*100:.0f}%  (hit: {snap['hard_block_hit']})",
        f"  Single decision limit: {snap['single_decision_cap']:.2f}",
        "",
        "Last spendlar:",
    ]
    for e in snap["recent_entries"]:
        lines.append(f"  - {e['ts']}  {e['category']:20s}  {e['amount']:>8.2f}  {e.get('note','')}")
    if not snap["recent_entries"]:
        lines.append("  (not yet record none)")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "log_expense",
    "Bir spendyi budget ledgerina kaydeder. role and amount mandatory, note serbest text.",
    {"role": str, "amount": float, "note": str},
)
async def log_expense(args: dict) -> dict:
    role = args.get("role", "").strip()
    amount = float(args.get("amount", 0))
    note = args.get("note", "")
    if amount <= 0:
        return {"content": [{"type": "text", "text": "amount must be > 0"}], "is_error": True}

    def mutate(data):
        data.setdefault("entries", []).append({
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "category": role or "misc",
            "amount": amount,
            "note": note,
        })
        totals = data.setdefault("totals", {"all_time": 0.0, "month": 0.0})
        totals["all_time"] = float(totals.get("all_time", 0)) + amount
        totals["month"] = float(totals.get("month", 0)) + amount
        return data

    state_store.update("budget", mutate, _empty_ledger())
    snap = compute_snapshot()
    msg = (
        f"Saved: {role} {amount:.2f} {snap['currency']} — note: {note}\n"
        f"Ay toplami: {snap['month_spend']:.2f} / {snap['monthly_cap']:.2f} "
        f"({snap['month_ratio']*100:.1f}%)"
    )
    return {"content": [{"type": "text", "text": msg}]}


@tool(
    "request_user_approval",
    (
        "Userya (the owner) proposal sunar and response gelene until baddr. "
        "title, summary mandatory. details JSON string olarak verilebilir. "
        "Response 'approve', 'reject' or ek text olabilir."
    ),
    {"title": str, "summary": str, "details": str},
)
async def request_user_approval(args: dict) -> dict:
    title = args.get("title", "").strip() or "Approval heregi"
    summary = args.get("summary", "").strip() or "(summary none)"
    details_raw = args.get("details", "")
    details: dict = {}
    if details_raw:
        try:
            import json as _json
            details = _json.loads(details_raw) if details_raw.strip().startswith("{") else {"text": details_raw}
        except Exception:
            details = {"text": details_raw}

    response = await broker().submit(title, summary, details)
    return {"content": [{"type": "text", "text": f"User's responsei: {response}"}]}


@tool(
    "sync_from_analytics",
    ("Anthropic Admin API'den real spendyi cek and local ledger'in this ayki "
     "toplamini ona esitle. CEO/CFO 'analytics.usage_check' callsindan SONRA "
     "this callmali — boylece 'budget.get_report' now real sayilari yansitir. "
     "days: default 30 (this ay for), to note herersen note serbest."),
    {"days": int, "note": str},
)
async def sync_from_analytics(args: dict) -> dict:
    try:
        days = max(1, min(90, int(args.get("days") or 30)))
    except (TypeError, ValueError):
        days = 30
    note = (args.get("note") or "").strip()

    from . import analytics
    if not analytics.has_admin_key():
        return {"content": [{"type": "text",
                              "text": ("ANTHROPIC_ADMIN_API_KEY none — real spendyi cekemiyorum. "
                                       "Before admin key kur (docs/SERVICE_ACCOUNT.md), next tekrar try.")}],
                "is_error": True}

    try:
        data = analytics.fetch_combined(days)
    except Exception as e:
        return {"content": [{"type": "text",
                              "text": f"Analytics callsi failed: {e}"}],
                "is_error": True}

    if not data.get("ok"):
        return {"content": [{"type": "text",
                              "text": f"Analytics error: {data.get('error', 'bilining')}"}],
                "is_error": True}

    cost = data.get("cost") or {}
    if cost.get("error"):
        return {"content": [{"type": "text",
                              "text": f"Cost API error: {cost['error']}"}],
                "is_error": True}

    real_total = float(cost.get("total") or 0)
    currency = cost.get("currency") or "USD"
    ledger_before = _current_ledger()
    prev_month_spend = float(ledger_before.get("totals", {}).get("month", 0))
    delta = real_total - prev_month_spend

    def mutate(data):
        data.setdefault("entries", []).append({
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "category": "anthropic_actual_sync",
            "amount": delta,
            "note": (f"Sync: local {prev_month_spend:.4f} -> real {real_total:.4f} "
                     f"{currency} (delta {delta:+.4f}, last {days} day). {note}").strip(),
        })
        totals = data.setdefault("totals", {"all_time": 0.0, "month": 0.0})
        totals["all_time"] = float(totals.get("all_time", 0)) + delta
        totals["month"] = real_total
        return data

    state_store.update("budget", mutate, _empty_ledger())
    snap = compute_snapshot()

    lines = [
        "=== Local budget real Anthropic spendsiyla SENKRONLANDI ===",
        f"  Beforeki local month_spend:  {prev_month_spend:.4f} {currency}",
        f"  Real Anthropic (last {days}g): {real_total:.4f} {currency}",
        f"  Delta uygulandi:           {delta:+.4f} {currency}",
        "",
        "  Yeni state:",
        f"  Monthly cap:                 {snap['monthly_cap']:.2f}",
        f"  This ay spend (real):    {snap['month_spend']:.4f}  ({snap['month_ratio']*100:.2f}%)",
    ]
    if snap["soft_warning_hit"]:
        lines.append(f"  UYARI: soft warning ({snap['soft_warning_threshold']*100:.0f}%) GECILDI.")
    if snap["hard_block_hit"]:
        lines.append(f"  KRITIK: hard block ({snap['hard_block_threshold']*100:.0f}%) GECILDI.")
    lines.append("")
    lines.append("Sources:")
    lines.append(f"- Anthropic Admin API /v1/organizations/cost_report (last {days} day)")
    lines.append("- TeamForge budget.yaml monthly_cap referansi")
    if note:
        lines.append(f"- CEO notu: {note}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


BUDGET_TOOLS = [get_report, log_expense, request_user_approval, sync_from_analytics]
