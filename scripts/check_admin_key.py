"""Admin key diagnosis scripti — which org/workspace'leri goruyor?

Run (PowerShell):
  cd "C:/Users/cagda/Documents/Claude/Projects/TeamForge"
  .venv/Scripts/activate
  python scripts/check_admin_key.py
"""
import json, os, sys
from urllib import request as urlrequest, error as urlerror
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

admin_key = os.environ.get("ANTHROPIC_ADMIN_API_KEY")
standard_key = os.environ.get("ANTHROPIC_API_KEY")

print("=" * 60)
print("Anthropic Admin Key Diagnosisi")
print("=" * 60)
print(f"Admin key set:    {'EVET (...' + admin_key[-8:] + ')' if admin_key else 'HAYIR'}")
print(f"Standart key set: {'EVET (...' + standard_key[-8:] + ')' if standard_key else 'HAYIR'}")
print()

if not admin_key:
    print("Admin key none. .env'e ANTHROPIC_ADMIN_API_KEY=sk-ant-admin01-... add.")
    sys.exit(1)

def call(path):
    url = "https://api.anthropic.com/v1" + path
    req = urlrequest.Request(url, headers={
        "x-api-key": admin_key,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    })
    try:
        with urlrequest.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8")
        except Exception: pass
        return e.code, body

print("=== This admin key'in gordugu Workspaces ===")
status, data = call("/organizations/workspaces")
if status == 200:
    workspaces = data.get("data", []) if isinstance(data, dict) else []
    if not workspaces:
        print("HIC WORKSPACE YOK. Anthropic genelde 'Default Workspace' produces.")
    for w in workspaces:
        archived = "  [ARSIVLI]" if w.get("archived_at") else ""
        wid = w.get("id", "?")
        print(f"  - {w.get('name', '?'):40s} id={wid}{archived}")
        print(f"      created: {w.get('created_at', '?')}")
    print(f"\nToplam: {len(workspaces)} workspace")
else:
    print(f"HATA HTTP {status}: {str(data)[:300]}")

print()
print("=== Last 7 day GERCEK usage (cost report) ===")
from datetime import datetime, timedelta, timezone
end = datetime.now(timezone.utc).replace(microsecond=0)
start = end - timedelta(days=7)
status, data = call(
    "/organizations/cost_report?starting_at="
    + start.strftime("%Y-%m-%dT%H:%M:%SZ")
    + "&ending_at="
    + end.strftime("%Y-%m-%dT%H:%M:%SZ")
)
if status == 200:
    buckets = data.get("data", [])
    non_empty = [b for b in buckets if b.get("results")]
    print(f"Total bucket: {len(buckets)} (last 7 day, daily)")
    print(f"Filled bucket: {len(non_empty)}")
    if non_empty:
        print("\nFilled bucket detaylari:")
        for b in non_empty[:5]:
            print(f"  {b.get('starting_at', '?')[:10]}:")
            for r in b.get("results", []):
                print(f"    {r}")
    else:
        print("\nTUM bucket'lar empty — last 7 day 0 usage.")
        print("Iki olasilik:")
        print("  1. Admin key bambaska org'da, standart key'in being org'u doesn't see.")
        print("  2. Realten last 7 day 0 spend (test/stub kullaniyorsun).")
else:
    print("HATA: " + str(status) + " - " + str(data)[:200])

print()
print("=== Diagnosis resultu nadelete yorumla ===")
print("Yukaridaki workspace listnde, agent'larin kullandigi workspace'in adini sees musun?")
print("(Genelde 'Default Workspace' or elle bir name verdiysen its adi)")
print()
print("- EVET, correct workspace var but bucket empty -> realten usage 0 (1-2 hour badd)")
print("- WS goruyorum but benimkinden farkli -> separate org. Standart key'in altindaki org'da")
print("  yeni admin key create.")
print("- WORKSPACE LISTESI BOS -> admin key invalid or farkli problem.")
