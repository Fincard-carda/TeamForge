# Contributing to TeamForge

Thanks for taking the time to contribute. This project is small and moves fast,
so a few notes will save us both time.

## Development setup

```bash
git clone https://github.com/Fincard-carda/TeamForge.git
cd teamforge
python -m venv .venv
source .venv/bin/activate           # Linux/macOS
.venv\Scripts\activate              # Windows
pip install -r requirements.txt
pip install ruff pytest             # dev tools (optional)
cp .env.example .env                # then set ANTHROPIC_API_KEY
python -m orchestrator
```

## Branch and commit conventions

- Branch off `main`. Name branches `feat/<short-name>`, `fix/<short-name>`,
  or `docs/<short-name>`.
- Commit messages: imperative mood, one line summary plus optional body.
  Example: `Add dashboard real_cost endpoint for live spend display`.
- Squash before merge when feasible.

## Code style

- Python: PEP 8 + ruff (`ruff check`). Type hints encouraged but not required
  on internal helpers.
- Keep functions small. Heavy logic gets a docstring explaining *why*.
- Avoid premature abstractions; concrete first, generalize when there are
  two callers.

## Tests

Add at least one smoke test for new modules. Existing tests live under
`tests/`. If you change tool definitions in `tools/*.py`, exercise them with a
short asyncio script that runs the tool and prints its output.

## Running the budget monitor in development

Set `TEAMFORGE_BUDGET_MONITOR=off` if you're iterating fast and don't want
periodic Admin API calls in the background.

## Reporting security issues

Please do NOT open a public issue for security vulnerabilities. Email the
maintainer directly (see commit history for contact info).

## What we welcome

- New role templates, sample project descriptions, and prompt improvements
- Better Setup wizard UX (frontend or backend)
- Additional tool wrappers (Slack, GitHub, GDrive integrations)
- Performance improvements (caching, async fanout)
- Documentation and examples

## What needs careful discussion first

Open an issue before working on:

- Changes to the Admin API defensive wrapper (allowlist, rate limit)
- Anything that modifies the budget threshold semantics
- Breaking changes to the `prompts/*.md` schema

These touch security-sensitive flows; let's align on intent first.
