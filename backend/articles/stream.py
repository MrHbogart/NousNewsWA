"""Server-Sent Events for readers.

One watcher per process tracks two topics: `content` (cards/articles) and
`prices` (candles). A Postgres LISTEN connection, fed by the triggers in
migration 0001, wakes it the moment either changes; a cheap fingerprint poll
per topic is the fallback. Payloads are built once per topic version and
shared by all streams, so N readers cost one build per change, not N; each
stream skips payloads identical to the last one it sent.

Price ticks go out as a small `prices` event (`{id, price_series}`) so charts
move live without resending — or re-rendering — the whole brief.
"""
from __future__ import annotations

import asyncio
import json
import logging

import psycopg
from asgiref.sync import sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import Count, Max, Q
from django.http import JsonResponse, StreamingHttpResponse

from articles.models import AssetCandle, Card, CardArticle
from articles.views import article_payload, briefs_payload, last_hour_payload

logger = logging.getLogger(__name__)

POLL_SECONDS = 3.0  # fallback when NOTIFY is unavailable (e.g. pgbouncer transaction mode)
COALESCE_SECONDS = 0.2  # the agent writes in bursts; send the end state
PING_SECONDS = 15.0
RETRY_MS = 1000  # browser reconnect delay after a dropped stream (default is 3-5s)


def sse_event(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, cls=DjangoJSONEncoder)}\n\n"


def content_fingerprint() -> tuple:
    # Card saves use update_fields without updated_at, so count finals too.
    articles = CardArticle.objects.aggregate(latest=Max("updated_at"), count=Count("id"))
    cards = Card.objects.aggregate(count=Count("id"), final=Count("id", filter=Q(status=Card.STATUS_FINAL)))
    return (articles["latest"], articles["count"], cards["count"], cards["final"])


def prices_fingerprint() -> tuple:
    # Syncs insert or update the newest candle per series; the newest rows by pk
    # cover both, via the pk index.
    return tuple(AssetCandle.objects.order_by("-id").values_list("id", "close", "high", "low")[:50])


TOPICS = {"content": content_fingerprint, "prices": prices_fingerprint}  # LISTEN channel: nousnews_<topic>


async def _db(fn, *args):
    # Streams outlive requests: run ORM work off the event loop and hand the
    # connection back each time instead of pinning one per open stream.
    def call():
        try:
            return fn(*args)
        finally:
            connection.close()

    return await sync_to_async(call, thread_sensitive=False)()


def _listen_params() -> dict:
    s = connection.settings_dict
    params = {"dbname": s["NAME"], "user": s["USER"], "password": s["PASSWORD"], "host": s["HOST"], "port": s["PORT"]}
    django_only = ("isolation_level", "server_side_binding", "assume_role", "pool")
    params.update({k: v for k, v in s.get("OPTIONS", {}).items() if k not in django_only})
    return {k: v for k, v in params.items() if v not in (None, "")}


