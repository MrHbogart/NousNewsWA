# Review Fixes + SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every issue from the 2026-09-27 code review and push live data to readers over Server-Sent Events instead of polling.

**Architecture:** The agent moves out of the web process into its own `agent` compose service (`manage.py run_forever`) whose control/state lives in the DB (`AgentConfig` flags + an `AgentWorker` heartbeat row). The backend switches to ASGI (gunicorn + uvicorn workers) so one worker can hold many SSE connections; a single per-process poller watches a cheap "content version" and fans updates out to all SSE clients. Nuxt renders pages server-side again and upgrades to SSE on the client.

**Tech Stack:** Django 5.0 + DRF, uvicorn worker, Postgres 15, Nuxt 3, native `EventSource`.

**Spec:** Review report in conversation (2026-09-27), sections 1–7.

## Global Constraints

- No data migration: existing data is disposable. Regenerate each app's migrations as a fresh `0001_initial`.
- No CI.
- Server→reader live data goes over SSE (`text/event-stream`), not polling. Admin dashboard (`/agent-control`) keeps polling. It is token-authenticated, and `EventSource` can't send headers.
- No new frontend dependencies. Backend adds only `uvicorn[standard]` (ASGI server) and `defusedxml`.
- Verification per task: `manage.py check`, `makemigrations --check`, `pyflakes`, `manage.py test` (in the `nousnews-test` docker image).

## Review Focus

- SSE client disconnects: the stream generator must exit on cancel and not leak the poller.
- Agent worker restarted mid-run: the heartbeat goes stale and status reports `running: false` within 30s.
- `run-once` requested while the worker is disabled: it still runs exactly once.
- Price source with `rate_limit_seconds=300`: sync returns immediately and the source is skipped until due.
- Open hour card refreshed with a new title: the article slug stays the same.

---

### Task 1: Pipeline correctness (review #1, #2, #3, #5, #14)

**Files:** `agent/signals.py` (delete), `agent/apps.py`, `agent/management/commands/seed_sources.py`, `agent/price_sync.py`, `agent/services/base.py`, `config/settings.py`, delete `agent/management/commands/agent_loop.py`, `articles/management/commands/price_feed_loop.py`

- [ ] Delete `signals.py` and the `ready()` import. Nothing may auto-start a run on `AgentRun` save.
- [ ] `seed_sources`: apply the `config_updates` dict only when `AgentConfig` was just created (`get_or_create` → `created`).
- [ ] `price_sync._sync_from_price_sources`: remove `time.sleep`. Skip a source when `last_fetched_at + rate_limit_seconds > now`.
- [ ] `AgentServiceCore.run`: order is fetch → finalize hourly → finalize aggregates → aftermath → refresh current hour (open card last, so permanent cards get the LLM budget first).
- [ ] Delete `agent_loop` and `price_feed_loop` (superseded by the `run_forever` worker in Task 2).
- [ ] Tests: creating a running `AgentRun` does not call `start_agent_async`. Re-running seed keeps a changed `loop_interval_minutes`. A 300s-rate-limited source that was fetched 10s ago is skipped with no sleep.

### Task 2: Agent worker as its own service with DB state (#4)

**Files:** `agent/models.py` (+`AgentWorker`, `AgentConfig.run_forever_paused`, `AgentConfig.run_once_requested`), `agent/services/runtime.py` (rewrite), `agent/management/commands/run_forever.py`, `agent/views.py`, `agent/urls.py`, `agent/admin.py`, `docker-compose.yml`, `backend/entrypoint.sh`, `frontend/pages/agent-control.vue` (only if field names change)

**Interfaces:**
- `runtime.request_start() / request_pause() / request_resume() / request_stop() / request_run_once() -> dict` write flags to `AgentConfig` and return `worker_status()`.
- `runtime.worker_status() -> dict` has keys `running` (heartbeat < 30s old), `state`, `paused`, `current_action`, `started_at`, `last_heartbeat_at`, `last_news_run_at`, `last_price_sync_at`, `iterations`, `last_error`.
- `runtime.run_worker(max_iterations: int | None = None, sleep=time.sleep)` is the loop, and it is testable.
- `AgentWorker` is a singleton row (`pk=1`) with fields `state`, `current_action`, `started_at`, `heartbeat_at`, `last_news_at`, `last_price_at`, `iterations`, `last_error`.

