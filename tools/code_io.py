"""Developer agent'lari for scoped kod filesi okuma/writing — agresif rol guard'lari ile.

Davranis:
- Her role's only kendi alinstanta writing izni var (artifacts/<role>/).
- writes_code: false olan rolesde write_file YASAK (uiux_dev, marketing).
- Cross-domain yazim engellendi (backend frontend/'a can't write, vs.).
- Read serbest — everyone everyone's artifact'ini okuyabilir (knowledge.read_artifact already var).

Path kurallari:
- write_file path'i artifacts/ ALTINDA OLMALI
- Path first segment checkene subject: ya own role or 'shared/' must be
- writes_code: false olan rolesde 'kod uzantili' file writingk da forbidden
"""
from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import tool

from . import config_loader, live_log

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

# Rolen kendi adina yazabilecegi alanlar (path basi)
# Default: role's kendi klasoru + 'shared/' (planning/ortak doc)
_ROLE_DOMAINS: dict[str, set[str]] = {
    "android_dev": {"android_dev", "shared", "mobile-shared"},
    "ios_dev": {"ios_dev", "shared", "mobile-shared"},
    "frontend_dev": {"frontend_dev", "shared", "web-shared"},
    "backend_dev": {"backend_dev", "shared", "api-shared"},
    "devops_engineer": {"devops_engineer", "shared", "infra"},
    "mobile_tester": {"mobile_tester", "shared", "test"},
    "tester": {"tester", "shared", "test"},
}

# Which rolesde code.write_file TAMAMEN forbidden
_BLOCKED_WRITE = {"uiux_dev", "marketing_sales_specialist",
                   "ceo", "cfo", "project_manager", "business_analyst", "tech_lead"}

# Code filesi uzantisi — writes_code: false role'se closema
_CODE_EXTS = {".py", ".java", ".kt", ".swift", ".ts", ".tsx", ".js", ".jsx",
              ".go", ".rs", ".rb", ".php", ".c", ".cpp", ".cs", ".m", ".mm",
              ".sh", ".sql", ".yaml", ".tf", ".dockerfile"}


def _safe(path: str) -> Path:
    p = (ARTIFACTS_DIR / path).resolve()
    root = ARTIFACTS_DIR.resolve()
    if root != p and root not in p.parents:
        raise ValueError(f"Path artifacts/ outside: {path}")
    return p


def _check_write_permission(path: str) -> tuple[bool, str]:
    """Existing rol for writing izni var mi? (ok, mesaj)"""
    role = live_log.current_role()
    if role is None:
        return True, "(top-level: check skipnir)"
    # writes_code: false olan rolesde tamamen kapali
    if role in _BLOCKED_WRITE:
        return False, (f"Rol '{role}' code.write_file kullanamaz. "
                       f"Kod uretimi outsideki outputlar for knowledge.write_artifact kullan.")
    # Path basi check
    parts = Path(path).parts
    first = parts[0] if parts else ""
    domain = _ROLE_DOMAINS.get(role, {role, "shared"})
    if first not in domain:
        return False, (f"Rol '{role}' only {sorted(domain)} altina yazabilir; "
                       f"request edilen path first segment '{first}'. "
                       f"This domain {role}'a kapali. Correct role redirect or path'i change.")
    return True, ""


@tool(
    "write_file",
    ("artifacts/<rol>/ or artifacts/shared/ under kod filesi yazar. "
     "ROL GUARD: Only kendi domain'ine you can write. "
     "writes_code: false olan rolesde (CEO/CFO/PM/BA/TL/uiux_dev/marketing) BLOKE. "
     "Cross-domain yazim engellenir (backend frontend/'a can't write)."),
    {"path": str, "content": str},
)
async def write_file(args: dict) -> dict:
    path = args.get("path", "").strip()
    content = args.get("content", "")
    if not path:
        return {"content": [{"type": "text", "text": "path mandatory"}], "is_error": True}
    ok, msg = _check_write_permission(path)
    if not ok:
        return {"content": [{"type": "text",
                              "text": f"REDDEDILDI (rol guard): {msg}"}],
                "is_error": True}
    try:
        p = _safe(path)
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"content": [{"type": "text",
                          "text": (f"Yazildi: {p.relative_to(PROJECT_ROOT)}  "
                                   f"({len(content)} byte)")}]}


@tool(
    "read_file",
    "artifacts/ altindan bir fileyi okur. All agent'lar everyone's file okuyabilir.",
    {"path": str},
)
async def read_file(args: dict) -> dict:
    path = args.get("path", "").strip()
    if not path:
        return {"content": [{"type": "text", "text": "path mandatory"}], "is_error": True}
    try:
        p = _safe(path)
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}], "is_error": True}
    if not p.exists():
        return {"content": [{"type": "text",
                              "text": (f"File none: {path}. "
                                       f"knowledge.list_artifacts ile mevcutlari check et.")}],
                "is_error": True}
    return {"content": [{"type": "text", "text": p.read_text(encoding="utf-8")}]}


CODE_TOOLS = [write_file, read_file]
