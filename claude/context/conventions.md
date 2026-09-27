# Conventions

- **New models** extend `core.models.TimeStampedModel` (or write a plain
  model if timestamps genuinely don't apply) — don't redeclare
  `created_at`/`updated_at`.
- **Settings come from `os.getenv(...)` with an inline default** in
  `config/settings.py` — no separate `settings/dev.py`/`settings/prod.py`
  split. Add new config the same way: one `os.getenv("DJANGO_X", "default")`
  line, not a new settings module.
- **Two different places hold config, on purpose:**
  - `.env` / environment variables — infra concerns: DB creds, secret key,
    allowed hosts, CORS/CSRF origins, ports.
  - `AgentConfig` (a DB row, `agent/models.py`) — runtime agent behavior:
    LLM API key, timeouts, token budgets, control-token TTL. Edit it via
    Django admin or `PUT /api/agent/config/`, not `.env`. Don't add an
    env var for something that's really an `AgentConfig` field, and vice
    versa.
- **Migrations are committed.** `backend/*/migrations/` is real, checked-in
  history (reset to a fresh `0001_initial` per app on 2026-09-27 while data
  was still disposable — see `decisions/known-issues.md`).
  Run `python manage.py makemigrations <app>` locally and commit the
  generated file whenever you change a model — don't rely on the container
  regenerating migrations at startup; it no longer does.
- **API style: DRF `APIView` everywhere** (`agent/`, `articles/`, `prices/`),
  with serializers where one exists. Public views set
  `authentication_classes = []` / `permission_classes = []`. The one
  exception is `articles/stream.py`: SSE endpoints are plain async Django
  views returning `StreamingHttpResponse` — DRF doesn't stream. Payload
  builders (`last_hour_payload`, `briefs_payload`, `article_payload` in
  `articles/views.py`) are shared by the REST views and the streams, so the
  two can't drift.
- **`agent/services/` is a package of mixins composing one `AgentService`
  class** (`agent/services/service.py`), not several independent services —
  every method still runs with the full `AgentService` as `self`, so any
  mixin can call any other mixin's method or the shared config/constants in
  `base.py`'s `AgentServiceCore`. Module map, by responsibility:
  - `base.py` — dataclasses, `get_config()`, class-level constants,
    `__init__`/`close`/`run()` (the top-level orchestration entry point).
  - `fetching.py` — RSS/API source fetching, item parsing/normalization,
    dedup, raw storage.
  - `cards.py` — Card/period lifecycle: loading raw records for a window,
    upserting `Card`/`CardArticle`/`CardAsset`.
  - `content.py` — LLM article/brief composition, prompt building, text
    cleanup.
  - `scoring.py` — heuristic + LLM-assisted relevance/importance scoring.
  - `budget.py` — `AgentLogEvent` writing and the LLM request budget (a
    daily cap, `AgentConfig.llm_daily_request_budget`, counted from
    `AgentRun.llm_requests`).
  - `runtime.py` — two halves: control functions for web processes
    (`request_start`/`request_stop`/`request_pause`/`request_resume`/
    `request_run_once` only write `AgentConfig` flags; `worker_status()`
    reads the `AgentWorker` heartbeat row), and `run_worker()`, the loop run
    by `manage.py run_forever` in the separate `agent` container. Never
    start agent work from a web process or a model signal.

  Add a new method to whichever mixin already owns that responsibility, not
  a new top-level abstraction. If a method doesn't fit any existing mixin
  cleanly, that's worth a deliberate conversation, not a silent new file.
- **The `/api/agent/control/*` endpoints use a separate auth scheme**
  (`agent/control_auth.py`: a shared password → signed, TTL'd token in the
  `X-Agent-Control-Token` header, checked by `agent/permissions.py`'s
  `HasAgentControlToken`), independent of Django's session/user auth. Don't
  route these through `request.user`-based permissions.
- Keep `README.md`'s "API endpoints" list in sync with the actual
  `*/urls.py` files when you add/rename/remove a route — it had drifted
  significantly from the real routes before this pass.
