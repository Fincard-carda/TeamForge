"""Anthropic Admin API client — defensive wrapper (servis hesabi modelle).

Anthropic'in current auth modelinde cost/usage endpoint'leri only admin
key (sk-ant-admin01-...) ile acilir. Workspace key or standart API key this
endpoint'lere eriseing. Workaround olarak admin key'i **en az ayricalikli
servis hesabi like davranmaya to force** for 3 layer adddik:

1. **Allowlist enforcement** — only 3 read-only endpoint calllabilir.
   Yarin one yanlislikla write endpoint callsi addrse kod-levelsinde RED.
2. **Audit log** — her call state/admin_api_audit.json'a falls
   (timestamp, path, source: agent or user, role).
3. **Rate limit** — hourly 60 call upper limiti (how many minute forde N call).
   Cache already 5dk; realten required call sayisi 1-3/hour. Anomali yakalanir.

Anthropic Console > Settings > Admin Keys over this servis for
**dedicated** bir admin key (orn. "teamforge-usage-monitor") createulmali and
.env'de ANTHROPIC_ADMIN_API_KEY olarak saklanmali. Sahibin personal key'i ile
karistirma; rotation for 3 ay periyot.

Endpoint'ler:
  GET /v1/organizations/cost_report
  GET /v1/organizations/usage_report/messages
  GET /v1/organizations/usage_report/claude_code

Answerlar expensive olabilir; 5 minutelik in-memory cache + JSON audit log.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import request as urlrequest, error as urlerror, parse as urlparse

from . import live_log

log = logging.getLogger("teamforge.analytics")

API_BASE = "https://api.anthropic.com/v1"
CACHE_TTL_SEC = 300  # 5 minute

# Anthropic Admin API cost_report `amount` field USD CENT olarak doruyor.
# Console'da $0.17 olan spend API'den 17.1002 amount geing → 100x = cent
# (currency: "USD" yazsa da). This sabit ile dollara convert.
_AMOUNT_DIVISOR = 100.0

# Workspace filter: cost and usage calllar's only this workspace'i covermasi.
# All workspaces (Default included) for empty birak.
# TeamForgeWorkspace workspace ID env var ile override acceptable.
_TEAMFORGE_WORKSPACE_ID = os.environ.get(
    "TEAMFORGE_WORKSPACE_ID", ""
)

# --- Defensive wrapper sabits ---
_ALLOWED_ADMIN_PATHS = {
    "/organizations/cost_report",
    "/organizations/usage_report/messages",
    "/organizations/usage_report/claude_code",
    "/organizations/workspaces",  # debug — org mismatch diagnosisi
}
_RATE_LIMIT_PER_HOUR = 60
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_FILE = _PROJECT_ROOT / "state" / "admin_api_audit.json"

_cache: dict[str, tuple[float, Any]] = {}
_call_history: deque = deque(maxlen=200)  # last calls (timestamp)


def has_admin_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_ADMIN_API_KEY"))


def _admin_key() -> str | None:
    return os.environ.get("ANTHROPIC_ADMIN_API_KEY")


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if not entry:
        return None
    ts, val = entry
    if time.time() - ts > CACHE_TTL_SEC:
        _cache.pop(key, None)
        return None
    return val


def _cache_set(key: str, val: Any) -> None:
    _cache[key] = (time.time(), val)


def clear_cache() -> None:
    _cache.clear()


def get_cached_cost(days: int = 30) -> dict | None:
    """Cache'te if exists cost_report dondurur, nonesa None. API callsi YAPMAZ.

    Dashboard /api/state like 'cheap read' yerlerinde kullanilir —
    rate limit'i tuketmemek for. Cache budget_monitor (hourly) tarafindan
    populate is done.
    """
    return _cache_get(f"cost:{days}")


def get_cached_usage(days: int = 30) -> dict | None:
    """Cache'te if exists usage_report dondurur, nonesa None. API callsi YAPMAZ."""
    return _cache_get(f"usage:{days}")


def _rate_limit_check() -> bool:
    """Hourly cap checke. True = permission, False = limit asildi."""
    now = time.time()
    hour_ago = now - 3600
    # Eski calllari at
    while _call_history and _call_history[0] < hour_ago:
        _call_history.popleft()
    return len(_call_history) < _RATE_LIMIT_PER_HOUR


