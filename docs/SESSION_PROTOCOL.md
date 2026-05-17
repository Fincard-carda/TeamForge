# Session Close & Resume Protokolu

## Session hayati

1. **Acilis:** Beforeki brief'i `brief.load` ile read. Prompt'unda "[RESUME]" tag if exists, "In-progress" and "Next steps" maddelerinden continue et.
2. **Work:** Normal akis.
3. **Kapanis:** `brief.save` ile where kaldigini save.

## Guvenli closema (cascade)

1. Before lower katmana delege et (yoneticiysen)
2. Kendi `brief.save` call
3. Cagrana kisa report ver

## Built-in tool forbidden

`Edit, Write, Read, Bash, Glob, Grep, Skill, Task, TodoWrite, MultiEdit, NotebookEdit` this sheremde kapali. Cagirsan reddedilirsin. File operations for only MCP tool'lari (`config.*, code.*, knowledge.*, brief.*, tasks.*`).

`WebSearch/WebFetch` only policy ile aciksa accesslebilir.
