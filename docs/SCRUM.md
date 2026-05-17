# TeamForge Scrum Framework

## Roller

| TeamForge role | Scrum role | Ana responsibility |
|---|---|---|
| Tech Lead | **ScrumMaster** | Sprint yonetimi, ceremony facilitator, code review gate, retro reportma CEO'ya |
| Business Analyst | **Product Owner** | Backlog refinement, acceptance criteria, sprint goal'ina uydaily |
| Dev/Test Workers | **Dev Team** | Task uretimi (android/ios/frontend/backend/devops/test), pending_review akisi |
| Project Manager | **Tarafsiz koordinator** | Roadmap, kapasite, takvim — daily Scrum'a girmez but targets belirler |
| CEO | **Stakeholder** | Sprint end reportri okur, retro action'larini stratejik karara bagar |

## Cadence — 1 hafta sprint

```
Pzt 09:00  Sprint Planning   (~30 dk)   TL + BA + Dev Team
Pzt-Cum    Daily Standup     (15 dk)    All dev team
Cars 14:00 Backlog Grooming  (~45 dk)   TL + BA (next sprint)
Cum 16:00  Sprint Review     (~30 dk)   TL + BA + Dev Team + (CEO optional)
Cum 16:30  Retrospective     (~45 dk)   2 sprint'te bir (her 2 haftada 1 Cuma)
```

Sprint duration `config/team.yaml`'den not `scrum.start_sprint` in the parameter is determined (default 7 day).

## Sprint akisi

### 1. Sprint Planning (Pzt sabah)
- TL `scrum.current_sprint` ile bir beforeki kapali mi check eder
- BA backlog'u sunar, dev team kapasite recommendisi yapar
- Konsensus → TL `scrum.start_sprint(name, goals, planned_task_ids)` calls
- TL `scrum.log_ceremony(kind="planning", attendees=..., notes=..., action_items=...)` ile record

### 2. Daily Standup (her day, 15 dk)
- Optional record (many sik olursa noise happens, critical blocking log)
- TL baddyen `pending_review` task'lari hatirlatir

### 3. Backlog Grooming (Carsamba)
- TL + BA bir next sprint for task'lari ayrintilandirir
- Acceptance criteria netlestirilir, story point/efor tahmin is done
- TL `scrum.log_ceremony(kind="grooming", ...)` ile record

### 4. Sprint Review (Cuma 16:00)
- Dev team `pending_review` and `review_passed` task'lari demo
- TL `tasks.list(filter_status="review_passed")` runir
- BA stakeholder opinion receives, back bildirims into record passes
- TL `scrum.log_ceremony(kind="review", attendees=..., notes=..., action_items=...)`

### 5. Retrospective (her 2 haftada bir, Cuma 16:30)
- Dev team + TL + BA katilir
- "What good went, what kotu, what degistirelim" formati
- TL action item'lari collects, `scrum.log_ceremony(kind="retrospective", ...)` ile record
- TL `scrum.report_to_ceo(subject, body, priority, action_items)` ile **CEO'ya notifies**
- CEO bir next turunda `scrum.read_ceo_inbox()` ile sees, userya reportr

### 6. Sprint Close
- TL `scrum.close_sprint(sprint_id, summary)` calls
- Sprint registry'de "closed" olarak isaretlenir
- Yeni sprint for Pzt planning'e gidilir

## CEO retro reportma akisi

```
TL retrospective'i tutuyor
  -> action item'lari topluyor
  -> scrum.report_to_ceo(subject, body, priority, action_items)
       -> state/ceo_inbox.json'a is written
       -> dashboard'a "ceo_inbox" event'i broadcast olunur
  -> CEO'nun bir next turunda:
       1. scrum.read_ceo_inbox(unread_only=true)  calls
       2. Mesajlari okur, stratejik valuelendirir
       3. Userya report: "Last retro'dan TL that action'lari ileti..."
       4. scrum.mark_inbox_read(item_id) ile okundu flags
```

## Tool referansi

### Tech Lead (ScrumMaster)
- `scrum.start_sprint(name, goals, duration_days, planned_task_ids)`
- `scrum.current_sprint()`
- `scrum.list_sprints(limit)`
- `scrum.close_sprint(sprint_id, summary)`
- `scrum.log_ceremony(sprint_id, kind, attendees, notes, action_items)`
- `scrum.list_ceremonies(sprint_id, kind, limit)`
- `scrum.report_to_ceo(subject, body, priority, action_items)`

### BA (Product Owner)
- `scrum.current_sprint`
- `scrum.list_sprints`, `list_ceremonies`
- `scrum.log_ceremony` (grooming recordlari for)

### CEO (Stakeholder)
- `scrum.read_ceo_inbox(unread_only, limit)`
- `scrum.mark_inbox_read(item_id)`
- `scrum.current_sprint`, `list_sprints`, `list_ceremonies`

## State filelari

- `state/sprints.json` — sprint recordlari
- `state/ceremonies.json` — toplanti notlari
- `state/ceo_inbox.json` — TL'den CEO'ya inbox

## Userya reportma (CEO)

CEO her session acilisinda `scrum.read_ceo_inbox(unread_only=true)` callmali and if okunmamis record if exists userya that formatta sunmali:

```
Beforeki retrospektif reportu:

Topic: Sprint 2026-W17 Retro Action Items
Beforelik: medium

This sprintte fark edilenler:
- Code review baddmesi 2 day ortalamayi gectikten next dev team flow bozuluyor
- Mobile UAT'da real cihaz farm'i yetersiz, BrowserStack budget'i artirilmali
...

TL'nin recommendationri:
1. CR SLA: 4 hour forde TL first feedback
2. BrowserStack annual budget +$3000

Se's approvalini baddyen 1 madde: BrowserStack budget artisi.
```
