# Known issues

Point-in-time findings from an initial-setup review (2026-09-13), split into
what was fixed then and what's still open. Update this file as items get
resolved — don't let it go stale the way `README.md`'s API section did.

## Fixed in the initial-setup pass

- **`agent.PriceSource.chart_label` field was missing entirely** while
  `agent/admin.py` (`list_display`, `search_fields`, a fieldset) and
  `agent/services.py::_enabled_price_source_symbol_labels` both referenced
  it. This failed Django's admin system check (`admin.E108`) — `manage.py`
  could not run *at all* (migrate, runserver, any command) until this was
  fixed. Added the field to the model; see `agent/migrations/0001_initial.py`.
- **No migrations were committed for any app** (`agent`, `articles`,
  `dataset` had model code but no `migrations/` directory). `entrypoint.sh`
  ran `makemigrations` on every container start instead — meaning schema
  history wasn't version-controlled and depended on whatever the container
  generated at boot. Generated and committed the initial migrations; the
  entrypoint now only runs `migrate --noinput`.
- **`.env.example` didn't exist**, even though `README.md` instructed
  `cp .env.example backend/.env`. Added a root `.env.example`.
- **`backend/docker-compose.yml` and `frontend/docker-compose.yml` were
  unused duplicates** of the root compose file (nothing referenced them).
  Deleted both.
- **Env var name mismatch**: `docker-compose.yml` fed Postgres
  `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD` while
  `config/settings.py` reads `DJANGO_DB_NAME`/`DJANGO_DB_USER`/
  `DJANGO_DB_PASSWORD` — two names for the same values, easy to set one and
  forget the other and get a backend that can't reach the DB it just
  created. `docker-compose.yml` now treats `POSTGRES_*` as the single source
  and maps it to `DJANGO_DB_*` for the backend container.
- **`backend_media` volume/mount was dead weight**: no `MEDIA_ROOT`/
  `MEDIA_URL` is configured anywhere and no model has a `FileField`/
  `ImageField`. Removed the volume and the `/app/media` mount.
- **Superuser auto-creation used a hardcoded fallback password**
  (`adminadmin`) and ran unconditionally on every container start. Now
  gated on both `DJANGO_SUPERUSER_USERNAME` and `DJANGO_SUPERUSER_PASSWORD`
  being explicitly set, with no fallback password.
- **`README.md`'s "API endpoints" section didn't match the code** — it
  documented `/articles/`, `/articles/ingest/`, `/briefs/current/`,
  `/briefs/headlines/`, `/agent/seeds/`, `/agent/export.csv`, none of which
  exist, and it omitted the `prices`/`cards` apps entirely. Rewrote it
  against the actual `*/urls.py` files.
- **`README.md` listed management commands that don't exist**
  (`add_seeds`, `crawl_loop`) instead of the real ones (`seed_sources`,
  `seed_prices`, `agent_loop`, `run_forever`, `sync_price_feeds`,
  `price_feed_loop`).
- **Dockerfiles ran the backend as root.** Rebuilt `backend/Dockerfile` as a
  venv-builder + final-stage image running the app as a non-root `django`
  user (via `gosu`, dropped in `entrypoint.sh`), matching the pattern used
  in this developer's other Django projects (fgperp, MiyanWA).
- **No dev-mode Docker workflow existed** (no bind mounts, no hot reload).
  Added `docker-compose.dev.yml` as an overlay and a `development` build
  stage in `frontend/Dockerfile`.

## Fixed in the cleanup/restructure pass (same day, follow-up)

- **`core.models.PublishableModel` and `core.viewsets.PublicReadModelViewSet`
  were unused** by any model or view. Deleted both (`core/viewsets.py`
  removed entirely; `core/models.py` now only has `TimeStampedModel`).
- **`agent/services.py` was one ~2700-line `AgentService` class.** Split into
  `agent/services/` (a package) by responsibility, with zero behavior
  change — see `context/conventions.md` for the module map and the rule for
  adding new methods. Verified line-for-line: every method/attribute the
  original class exposed is present exactly once in the new package (checked
  programmatically), `manage.py check` passes, and a real `agent_loop` run
  against Postgres in Docker ingested sources and built cards exactly as
  before.
