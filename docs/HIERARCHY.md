# Hierarchy and Delegation Kurallari

## Kim kimle konusur?

| Source | Hedef | Mekanizma |
|---|---|---|
| You | CEO | orchestrator.py REPL |
| CEO | PM | `delegate.to_pm` |
| CEO | You | `budget.request_user_approval` (only approval/proposal) |
| PM | BA | `delegate.to_ba` |
| PM | CEO | `team.request_new_agent` (queue over, CEO kendi turunda sees) |
| BA | Worker | `delegate.to_worker(role=...)` |
| Worker | BA | functionon donusu (tool resultu) |

### Yeni agent addme — iki yol

| Request kaynagi | CEO tool'u | User approvali | CEO opinion |
|---|---|---|---|
| PM fark doing, `request_new_agent` atiyor | `team.spawn_agent` | **mandatory** (`budget.request_user_approval`) | proposal forde place receives |
| User directly "X rol add" says | `team.direct_spawn_agent` | **yok** (user already heredi) | mandatory — `ceo_opinion` parametresine is written |

`direct_spawn_agent` budget `single_decision_cap`'i (5000 USD defaulti) or hard block esigini (%95) asacaksa automatic rejects; o in state CEO Path A'ya is forced. Her iki yol da registry'e `requested_by` field ile farkli audit trace leaves (`project_manager` vs `user`).

Worker'lar birbirine directly konusamaz. Backend and Frontend same feature on calisiyorsa BA tarafindan **paralel** iki task halinde verilir, output'lar `knowledge.write_artifact` ile goze gore birakilir, BA karsilikli eslestirir.

## Neden this much sert?

Enterprise-grade bir teamda clean responsibility chain, scope drift prevents. Agentlar da humans like bir expertise alinstantda en good ones — scope outside output uretmelerine permission verirsek:

- Backend developer UI about olmayan "good ideas"what wrapping.
- iOS developer Android'in solving gereken problem kendi uzerine takes.
- Test uzmani sorumlulugu olmayan bir subsystem'de koda mixing.

Katmmeinstantga this kirmizi lines technical olarak enforces: policies.yaml bir role's which tool'u gorecegini clarifies. Prompt'lar responsibility constitution addr.

## Scope checke nadelete works

1. **Tool filtreleme** (technical limit): SDK `allowed_tools`. Worker'lar `delegate.*` doesn't see.
2. **System prompt'ta "never don't do" list** (bilissel limit): her prompt'ta role's reddedecegi seyler bold.
3. **Log'da ihlal tracking**: bir agent owner olmadigi tool'u callmaya kalkarsa SDK rejects, log'a falls.

## Paralel work ornegi

Epic: **"Kredi karti addme akisi"**

BA dekompoze eder:
- `task-a` (uiux_dev) — wireframe + mockup + design tokens
- `task-b` (backend_dev) — POST /cards endpoint, tokenization, ledger entry, PCI scope (bagli: OpenAPI spec uretilecek)
- `task-c` (frontend_dev) — web checkout "Yeni kart" akisi (bagli: task-a + OpenAPI)
- `task-d` (android_dev) — Android "Yeni kart" akisi (bagli: task-a + OpenAPI)
- `task-e` (ios_dev) — iOS "Yeni kart" akisi (bagli: task-a + OpenAPI)
- `task-f` (tester) — API kontrat + web e2e (bagli: task-b, task-c)
- `task-g` (mobile_tester) — UAT Android + iOS (bagli: task-d, task-e)

BA `tasks.create` ile hep acar, her birine `assigned_role` atar. `parent_id` ile epic'e connects.

PM sprint plinstantda paralel serit sees: a -> (b || c || d || e) -> (f, g) -> release gate.

## Release gate

- **tester** web+API for go/no-go opinion verir.
- **mobile_tester** mobile for go/no-go opinion verir.
- BA her iki sinyali collects, PM'e delivery eder.
- PM CEO'ya release note ile together send.

## Permission yukseltme

- Worker BA'ya back donmek hereyebilir (spec belirsiz, blocking bagimlilik). -> `tasks.update(status='blocked', note='...')` + BA'nin sprint review'unda sees.
- BA PM'e donecek? -> spec bolmes netlestiriyorsa `knowledge.write_decision` + PM next turn read.
- PM CEO'ya donecek? -> scope genisledi or kapasite missing -> `team.request_new_agent` or topic "scope change" notuyla `knowledge.write_decision`.
- CEO to you mi? -> her approval kopsusunda `budget.request_user_approval`.