def _audit_write(entry: dict) -> None:
    """Her admin API call state/admin_api_audit.json'a append.
    Corrupt file senaryosunda automatic resetleyip yeni bneverr."""
    try:
        _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"calls": []}
        if _AUDIT_FILE.exists():
            try:
                data = json.loads(_AUDIT_FILE.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "calls" not in data:
                    data = {"calls": []}
            except (json.JSONDecodeError, OSError) as parse_err:
                log.warning("Audit filesi broken (resetlenecek): %s", parse_err)
                # Backup'i tut, yeni file yarat
                try:
                    _AUDIT_FILE.rename(_AUDIT_FILE.with_suffix(".corrupt.bak"))
                except Exception:
                    pass
                data = {"calls": []}
        data.setdefault("calls", []).append(entry)
        if len(data["calls"]) > 500:
            data["calls"] = data["calls"][-500:]
        # Atomic write: temp -> rename (corrupt risk azalir)
        tmp = _AUDIT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        tmp.replace(_AUDIT_FILE)
    except Exception as e:
        log.warning("Audit yazim errorsi: %s", e)


def _current_source() -> dict:
    """Callyi kim/which rol tetikledi (live_log context'ten)."""
    role = None
    try:
        role = live_log.current_role()
    except Exception:
        pass
    return {"source": "agent" if role else "user_or_dashboard",
            "role": role or "(none)"}


def _http_get(path: str, params: dict[str, str]) -> dict:
    """Senkron HTTP GET — Anthropic Admin API for.

    GUARDS:
    1. Path allowlist'te mi?
    2. Rate limit asilmis mi?
    3. Admin key var mi?
    Her in state audit'e falls.
    """
    audit_entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "path": path,
        "method": "GET",
        "params_summary": ",".join(f"{k}={str(v)[:30]}" for k, v in params.items()),
        **_current_source(),
    }

    # 1) Allowlist check
    if path not in _ALLOWED_ADMIN_PATHS:
        audit_entry["status"] = "REJECTED_ALLOWLIST"
        _audit_write(audit_entry)
        raise RuntimeError(
            f"Path allowlist outside: {path}. "
            f"Permission verilen: {sorted(_ALLOWED_ADMIN_PATHS)}. "
            f"analytics.py defensive wrapper this callyi blocking."
        )

    # 2) Rate limit check
    if not _rate_limit_check():
        audit_entry["status"] = "REJECTED_RATE_LIMIT"
        _audit_write(audit_entry)
        raise RuntimeError(
            f"Rate limit asildi: hourly {_RATE_LIMIT_PER_HOUR} call. "
            f"Cache 5dk; tekrar deneme zamani: 1 hour forde."
        )

    # 3) Admin key check
    key = _admin_key()
    if not key:
        audit_entry["status"] = "REJECTED_NO_KEY"
        _audit_write(audit_entry)
        raise RuntimeError("ANTHROPIC_ADMIN_API_KEY none (sk-ant-admin01-...)")

    qs = urlparse.urlencode(params, doseq=True)
    url = f"{API_BASE}{path}?{qs}"
    req = urlrequest.Request(url, headers={
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    })
    try:
        with urlrequest.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8")
            _call_history.append(time.time())
            audit_entry["status"] = "OK"
            audit_entry["http_status"] = resp.status
            _audit_write(audit_entry)
            return json.loads(data)
    except urlerror.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8")
        except Exception: pass
        audit_entry["status"] = "HTTP_ERROR"
        audit_entry["http_status"] = e.code
        audit_entry["error"] = body[:200]
        _audit_write(audit_entry)
        raise RuntimeError(f"HTTP {e.code}: {body[:200]}")
    except Exception as e:
        audit_entry["status"] = "NETWORK_ERROR"
        audit_entry["error"] = str(e)[:200]
        _audit_write(audit_entry)
        raise


