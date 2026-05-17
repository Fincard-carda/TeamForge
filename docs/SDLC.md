# TeamForge SDLC — Software Development Lifecycle (v0.1)

> This dokuminstant sahibi: **Tech Lead**. All dev/test agent'lar this akisi tracking eder.
> TL this fileyi `knowledge.write_spec("sdlc-v1", ...)` ile zenginlestirir.

## Faz 1 — Planning
- CEO stratejik hedefi acar (browser or terminal)
- PM hedefi epic + sprint plani haline getirir
- Tech Lead mimari recommendi sunar (gerekirse ADR)

## Faz 2 — Design
- BA spec yazar (`knowledge.write_spec`) — acceptance criteria, BPMN, sequence
- UI/UX wireframe + design tokens (`knowledge.write_artifact("uiux_dev", ...)`)
- Tech Lead spec'i review eder, mimari uyumu approvals (ADR + decision)

## Faz 3 — Implementation
- BA `tasks.create` + `tasks.assign` ile task'leri worker'lara dagitir
- Worker `tasks.update(status="in_progress")` + kodu yazar
- Worker `code.write_file` ile artifacts/<role>/ altina record
- Worker bittiginde `tasks.update(status="pending_review")` — kendisi DONE cannot do

## Faz 4 — Code Review (TECH LEAD GATE)
- Tech Lead `tasks.list(filter_status="pending_review")` ile baddyens sees
- Artifact'leri `code.read_file` ile inceler
- Coding standards (docs/CODING_STANDARDS.md) uyumu check
- Verdict koyar: `tasks.review(task_id, verdict, review_note, review_artifact_path)`
  - `review_passed` → Faz 5'e late
  - `needs_changes` → Faz 3'e back (worker tekrar code yazar)
  - `rejected` → BA again plan yapar (Faz 2'ye back)

## Faz 5 — Test
- Mobile_tester / tester atamali UAT/integration test taski produces
- Test gecerse: `tasks.update(status="pending_review")` → TL test artifact'lerini approvals
- Test gecmezse: blocker olarak isaretle, dev'e back don

## Faz 6 — Deploy
- DevOps engineer staging deploy yapar (`code.write_file` IaC + CI workflow)
- TL deploy artifact'ini approvals
- BA "done" tasir
- Production deploy ya canary ya blue/green (DevOps produces, TL approvals)

## Faz 7 — Monitor
- DevOps observability dashboards must be set up must be
- SRE alert/runbook playbook'lari `artifacts/devops_engineer/runbook-*.md` under
- Post-mortem gerekirse Tech Lead `knowledge.write_decision` ile yazar

## Status Akisi (formal)

```
open
  -> in_progress         (worker basing)
    -> pending_review    (worker tamamlandi says)
      -> review_passed   (TL approvali — only TL)
        -> done          (BA/PM/CEO tasiyabilir)
      -> needs_changes   (TL back senddi)
        -> in_progress   (worker tekrar code)
      -> rejected        (TL mimari problem isaretledi)
        -> open / cancelled
    -> blocked           (worker baddyen var)
```

## Audit / Tracelog
- Her status degisikligi `tasks.json` inside `history` alinstanta dusulur
- Tech Lead review verdict'leri `review_history` forde de saklanir
- Audit log `state/config_audit.json` and agent transcript'leri all izlemeyi provides