class _Watcher:
    def __init__(self):
        self.versions = dict.fromkeys(TOPICS, 0)
        self.fingerprints = dict.fromkeys(TOPICS)
        self.condition: asyncio.Condition | None = None
        self.changed: dict[str, asyncio.Event] = {}
        self.tasks: list[asyncio.Task] = []
        self._cache: dict = {}

    def ensure_started(self) -> None:
        loop = asyncio.get_running_loop()
        if not self.tasks or self.tasks[0].done() or self.tasks[0].get_loop() is not loop:
            self.condition = asyncio.Condition()
            self.fingerprints = dict.fromkeys(TOPICS)
            self.changed = {topic: asyncio.Event() for topic in TOPICS}
            self._cache = {}
            self.tasks = [loop.create_task(self._poll(topic)) for topic in TOPICS]
            if connection.vendor == "postgresql":
                self.tasks.append(loop.create_task(self._listen()))

    async def _listen(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(**_listen_params(), autocommit=True) as conn:
                    for topic in TOPICS:
                        await conn.execute(f"LISTEN nousnews_{topic}")
                    for event in self.changed.values():
                        event.set()  # catch anything missed while disconnected
                    async for notify in conn.notifies():
                        event = self.changed.get(notify.channel.removeprefix("nousnews_"))
                        if event:
                            event.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("stream LISTEN connection lost; falling back to polling", exc_info=True)
            await asyncio.sleep(5)

    async def _poll(self, topic: str) -> None:
        changed = self.changed[topic]
        while True:
            try:
                await asyncio.wait_for(changed.wait(), POLL_SECONDS)
                notified = True
                await asyncio.sleep(COALESCE_SECONDS)
            except asyncio.TimeoutError:
                notified = False
            changed.clear()
            try:
                fingerprint = await _db(TOPICS[topic])
            except Exception:
                logger.exception("stream %s fingerprint poll failed", topic)
                continue
            # A notify always rebuilds: card field edits don't move the fingerprint.
            if notified or fingerprint != self.fingerprints[topic]:
                self.fingerprints[topic] = fingerprint
                self.versions = {**self.versions, topic: self.versions[topic] + 1}
                self._cache = {k: v for k, v in self._cache.items() if k[0] != topic}
                async with self.condition:
                    self.condition.notify_all()

    async def wait_for_change(self, seen: dict) -> dict:
        async with self.condition:
            try:
                await asyncio.wait_for(self.condition.wait_for(lambda: self.versions != seen), PING_SECONDS)
            except asyncio.TimeoutError:
                pass
        return self.versions

    async def payload(self, topic: str, key, builder, *args):
        # Cache the in-flight build, not its result, so concurrent streams share it.
        cache_key = (topic, key)
        version = self.versions[topic]
        entry = self._cache.get(cache_key)
        if entry is None or entry[0] != version:
            entry = (version, asyncio.ensure_future(_db(builder, *args)))
            self._cache[cache_key] = entry
        try:
            # shield: one reader disconnecting mustn't cancel everyone's build.
            return await asyncio.shield(entry[1])
        except Exception:
            if self._cache.get(cache_key) is entry:
                del self._cache[cache_key]  # don't serve a failed build for the whole version
            raise


watcher = _Watcher()


def _home() -> dict:
    return {"lasthour": last_hour_payload(), "briefs": briefs_payload(0, 10)}


def _prices_of(payload: dict | None) -> dict | None:
    if not payload or not payload.get("id"):
        return None
    return {"id": payload["id"], "price_series": payload.get("price_series") or []}


def _home_prices() -> dict | None:
    # Only the current hour's chart is still moving; closed periods are fixed.
    return _prices_of(last_hour_payload())


def _article_prices(pk: str) -> dict | None:
    return _prices_of(article_payload(pk))


def _stream_response(*feeds) -> StreamingHttpResponse:
    """feeds: (event, topic, key, builder, *args); the first one is sent on connect."""

    async def events():
        watcher.ensure_started()
        seen = watcher.versions
        event, topic, *build = feeds[0]
        last = {event: sse_event(event, await watcher.payload(topic, *build))}
        yield last[event]
        yield f"retry: {RETRY_MS}\n\n"
        while True:
            versions = await watcher.wait_for_change(seen)
            if versions == seen:
                yield ": ping\n\n"
                continue
            changed = {t for t in versions if versions[t] != seen[t]}
            seen = versions
            for event, topic, *build in feeds:
                if topic not in changed:
                    continue
                data = await watcher.payload(topic, *build)
                if data is None:
                    continue
                message = sse_event(event, data)
                if message != last.get(event):
                    last[event] = message
                    yield message

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # let nginx-style proxies flush each event
    return response


async def home_stream(request):
    return _stream_response(
        ("home", "content", "home", _home),
        ("prices", "prices", "home", _home_prices),
    )


async def article_stream(request, pk: str):
    if await _db(article_payload, pk) is None:
        return JsonResponse({"detail": "Not found."}, status=404)
    return _stream_response(
        ("article", "content", ("article", pk), article_payload, pk),
        ("prices", "prices", ("article", pk), _article_prices, pk),
    )
