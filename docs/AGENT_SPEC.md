# Yeni Agent / Feature Addme Rehberi

This team layered inşa was done: bir role's behavior degistirmek for kod writing ihtiyacin neredeyse none.

## Senaryo 1 — Bir role's count degistirmek

`config/team.yaml` forde o role's `count:` valueini set.

More next runmada orchestrator `ensure_baseline_registry()` functiononu baseline teami filling SEED'lere doesn't touch — yani already bir team if exists seed addmez. Dynamic to add istiyorsan CEO over late or `state/team_registry.json`'u elle edit.

Fast reset:
```bash
rm state/team_registry.json
python orchestrator.py
```

## Senaryo 2 — Bir role's kisiligini/permissionnligini degistirmek

`prompts/<role>.md` file edit et. Change again startinca active happens (prompt her in delegation from disk is read).

## Senaryo 3 — Bir role's permission (tool) degistirmek

`config/policies.yaml`'da o role's `tools:` listni edit. Orn. frontend_dev'e `tasks.create` permissionsi vermek want to listden remove.

## Senaryo 4 — Yeni bir rol to add

Example: `devops_engineer` addyelim.

1. **Prompt**: `prompts/devops_engineer.md` create.
2. **Team config**: `config/team.yaml` altina add:
   ```yaml
   devops_engineer:
     count: 1
     model: ${CLAUDE_MODEL}
     max_turns: 40
     profile: "Kubernetes, Terraform, ArgoCD..."
   ```
3. **Policy**: `config/policies.yaml`'a:
   ```yaml
   devops_engineer:
     delegate_to: []
     writes_code: true
     tools: [tasks.list_mine, tasks.update, knowledge.read_docs, knowledge.write_artifact, code.write_file, code.read_file]
   ```
4. **Runtime map**: `tools/runtime.py` inside `PROMPT_FILES` sozlugune line add:
   ```python
   "devops_engineer": "devops_engineer.md",
   ```
5. **Delegation**: BA'nin this role gorev verebilmesi for `tools/delegation.py` inside `to_worker.allowed` setine `"devops_engineer"` add.
6. **Budget**: `config/budget.yaml` altindaki `agent_costs_monthly` kismina yeni role's costini add.

This until. CEO -> PM -> BA -> devops_engineer akisi automatic works.

## Senaryo 5 — Yeni bir tool (MCP tool) to add

Example: Jira entegrasyonu.

1. `tools/jira.py` create:
   ```python
   from claude_agent_sdk import tool

   @tool("create_issue", "Jira issue createur", {"summary": str, "description": str})
   async def create_issue(args: dict) -> dict:
       # Jira REST API callisi
       return {"content": [{"type": "text", "text": f"JIRA-123 createuldu"}]}

   JIRA_TOOLS = [create_issue]
   ```
2. `tools/runtime.py` inside `_collect_tools_for_role` functiononuna add:
   ```python
   from . import jira as jira_tools
   _add("jira", jira_tools.JIRA_TOOLS, ["create_issue"])
   ```
3. `config/policies.yaml`'da relevant role's `tools:` listne `jira.create_issue` add.
4. `orchestrator.py` CEO registry'sine de yansit (hereyen roles for).

## Senaryo 6 — Model degistirmek

Rol per `config/team.yaml` -> `model:` field change. Upper level roles for Opus, worker roles for Sonnet typical bir pattern. `CLAUDE_MODEL` and `CLAUDE_MODEL_LEAD` env variables de you can set.

## Senaryo 7 — Dynamic agent talebini to force (kapasite stresi)

CEO this you herersen for doesn't do; PM'den request receiving needed. Scenario quickly trigger etmek for:

```
you> PM'e say: backend tarafinda kapasite many yetersiz, 2 sprint more gecikeceksiniz, yeni agent hereyin.
```

This request CEO'ya bir next turde comes, CEO to you proposal sunar.

## Issue giderme

- **"Workspace still starting"** — first run ise API key'i dogrula, Claude Code CLI kurulu mu check et (`claude --version`).
- **Agent empty response veriyor** — `logs/orchestrator.log` fore bak, tool calllari there. max_turns yetersiz olabilir.
- **Approval kopsusu fell** — ApprovalBroker single instance, orchestrator closeilip acilmali. Half remaining request state'e isn't written, knowingly this way.
- **Budget summaryi real costi doesn't show** — `agent_costs_monthly` simulasyon rakami; real usage for Anthropic dashboard'u kullan.
