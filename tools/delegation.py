"""Hierarchyk delegation tool'lari — async-first + peer review.

Davranis:
- Default: chain delegasyonlari (PM->BA, BA->worker) sync; CEO/CFO arasi async.
- Opt-in: mode="async" or mode="sync" ile override.

Async modda agent:
- Callyi yapar, instant "Job queueta" responsei receives
- Resultlari delegate.read_inbox or check_result ile pulling
- Only persherent agent'lar (CEO/CFO) for auto-wake active
"""
from __future__ import annotations

import logging

from claude_agent_sdk import tool

from . import jobs

log = logging.getLogger("teamforge.delegation")


def _mode(args: dict, default: str = "async") -> str:
    raw = (args.get("mode") or default).strip().lower()
    if raw in ("sync", "wait", "true", "blocking"):
        return "sync"
    if raw in ("async", "false", "fire", "background"):
        return "async"
    return default


def _build_prompt(msg: str, ctx: str) -> str:
    return msg if not ctx else f"[Context]\n{ctx}\n\n[Gorev]\n{msg}"


async def _dispatch(role: str, args: dict, caller: str, default_subject: str,
                     default_mode: str = "async") -> dict:
    msg = args.get("message", "").strip()
    ctx = args.get("context", "").strip()
    subject = (args.get("subject") or "").strip() or default_subject
    if not msg:
        return {"content": [{"type": "text", "text": "message mandatory"}], "is_error": True}
    mode = _mode(args, default=default_mode)
    prompt = _build_prompt(msg, ctx)
    mgr = jobs.JobManager.get()
    if mode == "sync":
        job_id, text = await mgr.run_sync(role, prompt, caller, subject=subject)
        return {"content": [{"type": "text",
                              "text": f"[SYNC result — job {job_id}]\n\n{text}"}]}
    job_id = mgr.submit(role, prompt, caller, mode="async", subject=subject)
    return {"content": [{"type": "text",
                          "text": (f"Job queueta: {job_id}  ({caller} -> {role})\n"
                                   f"Topic: {subject}\n"
                                   f"Resultu gormek for: delegate.check_result(job_id=\"{job_id}\") "
                                   f"or delegate.read_inbox(role=\"{caller}\")")}]}


@tool(
    "to_pm",
    ("CEO -> PM. Default async (CEO persherent — inbox'tan okur). "
     "Next step PM responseina KESIN bagliysa mode=\"sync\" late."),
    {"message": str, "context": str, "subject": str, "mode": str},
)
async def to_pm(args: dict) -> dict:
    return await _dispatch("project_manager", args, caller="ceo",
                            default_subject="(CEO -> PM mesaj)")


@tool(
    "to_ba",
    ("PM -> BA. **Default sync** (PM transient — resultu baddmeli). "
     "Async'e convertmek herersen mode=\"async\"; nadir usage."),
    {"message": str, "context": str, "subject": str, "mode": str},
)
async def to_ba(args: dict) -> dict:
    return await _dispatch("business_analyst", args, caller="project_manager",
                            default_subject="(PM -> BA mesaj)", default_mode="sync")


@tool(
    "to_worker",
    ("BA/Tech Lead/CFO bir uzmana gorev verir. **Default sync** — caller transient. "
     "from_role: 'business_analyst' | 'tech_lead' | 'cfo'. "
     "role: android_dev | ios_dev | uiux_dev | frontend_dev | backend_dev | "
     "mobile_tester | tester | marketing_sales_specialist | devops_engineer."),
    {"role": str, "message": str, "context": str, "subject": str,
     "mode": str, "from_role": str},
)
async def to_worker(args: dict) -> dict:
    role = args.get("role", "").strip()
    from_role = (args.get("from_role") or "").strip().lower()
    if from_role not in ("business_analyst", "tech_lead", "cfo"):
        from_role = "cfo" if role == "marketing_sales_specialist" else "business_analyst"
    allowed = {"android_dev", "ios_dev", "uiux_dev",
                "frontend_dev", "backend_dev",
                "mobile_tester", "tester",
                "marketing_sales_specialist",
                "devops_engineer"}
    if role not in allowed:
        return {"content": [{"type": "text",
                              "text": f"Gecersiz rol: {role}. Permission verilen: {sorted(allowed)}"}],
                "is_error": True}
    if from_role == "cfo" and role != "marketing_sales_specialist":
        return {"content": [{"type": "text",
                              "text": (f"CFO only marketing_sales_specialist'e atayabilir. "
                                       f"'{role}' for BA or Tech Lead over late.")}],
                "is_error": True}
    return await _dispatch(role, args, caller=from_role,
                            default_subject=f"({from_role} -> {role})",
                            default_mode="sync")


@tool(
    "to_tech_lead",
    ("CEO or PM'den TL'e technical danisma. PM->TL sync, CEO->TL async default. "
     "Mode override: \"sync\" or \"async\"."),
    {"message": str, "context": str, "subject": str, "mode": str, "from_role": str},
)
async def to_tech_lead(args: dict) -> dict:
    from_role = args.get("from_role", "").strip() or "project_manager"
    if from_role not in ("ceo", "project_manager"):
        from_role = "project_manager"
    default_mode = "async" if from_role == "ceo" else "sync"
    return await _dispatch("tech_lead", args, caller=from_role,
                            default_subject=f"({from_role} -> TL)",
                            default_mode=default_mode)


@tool(
    "to_cfo",
    ("CEO -> CFO. **Default async** (her ikisi de persherent). "
     "mode=\"sync\" only CFO sayis's hemen requiredsa."),
    {"message": str, "context": str, "subject": str, "mode": str},
)
async def to_cfo(args: dict) -> dict:
    return await _dispatch("cfo", args, caller="ceo",
                            default_subject="(CEO -> CFO mesaj)",
                            default_mode="async")


