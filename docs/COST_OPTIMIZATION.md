# Cost Optimization Rehberi

## Existing defenses

| Katman | Savings | Activeligi |
|---|---|---|
| Prompt caching (5dk default) | ~%30-50 | Automatic |
| Prompt caching (1h opt-in) | ~%50-70 | `.env`: `ENABLE_PROMPT_CACHING_1H=1` |
| Prompt slimming | ~%60 (30KB→14KB) | Kalici (runtime.py) |
| Concurrency limit | Process crashsi engellenir | `TEAMFORGE_MAX_CONCURRENT=4` |
| Defensive admin API (rate limit) | Analytics endpoint rate cap | analytics.py |

## Cache state izlemek

CEO/CFO always:
```
analytics.usage_check(days=7)
```

Output inside `cache_read` token count `uncached_input`'a orunderstand:
- `cache_read / total_input > 0.5` → cache hot, good in state
- `< 0.3` → cache miss high, sessions kisa or prompt'lar siklikla changing
- `~0` → caching kapali olabilir (`DISABLE_PROMPT_CACHING` env'i check et)

## 1-hourly vs 5-minute cache farki

Bizim system **many agent spawn doing**:
- CEO ana mesaja response verirken PM/CFO'ya delegation
- PM kendi turn'unde BA'ya, BA worker'lara
- Async chain'de inbox check'ler

This paralel and fast iletisimde 5dk cache yetersiz kalabilir. 1h ile:
- Bir Q3 review the session 30dk surse bile prompt'lar sicak
- Async job 10dk next inbox'a dustuday cache hala valid
- Brief load + system_prompt again tokenize edilmez

**Cost trade-off:** Cache creation tokens %25 more expensive but cache_read %90 discount. Net positive if 2+ times cache hit if exists (always happens).

## Next steps (not yet not done)

1. **Model tiering** — Haiku worker'lar for
2. **Tool description audit** — 60 tool description kisaltma
3. **max_turns sikilastir** — 40 → 15-25 per role
4. **Tool result truncation** — `knowledge.read_artifact` default max_chars

## ENABLE_PROMPT_CACHING_1H detail

Set: `.env` filesinda `ENABLE_PROMPT_CACHING_1H=1`

Disable specific model: `DISABLE_PROMPT_CACHING_HAIKU=1` (default disable not; only debug for)

Force 5dk default: `FORCE_PROMPT_CACHING_5M=1` (our system for unnecessary)