def _isoz(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_get_paginated(path: str, params: dict, max_pages: int = 10) -> dict:
    """Anthropic Admin API pagination wrapper.

    Default 'limit' ~7 being for all bucket'lari almak for has_more/next_page
    olduğu surece next pageyi cek. data array'lerini birlestir.
    """
    all_data: list = []
    page_params = dict(params)
    last_resp: dict = {}
    for _ in range(max_pages):
        resp = _http_get(path, page_params)
        last_resp = resp
        all_data.extend(resp.get("data") or [])
        if not resp.get("has_more"):
            break
        next_page = resp.get("next_page")
        if not next_page:
            break
        page_params = dict(params)
        page_params["page"] = next_page
    merged = dict(last_resp)
    merged["data"] = all_data
    merged["has_more"] = False
    return merged


# ------------------------------------------------------------------
# Yuksek levelli yardimcilar
# ------------------------------------------------------------------

def _to_float(v) -> float:
    """Anthropic API bazen string ('1.234'), bazen float, bazen cent (int) donduruyor."""
    if v is None: return 0.0
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        try: return float(v)
        except ValueError: return 0.0
    return 0.0


def fetch_cost_report(days: int = 30) -> dict[str, Any]:
    cache_key = f"cost:{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(days=days)
    # ONEMLI: group_by[] olmadan Anthropic API bucket'lara boş results dorabiing.
    # workspace_id ile group_by yapinca bucket-forde {amount, workspace_id} filledyor.
    params = {
        "starting_at": _isoz(start),
        "ending_at": _isoz(end),
        "bucket_width": "1d",
        # cost_report endpoint'i workspace_ids[] filter parametre KABUL ETMIYOR
        # (HTTP 400: Extra inputs are not permitted). This yuzden:
        # 1. group_by[]=workspace_id ile workspace per bucket-contents result'lar al
        # 2. Parser tarafinda only TeamForgeWorkspace workspace_id'li result'lari topla
        "group_by[]": ["workspace_id"],
    }
    raw = _http_get_paginated("/organizations/cost_report", params)

    # ROBUST PARSER — suddenly many structure destaddr
    # Format 1: {"data": [{"starting_at": "...", "results": [{"amount": X, "currency": "USD"}]}]}
    # Format 2: {"data": [{"starting_at": "...", "amount": X, "currency": "USD"}]}  (eski)
    # Format 3: {"data": [{"starting_at": "...", "amount": {"value": "1.234", "currency": "USD"}}]}
    # Format 4 (yeni): amount cents olarak (int * 0.01)
    # DEDUPE: pagination next_page bazen same bucket'i tekrar dorebiing — starting_at per dedupe
    raw_buckets = raw.get("data") or []
    _seen_starts: dict[str, dict] = {}
    for b in raw_buckets:
        key = b.get("starting_at") or ""
        # Same day for before filled olani tercih et, nonesa last geleni tut
        if key not in _seen_starts or (b.get("results") and not _seen_starts[key].get("results")):
            _seen_starts[key] = b
    deduped_buckets = list(_seen_starts.values())
    duplicate_count = len(raw_buckets) - len(deduped_buckets)

    # Daily aggregation by date — aynı gün multiple workspace/result satiri olabilir
    daily_by_date: dict[str, float] = {}
    total = 0.0
    currency = "USD"
    skipped_other_workspace = 0
    for bucket in deduped_buckets:
        bucket_start = bucket.get("starting_at") or ""
        date_key = bucket_start[:10]
        # results array if exists it kullan, nonesa direkt bucket'in kendi sayisal hesapla
        sub_items = bucket.get("results")
        if not sub_items:  # None or [] - ikisi de bucket'in kendisinde amount ara
            sub_items = [bucket]
        for r in sub_items:
            # Workspace filter — only TeamForgeWorkspace workspace'i's satirlarini al.
            # workspace_id None ise (Default Workspace or workbench) skip.
            if _TEAMFORGE_WORKSPACE_ID:
                row_wsid = r.get("workspace_id")
                if row_wsid != _TEAMFORGE_WORKSPACE_ID:
                    skipped_other_workspace += 1
                    continue
            amount_field = r.get("amount") or r.get("cost") or r.get("total")
            if isinstance(amount_field, dict):
                # Nested: {"value": "1.234", "currency": "USD"}
                amount = _to_float(amount_field.get("value") or amount_field.get("amount"))
                currency = amount_field.get("currency") or currency
            else:
                amount = _to_float(amount_field)
                currency = r.get("currency") or currency
            # ONEMLI: Anthropic API amount'i CENT olarak doruyor. Dollar'a convert.
            amount = amount / _AMOUNT_DIVISOR
            daily_by_date[date_key] = daily_by_date.get(date_key, 0.0) + amount
            total += amount
    # Datee gore descending (en yeni en ustte)
    daily = [{"date": d, "amount": amt}
             for d, amt in sorted(daily_by_date.items(), reverse=True)]

    # Debug sample: tercihen NON-EMPTY bucket'lardan al, nonesa first 2'yi
    all_buckets = raw.get("data", []) or []
    non_empty = [b for b in all_buckets if b.get("results") or b.get("amount")]
    sample = non_empty[:2] if non_empty else all_buckets[:2]
    last_bucket = all_buckets[-1] if all_buckets else None
    days_with_data = sum(1 for d in daily if d["amount"] > 0)
    out = {
        "currency": currency, "total": round(total, 4), "days": days,
        "days_with_data": days_with_data,
        "avg_per_day_with_data": round(total / days_with_data, 4) if days_with_data else 0.0,
        "daily": daily,
        "starting_at": params["starting_at"], "ending_at": params["ending_at"],
        "raw_buckets": len(all_buckets),
        "raw_non_empty_buckets": len(non_empty),
        "raw_duplicate_buckets": duplicate_count,
        "filtered_workspace": _TEAMFORGE_WORKSPACE_ID or "(all)",
        "skipped_other_workspace_rows": skipped_other_workspace,
        "_raw_sample": sample,
        "_last_bucket": last_bucket,
    }
    _cache_set(cache_key, out)
    return out


def fetch_usage_report(days: int = 30) -> dict[str, Any]:
    cache_key = f"usage:{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(days=days)
    params = {
        "starting_at": _isoz(start), "ending_at": _isoz(end),
        "bucket_width": "1d",
        "group_by[]": ["model"],
        # limit'i set etme — Anthropic upper limit koyuyor.
        # When pagination wrapper sees has_more, it collects all buckets via next_page.
    }
    # Workspace filter — only TeamForgeWorkspace workspace'i's usagei
    if _TEAMFORGE_WORKSPACE_ID:
        params["workspace_ids[]"] = _TEAMFORGE_WORKSPACE_ID
    raw = _http_get_paginated("/organizations/usage_report/messages", params)

    by_model: dict[str, dict[str, int]] = {}
    totals = {"uncached_input": 0, "cache_creation": 0, "cache_read": 0, "output": 0}
    # Alternatif field names (Anthropic API zaman forde degisebilir)
    FIELD_MAP = {
        "uncached_input": ["uncached_input_tokens", "input_tokens", "prompt_tokens"],
        "cache_creation": ["cache_creation_input_tokens", "cache_creation_tokens"],
        "cache_read": ["cache_read_input_tokens", "cache_read_tokens", "cached_tokens"],
        "output": ["output_tokens", "completion_tokens"],
    }
    for bucket in (raw.get("data") or []):
        sub_items = bucket.get("results")
        if not sub_items:  # None or [] - bucket'in kendisinde token alanlari ara
            sub_items = [bucket]
        for r in sub_items:
            model = r.get("model") or r.get("model_name") or "unknown"
            slot = by_model.setdefault(model, {
                "uncached_input": 0, "cache_creation": 0, "cache_read": 0, "output": 0,
            })
            for k, alt_names in FIELD_MAP.items():
                # First match'i kullan
                v = 0
                for n in alt_names:
                    if n in r:
                        try: v = int(r.get(n) or 0)
                        except (TypeError, ValueError): v = 0
                        break
                slot[k] += v
                totals[k] += v

    all_buckets = raw.get("data", []) or []
    non_empty = [b for b in all_buckets if b.get("results") or any(k in b for k in ("uncached_input_tokens", "input_tokens"))]
    sample = non_empty[:2] if non_empty else all_buckets[:2]
    last_bucket = all_buckets[-1] if all_buckets else None
    out = {
        "days": days, "totals": totals, "by_model": by_model,
        "starting_at": params["starting_at"], "ending_at": params["ending_at"],
        "raw_buckets": len(all_buckets),
        "raw_non_empty_buckets": len(non_empty),
        "_raw_sample": sample,
        "_last_bucket": last_bucket,
    }
    _cache_set(cache_key, out)
    return out


def fetch_workspaces() -> dict[str, Any]:
    """Admin key'in gordugu workspaces'i list — org mismatch diagnosisi for."""
    cache_key = "workspaces"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        raw = _http_get("/organizations/workspaces", {})
    except Exception as e:
        return {"error": str(e), "data": []}
    workspaces = raw.get("data") or []
    out = {
        "count": len(workspaces),
        "workspaces": [{
            "id": w.get("id"),
            "name": w.get("name"),
            "type": w.get("type"),
            "created_at": w.get("created_at"),
            "archived_at": w.get("archived_at"),
        } for w in workspaces],
    }
    _cache_set(cache_key, out)
    return out


def fetch_combined(days: int = 30) -> dict[str, Any]:
    if not has_admin_key():
        return {
            "ok": False,
            "error": "ANTHROPIC_ADMIN_API_KEY env var set not",
            "hint": "https://console.anthropic.com/settings/admin-keys over create, .env'e add.",
        }
    out: dict[str, Any] = {"ok": True, "days": days,
                            "cached": False,
                            "fetched_at": datetime.utcnow().isoformat() + "Z"}
    try: out["cost"] = fetch_cost_report(days)
    except Exception as e: out["cost"] = {"error": str(e)}
    try: out["usage"] = fetch_usage_report(days)
    except Exception as e: out["usage"] = {"error": str(e)}
    return out


async def fetch_combined_async(days: int = 30) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fetch_combined, days)


