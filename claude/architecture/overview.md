# Architecture overview

## What this is

A news aggregation site: a background "agent" pipeline crawls configured
sources (RSS/API/scraped pages), optionally summarizes with an LLM, and
produces articles/briefs and price series that a Nuxt frontend renders.

## Topology

Four containers via `docker-compose.yml` (`docker-compose.dev.yml` layers on
bind mounts + hot reload for local dev):

- `db` — Postgres 15.
- `backend` — Django 5 + DRF served as ASGI by uvicorn (`--reload` in dev).
  ASGI is required: `/api/stream/*` are long-lived SSE connections.
- `agent` — same image, `python manage.py run_forever`: the only process that
  crawls, calls the LLM, syncs prices and prunes old data. The news run
  (crawl + LLM, minutes) runs on its own thread so price syncs keep their
  interval; each card's article+card writes are one transaction. Web
  processes control it through `AgentConfig` flags and read its
  `AgentWorker` heartbeat.
- `frontend` — Nuxt 3, SSR, served by its own Nitro server (not behind
  gunicorn/nginx).

One root `.env` (copied from `.env.example`) drives Docker Compose for both
services. `POSTGRES_*` is the single source of truth for DB credentials;
`docker-compose.yml` maps it to `DJANGO_DB_*` for the backend container so
there's only one place to change a password. For bare-metal (non-Docker) dev,
copy `.env.example` into `backend/.env` and `frontend/.env` separately —
each app's env loader only reads its own directory.

## Backend apps (`backend/`)

- **`core`** — abstract base models only: `TimeStampedModel`
  (`created_at`/`updated_at`). Every concrete model in this repo extends it;
  reuse it instead of redeclaring the timestamp fields.
- **`dataset`** — raw ingestion landing zone: `RawNewsItem`. What the agent
  fetches before any processing/dedup. (Prices go straight to
  `articles.AssetCandle`.)
- **`agent`** — the crawler/LLM pipeline and its admin-configurable state:
  `AgentConfig` (singleton-ish runtime config — LLM key, timeouts, token
  budgets — edited via Django admin or `PUT /api/agent/config/`, **not**
  environment variables), `AgentRun`, `AgentLogEvent`, `NewsSource`,
  `PriceSource`, `MemoryState`, `AgentWorker` (worker heartbeat row).
  Almost all the logic lives in
  `agent/services/`, a package assembling one `AgentService` class from
  focused mixins (see `context/conventions.md` for the module map) — fetch
  sources, call the LLM, write articles/cards/candles; the worker loop and
  its control flags live in `agent/services/runtime.py`. This used
  to be a single ~2700-line `agent/services.py` file; it was split by
  responsibility with no behavior change (see `decisions/known-issues.md`).
  `agent/llm.py` wraps the LLM HTTP call (auth scheme from
  `AgentConfig.llm_auth_scheme`, token usage recorded on `AgentRun`),
  `agent/price_sync.py` handles price syncing (yfinance for `YF_SYMBOLS`,
  ccxt/Binance for `CCXT_SYMBOLS`, then configured `PriceSource` feeds),
  `agent/retention.py` prunes old rows, `agent/economist_agent.py` is a secondary/optional
  agent gated by `AGENT_ENABLE_ECONOMIST_AGENT`, `agent/control_auth.py`
  implements a separate password + signed-token auth scheme
  (`Authorization: Bearer` or `X-Agent-Control-Token` header) for the `/api/agent/control/*` dashboard
  endpoints, distinct from Django's own auth.
- **`articles`** — the public-facing content model: `Card` (a 4-hour
  intraday block at 00/04/…/20 UTC / calendar day / week / month digest; only
  the current intraday block is ever `open`; once a day's card is final, that
  day's intraday briefs drop out of the feed and sitemap and their pages
  carry `noindex` plus a link to the day article),
  `CardArticle`/`CardAsset`, `AssetSeries` (a named price series),
  `AssetCandle` (1-minute OHLC, unique per series+minute). Views are DRF
  `APIView`s with serializers; `articles/stream.py` adds the SSE endpoints
  (one per-process poller watches a content version and fans updates out to
  every open stream).
- **`prices`** — thin read-only API over `articles.AssetSeries` /
  `AssetCandle`.

## URL routing

`config/urls.py` mounts, under `/api/`: `articles.urls` and `agent.urls` at
the root, `prices.urls` under `/prices/`. See
the root `README.md`'s "API endpoints" section for the concrete list — it's
kept in sync with the actual `urls.py` files; if you add/rename/remove a
route, update that README section too (it had drifted badly from the code
before this pass — see `decisions/known-issues.md`).

## Frontend (`frontend/`)

Nuxt 3, `pages/index.vue` (the main feed), `pages/articles/[id].vue`,
`pages/agent-control.vue` (talks to `/api/agent/control/*` via
`composables/useAgentControlApi.js`, which needs the control token from
`agent/control_auth.py`; it still polls — `EventSource` can't send the
token header). Public pages render server-side via `useAsyncData` +
`composables/useNewsApi.js` (`NUXT_API_BASE_URL` is the in-network API URL
for SSR, `NUXT_PUBLIC_API_BASE_URL` the browser's), then receive live
updates over SSE via `composables/useEventStream.js` (`/stream/home/`,
`/stream/articles/{id}/`). Article pages throw a real 404/503 (`error.vue`)
and emit `NewsArticle` JSON-LD. `server/routes/` serves `sitemap.xml`,
`rss.xml` and `robots.txt`.

`frontend/ARCHITECTURE.md`, `frontend/TECHNICAL_DEEP_DIVE.md`, and
`frontend/README_REDESIGN.md` are pre-existing, point-in-time design
write-ups for the card-scroll UI redesign — background/rationale for the
current component structure, not living documents. Treat them like
`reviews/` (below): read for context, don't edit them to reflect new
changes.

## Data flow

Sources (`NewsSource`/`PriceSource`, seeded via `seed_sources`) → `agent`
worker → `dataset.RawNewsItem` (raw landing) and `articles.AssetCandle` →
processed into `articles.Card`/`CardArticle`/`CardAsset` → served via the
`articles`/`prices` REST APIs and the SSE streams → Nuxt frontend.
