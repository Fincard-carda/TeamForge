# TeamForge Agent Team — Mimari

## Hedef

You bir CEO ile konusursun. CEO high levelli stratejiyi taking, technical yonetimi PM'e, task distribution BA'ya, application expert to agents delegates. Budget, risk and dynamic team scaling CEO on side.

## Katmanlar

```
 +-----------------------------------------------------------+
 |  orchestrator.py                                          |
 |    - stdin dongu (you)                                    |
 |    - ApprovalBroker (user approval kopsusu)              |
 |    - ClaudeSDKClient(CEO)  — kalici session                |
 +-----------------------------------------------------------+
              |                                ^
              v                                |
 +-----------------------------------------------------------+
 |  CEO (ClaudeSDKClient, persherent)                        |
 |    tools: budget.*, team.*, delegate.to_pm,               |
 |           knowledge.*                                     |
 +-----------------------------------------------------------+
              |  delegate.to_pm
              v
 +-----------------------------------------------------------+
 |  PM (claude_agent_sdk.query, stateless per call)          |
 |    tools: delegate.to_ba, team.request_new_agent,         |
 |           tasks.*, knowledge.*                            |
 +-----------------------------------------------------------+
              |  delegate.to_ba
              v
 +-----------------------------------------------------------+
 |  BA (stateless)                                           |
 |    tools: delegate.to_worker, tasks.*, knowledge.*        |
 +-----------------------------------------------------------+
              |  delegate.to_worker(role=...)
              v
 +-----------------------------------------------------------+
 |  Workers (Android, iOS, UI/UX, Frontend, Backend, Test)   |
 |    tools: tasks.list_mine/update, knowledge.*, code.*     |
 +-----------------------------------------------------------+
```

## Neden CEO kalici, others stateless?

- **CEO kalici** ki konusma history korusun. Useryla continue eden ozel sohbete, budget datecesine, uzun vadeli decision suregine owner olsun.
- **PM/BA/worker'lar** stateless — her delegation yeni bir session acar. Kalici baglam:
  - `state/tasks.json` — task board
  - `state/decisions.json` — ADR tarzi decision gecmisi
  - `docs/specs/` — BA spec'leri
  - `artifacts/` — specialists outputs

This tasarim hem costi dusurur (her call minimum context), hem de testi kolaylastirir.

## Ileti akisi

### Simple gorev akisi

1. You CEO'ya: "Checkout page 3DS2 ile uyumlu hale getir."
2. CEO -> delegate.to_pm("Checkout'ta 3DS2 hedefi, 2 sprint plunderstand.")
3. PM -> tasks.create(...) ile epic createur, delegate.to_ba('This epic'i tasklere bol and at.')
4. BA -> tasks.create(subtask) + delegate.to_worker(role='frontend_dev', ...) + delegate.to_worker(role='backend_dev', ...) vs.
5. Workers kodu yazar, tasks.update('done') ile closeir, artifact yazar.
6. Test agentlari release kapisinda kosar.

### Yeni agent talebi — iki akis

**Path A — PM'den gelen (approvalli)**

1. PM fark eder: backend solo doesn't fit.
2. PM -> team.request_new_agent(role='backend_dev', count=1, reason='...', impact='...', urgency='high')
3. CEO (bir next turunda) -> team.evaluate_new_agent_request -> cost/risk/ROI text receives.
4. CEO -> budget.request_user_approval(title, summary, details=JSON)
5. Orchestrator to you: "ONAY GEREKIYOR: Yeni Backend Dev — +3400 USD/ay, risk:low, urgency:high"
6. You: "approve" (or "reject" or "2 instead of 1")
7. Broker CEO'nun tool call response olarak resolve eder.
8. CEO -> team.spawn_agent(request_id=...) -> yeni agent registry'ye addnir, PM'e haber.

**Path B — User direkt talebi (CEO only opinion notifies)**

1. You: "Bir tane more backend dev add."
2. CEO -> budget.get_report -> existing state check eder.
3. CEO to you bir paragrafta opinion yazar ("in my view simdi zamani not, because X" or "approval veriyorum, Y because of"). But this is an opinion, approval not — you already request ettin.
4. CEO -> team.direct_spawn_agent(role, count, user_request_summary, ceo_opinion) ile registry'e addr.
5. Tool only budget guard'larina takilirsa rejects: `single_decision_cap` (5000 USD) or hard block (%95 budget). O in state CEO Path A'ya is directed.

Her iki yol da registry'e farkli audit trace leaves (requested_by: `project_manager` vs `user`).

### Budget tavani akisi

1. CEO her tool callsindan next budget state eye in front amount.
2. Soft warning (%75): CEO to you proactive warning yazar.
3. Hard block (%95): CEO yeni agent/spend for approval almayi enforces.

## Esnekligin limitlari

- Hierarchy **policies.yaml** ile is defined. Bir role's which tool'u gorecegi oradaki `tools:` listyle is determined.
- Bir agent kendi izinsiz tool'u callamaz — SDK `allowed_tools` list filter eder.
- Yeni bir rol to add for: `prompts/<role>.md` + `policies.yaml`'da blok + `team.yaml`'a count + `tools/runtime.py`'da PROMPT_FILES to the map line.

## Gelisim noktalari (ileride)

- **Persherent nested agents**: PM/BA'yi da `ClaudeSDKClient` ile kalici tutmak — cost karsiligi hafizayi korur.
- **Agent -> agent mesaj kuyrugu**: sync delegation instead of event-driven task picking.
- **Rol based rate-limit**: runilan eszamanli agent count limitla.
- **Cost ledger'i API usageiyla eslesir**: simulasyon instead of real usage.
- **MCP server olarak outer integrations**: Jira, GitHub, Figma API, Sentry — her one of them separate mcp_server olarak bagla.