- **Two real bugs surfaced by the split**, fixed immediately: `scoring.py`'s
  `_is_financially_relevant`/`_relevance_score`/`_extract_relevant_sentences`
  referenced the class by its old name (`AgentService.X`) from inside a
  `@staticmethod` — this only worked because they used to live in the
  `AgentService` class itself in the same module. Converted the first two to
  `@classmethod` and switched the hardcoded name to `cls`. Also removed a
  handful of unused imports the split's mechanical extraction left behind
  (caught with `pyflakes`; see `context/development-workflow.md`).

## Fixed in the review-fixes pass (2026-09-27)

From the code review of that date; plan in
`docs/superpowers/plans/2026-09-27-review-fixes.md`. Migrations were reset
to a fresh `0001_initial` per app (data was disposable).

- **Every scheduled run started the pipeline twice**: a `post_save` signal on
  `AgentRun` started a second thread for the run the pipeline had just
  created. Signal deleted.
- **`seed_sources` overwrote `AgentConfig` on every container start.** It now
  only sets defaults when it creates the config.
- **Price sync slept `rate_limit_seconds` per source** (~320s per sync with
  the seeded sources). It now skips a source until it is due.
- **Run-forever lived in per-gunicorn-worker threads** (random status,
  stop hitting the wrong worker, double loops, killed on worker restart).
  Now a separate `agent` container (`run_forever`) controlled by DB flags,
  with an `AgentWorker` heartbeat. Duplicate `/agent/status|run|run-forever/*`
  routes removed; `/agent/control/*` remains.
- **LLM budget spent on open cards first**, so final hourly briefs got
  fallback text. Finalization now runs first, and the budget is a daily cap
  (`llm_daily_request_budget`, default 200) with token usage recorded on
  `AgentRun`.
- **Rolling 24h "day" cards** (24 overlapping finalized cards per day) replaced
  by calendar-day cards; `/last24h/` removed.
- **Aftermath queue starvation** by old/data-less cards: candidates are
  limited to the last 7 days and cards with tracked assets.
- **Article slugs changed with every open-card refresh.** Now fixed at
  creation; side articles of open cards are refreshed.
- **`/briefs/` listed every hourly brief before any daily one.** Now ordered
  by period end.
- **Broken/dead endpoints and models**: `cards` app (detail always 404),
  `dataset.RawCandle` (never written; `/prices/.../latest/` always null),
  `seed_prices` + CSV fixtures, legacy and general-news seed sources,
  `LLMClient.embed`, `_load_hourly_records`, `AgentRun.objective` — removed.
  `AssetCandle` is now unique per series+minute.
- **Price providers**: yfinance was asked for symbols it can't serve and ccxt
  for a market Binance doesn't list, all errors swallowed. Now explicit
  symbol maps, bar timestamps, errors logged and surfaced as
  `price_sync_errors` log events. Also fixed `django.utils.timezone.utc`
  (removed in Django 5), which crashed RSS price items with a date.
- **LLM client**: per-run cache that never hit removed; non-object JSON
  rejected; the hard-coded ArvanCloud auth hack is now
  `AgentConfig.llm_auth_scheme`.
- **Security/ops**: backend refuses to start with DEBUG off and a
  placeholder secret; `llm_base_url` is read-only via the control API; RSS
  parsed with `defusedxml`; control token in `sessionStorage`; daily
  retention pruning; frontend image builds with `npm ci`.
- **Frontend**: SSR restored (it was `server: false` everywhere, and the
  SSR API URL env var was only read at build time); polling replaced by SSE;
  infinite scroll dedups overlapping pages; sitemap/RSS/robots routes.
- **Near-duplicate stories across sources** are collapsed by title
  similarity when a period's records are loaded.

## Open — flagged, not changed

- **No paid/maintained price provider yet.** yfinance and Binance (via ccxt)
  are free but unofficial or geo-restricted; pick a provider with an SLA
  before relying on prices.
- **No CI** (tests exist now: `python manage.py test`).
- **Admin dashboard (`/agent-control`) still polls.** `EventSource` can't
  send the control token header; moving it to SSE needs a cookie or
  query-string token.
- **No structured (JSON) logging** yet.
- **Economist agent / `MemoryState`** remain behind
  `AGENT_ENABLE_ECONOMIST_AGENT=false` with no tests.
- **One worker replica assumed.** Running two `agent` containers would run
  two loops; add a Postgres advisory lock before scaling it.
