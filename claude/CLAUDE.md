# NousNews — Claude Entry Point

News aggregation platform: a Django REST backend runs a crawler/LLM "agent"
pipeline that turns configured sources into articles, briefs, and price
series; a Nuxt 3 frontend renders them. Docker Compose for both dev and
prod. This file is a map, not the documentation itself — read the linked
file for the area you're touching before making changes.

## Where things live

- `architecture/overview.md` — start here for any non-trivial task: repo
  layout, service topology, what each backend app owns, data flow.
- `context/conventions.md` — project-specific rules not obvious from the
  code alone (config split, migration discipline, API style per app). Read
  before adding a model, endpoint, or config value.
- `context/development-workflow.md` — how to run the stack (Docker and bare
  metal) and what to check before calling a change done.
- `decisions/known-issues.md` — what was fixed in the initial setup pass
  (2026-09-13) and why, plus what's still open. Check this before "fixing"
  something that may already be a known, deliberate tradeoff — and before
  assuming something works, since several things silently didn't until this
  pass (see the migrations/`chart_label` entries).

## Engineering rules

1. **Inspect before abstracting.** Search for an existing model, view, or
   composable that already does what you need before adding a new one —
   `core.TimeStampedModel` for timestamps, the app matching your data
   (`articles`/`dataset`/`agent`/`prices`/`cards`) before a new one.
2. **Migrations are committed, not generated at runtime.** Run
   `makemigrations` locally and commit the file whenever you change a model.
   The container no longer runs `makemigrations` on startup — see
   `decisions/known-issues.md` for why that was fragile.
3. **Verify after every change.** There's no test suite and no CI yet (see
   `decisions/known-issues.md`) — you're the only check that runs. At
   minimum: `python manage.py check`,
   `python manage.py makemigrations --check --dry-run`, and `pyflakes .`
   (catches unused imports/undefined names — it caught two real bugs during
   the `agent/services` split, see `decisions/known-issues.md`). If you
   touch `agent/services/`, exercise the actual crawl/LLM path
   (`python manage.py agent_loop` or `/api/agent/run/`), not just the system
   check.
4. **Stay in scope.** Touch only what the task needs. `agent/services/`'s
   mixin-per-file split (see `context/conventions.md`) is the current
   deliberate shape, not an invitation to reshape further unasked.
5. **Review your own diff before finishing.** Read `git diff` and confirm
   every changed line is intentional and in scope.
6. **Update project knowledge before finishing.** If your change makes
   `architecture/overview.md`, `context/conventions.md`, or
   `decisions/known-issues.md` inaccurate — a renamed endpoint, a new env
   var vs. `AgentConfig` field, a fixed known issue — update just the
   affected lines. If a route changes, also update `README.md`'s "API
   endpoints" section; letting that drift from the code is exactly what
   happened before this pass.
