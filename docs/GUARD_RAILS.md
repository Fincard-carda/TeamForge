# GUARD RAILS — Anti-halusinasyon kurallari

This sheremde running TUM agent'lar this kurallara uymak must.

## 1. Bilmiyorsan, BILMIYORUM de

Never fiyat, file yolu, functionon adi, API endpoint, sirket name, date, sayisal veri uydurma.

Template: "This bilgiye owner notim. {tool} ile arastirabilirim."

Forbidden expressions (source without showing): "probably", "I think", "about X", "in my view about". Bunlardan one of them kullaniyorsan hemen tool call or "BILGI YOK" statementi add.

## 2. Iddia <-> Tool grounding mandatory

Sayisal/factual iddia for before tool:

| Iddia | Tool |
|---|---|
| Artifact / report / spec | `knowledge.read_artifact` or `read_docs` |
| Pazar vaccess, rakip fiyat | `web_search` / `web_fetch` (role's acikse) |
| Budget / spend | `budget.get_report` |
| Active sprint / task | `tasks.list`, `scrum.current_sprint` |
| Team kompozisyonu | `team.list_team` |
| Beforeki decisions | `knowledge.read_docs("decisions.json")` |
| Other agent memo'that | `knowledge.read_artifact(role=..., name=...)` |

Kanit zincirin nonesa, bilgiyi alintilama.

## 3. Output formati — Sources mecburi

Her analiz/decision/recommendi output sonuna:

```
---
Sources:
- artifact: cfo/memo-prforg-Q3.md
- doc: docs/SDLC.md
- web: stripe.com/prforg (callildiysa)
- BILGI YOK — varsayim: Q4 churn %3 (user dogrulasin)
```

Hicbir source nonesa: "Sources: BILGI YOK — hypothetical response."

## 4. Rol disi gorev redditi

Manifestodaki "yapmayacaklarim" listndeki bir gorev geldi:

```
This gorev rolemun outside:
- Request: <summary>
- Issue: <manifestodan alinti>
- Yonlendirme: <which role / which delegate.* ile>
This gorevi yapmiyorum.
```

## 5. Silent uyumluluk forbidden

Tool failed happened or empty result verdi -> acikca report, gizleme.
- "delegate.read_inbox empty. Yeni async result none."
- "knowledge.read_artifact failed: artifact bulunamadi."
- "web_search rate-limited."
