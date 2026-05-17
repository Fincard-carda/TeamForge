# Servis Hesabi — Anthropic Admin API

## Neden separate bir key?

TeamForge `analytics.usage_check`, `cost_report`, `usage_report` tool'lari
Anthropic'in **Admin API**'sini calls. This endpoint'ler **only admin
key** (sk-ant-admin01-...) ile acilir. Standart API key (sk-ant-api03-...) or
workspace key this endpoint'lere erisemez — 403 drecommend.

Anthropic'in existing auth modelinde **this spesifik endpoint'ler for "servis
hesabi" alternatifi none**. Workaround: admin key'i bir servis hesabi like
yonet — dedicated, narrow permission usagei, audit'li, rotation'li.

## Provisioning adimlari (5 minute)

1. **Personal admin key'inden separate bir tane create:**
   - Tarayicidan https://console.anthropic.com/settings/admin-keys
   - "Create key" -> Name: `teamforge-usage-monitor`
   - **Personal admin key'ini kullanma** — source tracking (kim what yapti) for
     this servis hesabini separate tut.

2. **.env'e add:**
   ```bash
   ANTHROPIC_ADMIN_API_KEY=sk-ant-admin01-...
   ```
   (.env never git'e never committed; .gitignore'da must be.)

3. **Optional — secret manager kullan:**
   1Password CLI ornegi:
   ```bash
   # .env'de bu's instead of
   # ANTHROPIC_ADMIN_API_KEY=$(op read "op://teamforge/admin-key/value")
   ```
   AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault da kullanilabilir.
   Personal laptop'unda plaintext bulundurmama avantaji.

4. **Restart:**
   ```
   python orchestrator.py
   ```
   CEO/CFO now `analytics.usage_check(days=30)` callinca real veri receives.

## Defensive layers (analytics.py)

Admin key teoride yikici operations (workspace silme, uye addme) yapabilir,
but TeamForge kod tabani **3 sert kati guard** ile this blocking:

### 1. Path allowlist

`tools/analytics.py` forde `_ALLOWED_ADMIN_PATHS` setine only 3 endpoint
ekli:

- `/organizations/cost_report`
- `/organizations/usage_report/messages`
- `/organizations/usage_report/claude_code`

Baska bir path'e call yapilmaya kalkilirsa kod-levelsinde `RuntimeError`
firlatir. Yarin one yanlislikla bir POST endpoint callsi addrse, anik
pskipr. Personal admin key'inle "all admin" gucu var olsa bile, this kod tabani
from there SADECE 3 read-only endpoint kullanir.

### 2. Audit log

Her call `state/admin_api_audit.json` fore falls:
```json
{
  "ts": "2026-05-14T21:32:34",
  "path": "/organizations/cost_report",
  "method": "GET",
  "params_summary": "starting_at=2026-04-14...,ending_at=2026-05-14...",
  "source": "agent",
  "role": "ceo",
  "status": "OK",
  "http_status": 200
}
```

Reddedilen calls da kaydedilir (`status: REJECTED_ALLOWLIST`,
`REJECTED_RATE_LIMIT`, `REJECTED_NO_KEY`).

Sahibe report herersen: `delegate.analytics.audit_log(last=20)` —
en yeni 20 admin API call listr. Kim/what zaman/which endpoint'e
call yapmis, audit trace open.

### 3. Rate limit

Hourly 60 call upper limiti. Cache 5 minute being for normal usage
ortalama 1-3 call/hour happens. Anormal crash (mesela bir agent loop'a
girip 200 call don't do) `REJECTED_RATE_LIMIT` ile durur, audit'e falls.

## Rotation

3 ayda bir:
1. Console > Settings > Admin Keys > "teamforge-usage-monitor" select > **Delete**
2. Yeni key create (same isimle)
3. `.env`'i currentle
4. Orchestrator restart

Reason: key compromise'e against upper limit; ekibe yeni one katildiysa, ayrildi
mi, hidden ifsa olduysa automatic mitigation.

## Anthropic'in resmi tuallu

- [Admin API overview](https://docs.anthropic.com/en/api/administration-api)
- [Usage & Cost API](https://docs.anthropic.com/en/api/usage-cost-api)
- [API Console Roles](https://support.anthropic.com/en/articles/10186004)

Workspace_billing role Console UI'da gormeyi destaddr but programatik
accessm for **admin key remains single yol** (May 2026 itibariyla).

## Emergency

Admin key sizdiysa:
1. Console > Settings > Admin Keys > select > **Revoke**
2. Yeni key create, `.env`'i currentle, restart
3. Audit log'u (`state/admin_api_audit.json`) check et — anormal call var mi
4. If anormal usage if exists Anthropic support'a write

This sheremde admin key bir "servis hesabi" like davranir — read-only, audit'li,
rate-limit'li, and personal key'inden separate happens.