- [ ] Loop per tick: reload config. If `run_once_requested`, clear it and run news once. Otherwise, if enabled and not paused, run news/price on their intervals. Write the heartbeat row. Price and news exceptions go to `last_error` and a log event.
- [ ] Control endpoints only write flags. Remove the duplicate `/agent/status|run|run-forever/*` routes and keep `/agent/control/*`, `/agent/config/`, `/agent/logs/`.
- [ ] Compose: new `agent` service (same image, `command: python manage.py run_forever`, `SKIP_SETUP=true`, depends on healthy backend). The entrypoint skips migrate/collectstatic/seed when `SKIP_SETUP=true`.
- [ ] Admin: drop the `start_run_forever_async` action and use `request_start`.
- [ ] Tests: `run_worker(max_iterations=1)` with `run_once_requested=True` while disabled runs the service once and clears the flag. A paused worker doesn't run news. A heartbeat older than 30s reports `running: false`.

### Task 3: Card lifecycle (#10, #11, #12)

**Files:** `agent/services/cards.py`, `agent/services/base.py`, `articles/views.py`, `articles/urls.py`

- [ ] Remove the rolling 24h card (`_refresh_current_24h_card`, `_current_rolling_day_window`) and `_finalize_stale_open_cards`. Add `Card.TIMEFRAME_DAY` to `_finalize_due_aggregate_cards` (calendar days). Day slug is `day-%Y-%m-%d`.
- [ ] Remove the `/last24h/` endpoint (the frontend doesn't use it).
- [ ] Aftermath candidates: only cards with `period_end >= now - 7 days` that have at least one asset, so old or data-less cards can't block the queue.
- [ ] `_upsert_card_articles`: the slug is set only when the main article is created, never rewritten. For an open card, replace side articles on each refresh.
- [ ] Tests: refreshing an open hour card with a new title keeps its slug. An aftermath candidate older than 7 days is ignored and a newer due card is processed. A closed calendar day produces exactly one `day` card.

### Task 4: Public API fixes + dead code (#6–#9, section 3, API style)

**Files:** delete `cards/` app, `dataset.RawCandle`, `articles/management/commands/seed_prices.py`, `articles/fixtures/`. Also touch `prices/views.py`, `articles/models.py`, `articles/views.py`, `articles/serializers.py`, `articles/services.py`, `agent/services/cards.py`, `agent/services/scoring.py`, `agent/llm.py`, `agent/models.py`, `agent/admin.py`, `agent/serializers.py`, `agent/management/commands/seed_sources.py`, `config/settings.py`, `config/urls.py`

- [ ] `AssetCandle`: `UniqueConstraint(series, timestamp)`.
- [ ] `prices` views become DRF `APIView`s, and `latest` reads `AssetCandle`.
- [ ] `/briefs/`: order by `-card__period_end`, then timeframe. Hourly and daily briefs interleave by recency.
- [ ] One `enabled_price_source_labels()` in `articles/services.py`, used by the serializer and the card assets code.
- [ ] Delete `_load_hourly_records`, `_is_financially_relevant`, `LLMClient.embed`, `AgentRun.objective`, legacy news/price source lists, and legacy asset series. General-news RSS feeds are dropped from the seed.
- [ ] `AgentConfigSerializer`: add the aftermath fields. `llm_base_url` becomes read-only via the API (admin-only).
- [ ] Tests: card-free URL conf. `/prices/series/X/latest/` returns the newest `AssetCandle`. `/briefs/` puts a day card that ended after an hourly card before that hourly card.

### Task 5: Price feeds + LLM client (#13, #15, LLM cost)

**Files:** `agent/price_sync.py`, `agent/llm.py`, `agent/models.py`, `agent/services/base.py`, `agent/services/budget.py`, `requirements.txt`

- [ ] yfinance: only symbols in `YF_SYMBOLS = {"^GSPC": "^GSPC", "DX-Y.NYB": "DX-Y.NYB", "XAUUSD=X": "GC=F"}`. ccxt: `CCXT_SYMBOLS = {"BTC-USD": "BTC/USDT", "ETH-USD": "ETH/USDT"}`. Candles are stamped with the bar's own timestamp. Errors are appended to `stats.errors` and logged instead of `pass`. Bump yfinance/ccxt to current versions.
- [ ] RSS parsing uses `defusedxml.ElementTree.fromstring`.
- [ ] LLM: drop the per-instance cache. `generate_json` returns `None` for non-dict JSON. Replace the `arvancloudai.ir` special case with `AgentConfig.llm_auth_scheme` (default `"Bearer"`). Record `usage` tokens on `AgentRun.llm_prompt_tokens` / `llm_completion_tokens`.
- [ ] Budget: replace the per-run cap with `AgentConfig.llm_daily_request_budget` (default 200), counted from today's `llm_prompt` log events. Keep the filter reserve logic.
- [ ] Tests: with a budget of 3 and 3 prompt events today, `_consume_llm_budget` returns False. `generate_json` with a list body returns None. `_auth_header` uses the configured scheme.

### Task 6: Dedup, retention, security (sections 4 + 7)

**Files:** `agent/services/fetching.py`, `agent/services/cards.py`, new `agent/management/commands/prune_data.py`, `agent/services/runtime.py`, `config/settings.py`, `frontend/pages/agent-control.vue`, `frontend/Dockerfile`

- [ ] `_load_raw_records`: drop near-duplicate titles across sources (`difflib.SequenceMatcher` ratio ≥ 0.85 on normalized titles).
- [ ] `prune_data`: delete `AgentLogEvent` older than `AGENT_LOG_RETENTION_DAYS` (14), `RawNewsItem` older than `RAW_NEWS_RETENTION_DAYS` (60), and `AssetCandle` older than `CANDLE_RETENTION_DAYS` (180). The worker calls it once per day.
- [ ] Settings: raise `ImproperlyConfigured` when `DEBUG` is false and `SECRET_KEY` is the default.
- [ ] Control token goes to `sessionStorage` instead of `localStorage`.
- [ ] Frontend Dockerfile: `COPY package*.json` + `npm ci`.
- [ ] Tests: two items with titles differing by punctuation collapse to one record. `prune_data` deletes only rows past retention.

### Task 7: SSE backend

**Files:** new `articles/stream.py`, `articles/urls.py`, `backend/Dockerfile` (CMD → uvicorn worker), `requirements.txt`, `config/settings.py`

**Interfaces:**
- `GET /api/stream/home/` sends events `lasthour` (same JSON as `/lasthour/`) and `briefs` (same JSON as `/briefs/?page=0&limit=10`) on connect and whenever the content version changes, plus a `: ping` comment every 15s.
- `GET /api/stream/articles/<id>/` sends event `article` (same JSON as `/articles/<id>/`) on connect and on change.
- `content_version() -> tuple` = (max `CardArticle.updated_at`, count). A single poller task per process checks it every 3s and wakes subscribers via `asyncio.Condition`.

- [ ] Async views return `StreamingHttpResponse(async_gen, content_type="text/event-stream")` with `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- [ ] `Dockerfile` CMD: `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker --workers 2`.
- [ ] Tests: the async test client reads the first event of `/api/stream/home/`, gets `event: lasthour`, and its data parses as JSON. `sse_event("x", {...})` formats correctly.

### Task 8: SSE frontend + SSR + scroll dedup + SEO

**Files:** new `frontend/composables/useEventStream.js`, `frontend/pages/index.vue`, `frontend/pages/articles/[id].vue`, `frontend/composables/useInfiniteScroll.js`, `frontend/nuxt.config.js`, `docker-compose.yml`, new `frontend/server/routes/sitemap.xml.js`, `frontend/server/routes/rss.xml.js`

- [ ] `useEventStream(path, handlers)`: client-only `EventSource`, JSON-parses each named event, closes on unmount (the browser auto-reconnects).
- [ ] index/article pages: remove `setInterval` polling and subscribe to the streams. Initial data comes from SSR (`useAsyncData` without `server: false`).
- [ ] `nuxt.config.js`: `apiBaseUrl` default `http://127.0.0.1:8081/api`. Compose sets `NUXT_API_BASE_URL=http://backend:8000/api` (the runtime override).
- [ ] `useInfiniteScroll.loadMore` skips ids already in `items`.
- [ ] Article page: `useSeoMeta` with og:title, og:description, og:type=article.
- [ ] `sitemap.xml` and `rss.xml` server routes built from `/briefs/?limit=100`.
- [ ] Verify: `npm run build` succeeds. Curling the rendered `/` shows brief HTML (SSR). `curl -N /api/stream/home/` streams events.

### Task 9: Observability + docs

**Files:** `articles/views.py` (health), `README.md`, `claude/architecture/overview.md`, `claude/context/*.md`, `claude/decisions/known-issues.md`

- [ ] `/api/health/` adds `agent: {running, last_heartbeat_at, last_news_run_at, last_price_sync_at}`. Container health still only needs HTTP 200.
- [ ] Update README endpoints, commands, and services. Mark fixed items in `known-issues.md` and record the deferred ones (paid price provider, structured logs, SSE for the admin dashboard).