# ============================================================
# MCP TOOLS — CEO/CFO for canli usage/cost check
# ============================================================

from claude_agent_sdk import tool  # noqa: E402


@tool(
    "usage_check",
    ("Anthropic Admin API'den last N day's cost + token usageini cek, "
     "TeamForge budget ile compare. days: 1-90 (default 30). "
     "Admin key nonesa graceful warning. Defensive wrapper: rate limit + allowlist + audit log."),
    {"days": int},
)
async def usage_check(args: dict) -> dict:
    try: days = max(1, min(90, int(args.get("days") or 30)))
    except (TypeError, ValueError): days = 30
    data = await fetch_combined_async(days)
    if not data.get("ok"):
        return {"content": [{"type": "text",
                              "text": (f"Admin API none: {data.get('error')}\n"
                                       f"Hint: {data.get('hint','')}\n\n"
                                       "Anthropic Console > Settings > Admin Keys -> "
                                       "ANTHROPIC_ADMIN_API_KEY .env'e add.\n"
                                       "DETAY: docs/SERVICE_ACCOUNT.md")}],
                "is_error": True}

    cost = data.get("cost") or {}
    usage = data.get("usage") or {}
    cost_total = cost.get("total", 0)
    currency = cost.get("currency", "USD")
    usage_totals = usage.get("totals", {})
    total_tokens = sum(usage_totals.values()) if usage_totals else 0

    try:
        from .budget import compute_snapshot
        snap = compute_snapshot()
        monthly_cap = snap.get("monthly_cap", 0)
        cap_used_pct = (cost_total / monthly_cap * 100) if monthly_cap else 0
        runway_days_at_burn = (monthly_cap - cost_total) / (cost_total / days) if cost_total > 0 else None
    except Exception:
        snap = {"monthly_cap": 0, "currency": "USD"}
        cap_used_pct = 0
        runway_days_at_burn = None

    by_model = usage.get("by_model", {})
    top_models = sorted(by_model.items(),
                        key=lambda x: sum(x[1].values()), reverse=True)[:5]

    lines = [
        f"=== Anthropic API Usage Check (last {days} day) ===",
        "",
        f"  Total cost:    {cost_total:.2f} {currency}",
        f"  Total token:      {total_tokens:,}",
        f"    - input (uncached): {usage_totals.get('uncached_input', 0):,}",
        f"    - input (cached):   {usage_totals.get('cache_read', 0):,}",
        f"    - cache create:     {usage_totals.get('cache_creation', 0):,}",
        f"    - output:           {usage_totals.get('output', 0):,}",
        "",
        f"  Daily ortalama:   {cost_total / days:.2f} {currency}/day",
        "",
        f"  TeamForge budget cap: {snap.get('monthly_cap', 0):.0f} {snap.get('currency', 'USD')}/ay",
        f"  Usage:          %{cap_used_pct:.1f}",
    ]
    if runway_days_at_burn:
        lines.append(f"  This burn ile cap'e kalan: {runway_days_at_burn:.0f} day")
    if cap_used_pct > 75:
        lines.append("")
        lines.append("  UYARI: budget usagei >%75 — userya bildir.")
    if cap_used_pct > 95:
        lines.append("  KRITIK: budget >%95 filled — yeni spendyi approvalsiz startma.")
    if top_models:
        lines.append("")
        lines.append("  Top usage (model basi):")
        for m, t in top_models:
            tot = sum(t.values())
            pct = (tot / total_tokens * 100) if total_tokens else 0
            lines.append(f"    {m:40s} {tot:>10,} token  (%{pct:.1f})")

    lines.append("")
    lines.append("Sources:")
    lines.append(f"- Anthropic Admin API /v1/organizations/cost_report ({days} day, audit'lendi)")
    lines.append(f"- Anthropic Admin API /v1/organizations/usage_report/messages")
    lines.append(f"- TeamForge budget.yaml (monthly_cap)")
    lines.append(f"- Cache fetched_at: {data.get('fetched_at', '-')}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "cost_report",
    "Only cost detayi (daily breakdown). days: 1-90.",
    {"days": int},
)
async def cost_report(args: dict) -> dict:
    try: days = max(1, min(90, int(args.get("days") or 30)))
    except (TypeError, ValueError): days = 30
    if not has_admin_key():
        return {"content": [{"type": "text",
                              "text": "ANTHROPIC_ADMIN_API_KEY none. docs/SERVICE_ACCOUNT.md read."}],
                "is_error": True}
    try:
        cost = fetch_cost_report(days)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Cost API error: {e}"}],
                "is_error": True}

    lines = [f"=== Cost Report (last {days} day) ==="]
    lines.append(f"Total: {cost.get('total', 0):.2f} {cost.get('currency', 'USD')}")
    lines.append("")
    daily = cost.get("daily") or []
    if daily:
        lines.append("Daily breakdown (last 15):")
        for d in daily[-15:]:
            lines.append(f"  {d.get('date', '-'):12s}  {d.get('amount', 0):>8.2f}")
    lines.append("")
    lines.append(f"Source: Anthropic Admin API (audit'lendi)")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "usage_report",
    "Model based token usage detayi. days: 1-90.",
    {"days": int},
)
async def usage_report(args: dict) -> dict:
    try: days = max(1, min(90, int(args.get("days") or 30)))
    except (TypeError, ValueError): days = 30
    if not has_admin_key():
        return {"content": [{"type": "text",
                              "text": "ANTHROPIC_ADMIN_API_KEY none."}],
                "is_error": True}
    try:
        usage = fetch_usage_report(days)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Usage API error: {e}"}],
                "is_error": True}

    totals = usage.get("totals", {})
    by_model = usage.get("by_model", {})
    lines = [f"=== Usage Report (last {days} day, model based) ==="]
    lines.append("")
    lines.append("Total tokens:")
    for k, v in totals.items():
        lines.append(f"  {k:20s} {v:>12,}")
    lines.append("")
    lines.append(f"{'Model':50s} {'Total':>12s} {'Input':>12s} {'Cached':>12s} {'Output':>12s}")
    for model, t in sorted(by_model.items(), key=lambda x: -sum(x[1].values())):
        total = sum(t.values())
        lines.append(f"  {model:48s} {total:>12,} "
                     f"{t.get('uncached_input', 0):>12,} "
                     f"{t.get('cache_read', 0):>12,} "
                     f"{t.get('output', 0):>12,}")
    lines.append("")
    lines.append("Source: Anthropic Admin API (audit'lendi)")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "audit_log",
    ("Admin API call audit log'unu show. last: how many line drecommend (default 20)."),
    {"last": int},
)
async def audit_log(args: dict) -> dict:
    try: n = max(1, min(100, int(args.get("last") or 20)))
    except (TypeError, ValueError): n = 20
    if not _AUDIT_FILE.exists():
        return {"content": [{"type": "text", "text": "Audit log not yet createulmadi (hic call none)."}]}
    try:
        data = json.loads(_AUDIT_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Audit read error: {e}"}],
                "is_error": True}
    calls = data.get("calls", [])
    recent = calls[-n:]
    lines = [f"=== Admin API Audit Log (last {len(recent)}/{len(calls)} record) ==="]
    for c in recent:
        st = c.get("status", "?")
        flag = "OK " if st == "OK" else "BLK"
        lines.append(f"  [{c.get('ts','?')[:19]}] {flag} {st:20s} "
                     f"{c.get('path','?'):40s} src={c.get('role','?')}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


ANALYTICS_TOOLS = [usage_check, cost_report, usage_report, audit_log]