@tool(
    "to_ceo",
    ("CFO -> CEO. CFO inisiyatifiyle escalation/warning/koordinasyon. "
     "Default async — CEO inbox'una falls, CEO next okur."),
    {"message": str, "context": str, "subject": str, "mode": str},
)
async def to_ceo(args: dict) -> dict:
    subject = args.get("subject", "").strip() or "(CFO -> CEO mesaj)"
    args["subject"] = subject
    msg = args.get("message", "")
    if msg:
        args["message"] = f"[CFO'dan gelen mesaj — Topic: {subject}]\n\n{msg}"
    return await _dispatch("ceo", args, caller="cfo",
                            default_subject=subject,
                            default_mode="async")


# Yuksek-stake output dogrulama for peer review
_PEER_REVIEW_ALLOWED_REVIEWERS = {
    "tech_lead", "business_analyst", "cfo", "ceo", "project_manager",
}


@tool(
    "peer_review",
    ("Yuksek-stake bir output's (prforg memo, board update, mimari ADR, scope karari) "
     "**baska bir agent tarafindan dogrulanmasi**. Default sync — review resultu donmeli. "
     "reviewer_role: tech_lead | business_analyst | cfo | ceo | project_manager. "
     "review_type: 'sayisal_dogrulama' | 'mimari_review' | 'scope_check' | 'finansal_check' | 'general'. "
     "from_role: callan agent (audit trace)."),
    {"artifact_role": str, "artifact_name": str, "reviewer_role": str,
     "review_type": str, "from_role": str, "specific_cbeforerns": str},
)
async def peer_review(args: dict) -> dict:
    art_role = args.get("artifact_role", "").strip()
    art_name = args.get("artifact_name", "").strip()
    reviewer = args.get("reviewer_role", "").strip().lower()
    review_type = args.get("review_type", "general").strip().lower()
    from_role = args.get("from_role", "unknown").strip().lower()
    cbeforerns = args.get("specific_cbeforerns", "").strip()

    if not art_role or not art_name:
        return {"content": [{"type": "text",
                              "text": "artifact_role and artifact_name mandatory"}],
                "is_error": True}
    if reviewer not in _PEER_REVIEW_ALLOWED_REVIEWERS:
        return {"content": [{"type": "text",
                              "text": (f"Gecersiz reviewer: {reviewer}. "
                                       f"Permission verilen: {sorted(_PEER_REVIEW_ALLOWED_REVIEWERS)}")}],
                "is_error": True}
    if reviewer == from_role:
        return {"content": [{"type": "text",
                              "text": "Kendi outputni kendin review edemezsin (objektif not). "
                                      "Farkli bir reviewer select."}],
                "is_error": True}

    review_prompts = {
        "sayisal_dogrulama": ("This outputdaki all sayilari check et. Her iddia for tool grounding "
                              "var mi? CAC, LTV, payback period, runway like metriks dogrula. "
                              "Wrong or kanitsiz olanlari isaretle."),
        "mimari_review": ("This artifact'in mimari kararlarini incele. Coding standards, ADR pattern, "
                          "tech debt etkisi acisindan valuelendir. Recommendilerini madde madde ver."),
        "scope_check": ("This artifact sprint scope'una uyuyor mu? Approvalsiz scope creep var mi? "
                        "PM perspektifinden uyday mu?"),
        "finansal_check": ("This output's finansal etkilerini dogrula. Unit economics, budget fizibilitesi, "
                           "ROI mantikli mi? Kati gozle sayisal check do."),
        "general": ("This artifact'i baska bir expert gozuyle review et. Amountlilik, tam veri kanit chain, "
                  "halusinasyon belirtisi, mantik errorsi var mi? Bul and report."),
    }
    instruction = review_prompts.get(review_type, review_prompts["general"])

    review_prompt = (
        f"[PEER REVIEW heregi]\n\n"
        f"This artifact'i {review_type} acisindan REVIEW et:\n"
        f"- Yazan rol: {art_role}\n"
        f"- File: {art_name}\n"
        f"- Request eden: {from_role}\n"
        f"- Spesifik endiseler: {cbeforerns or '(yok)'}\n\n"
        f"YAPILACAK:\n"
        f"1. `knowledge.read_artifact(role=\"{art_role}\", name=\"{art_name}\")` ile artifact'i read\n"
        f"2. {instruction}\n"
        f"3. Yapilandirilmis review write:\n"
        f"   - ONAY: tam approvalli / kosullu / red\n"
        f"   - Bulgu (madde madde, her birinde sayi/alinti)\n"
        f"   - Missing kanit (source gosterilmeyen iddialar)\n"
        f"   - Recommendilen fixmeler\n"
        f"4. Sonunda kararini net say: 'YESIL ISIK' or 'KIRMIZI ISIK + neden' or 'SARI ISIK + fixme list'"
    )

    # Sync — review'in resultunu bto add needed, caller decision verecek
    mgr = jobs.JobManager.get()
    job_id, text = await mgr.run_sync(reviewer, review_prompt, from_role,
                                        subject=f"PEER REVIEW: {art_role}/{art_name}")
    return {"content": [{"type": "text",
                          "text": f"[PEER REVIEW — job {job_id}, reviewer={reviewer}]\n\n{text}"}]}


DELEGATION_TOOLS = [to_pm, to_ba, to_worker, to_tech_lead, to_cfo, to_ceo, peer_review]
