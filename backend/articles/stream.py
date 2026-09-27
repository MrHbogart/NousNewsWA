"""Server-Sent Events for readers.

One poller task per process checks a cheap content version every few
seconds and wakes every open stream when it changes; payloads are built once
per version and shared by all streams, so N readers cost ~1 query per poll,
not N.
"""
from __future__ import annotations

import asyncio
import json
import logging

from asgiref.sync import sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import Count, Max
from django.http import JsonResponse, StreamingHttpResponse

from articles.models import CardArticle
from articles.views import article_payload, briefs_payload, last_hour_payload

logger = logging.getLogger(__name__)

POLL_SECONDS = 3.0
PING_SECONDS = 15.0


def sse_event(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, cls=DjangoJSONEncoder)}\n\n"


def content_version() -> tuple:
    agg = CardArticle.objects.aggregate(latest=Max("updated_at"), count=Count("id"))
    return (agg["latest"], agg["count"])


async def _db(fn, *args):
    # Streams outlive requests: run ORM work off the event loop and hand the
    # connection back each time instead of pinning one per open stream.
    def call():
        try:
            return fn(*args)
        finally:
            connection.close()

    return await sync_to_async(call, thread_sensitive=False)()


class _Watcher:
    def __init__(self):
        self.version = None
        self.condition: asyncio.Condition | None = None
        self.task: asyncio.Task | None = None
        self._cache: dict = {}

    def ensure_started(self) -> None:
        loop = asyncio.get_running_loop()
        if self.task is None or self.task.done() or self.task.get_loop() is not loop:
            self.condition = asyncio.Condition()
            self.task = loop.create_task(self._poll())

    async def _poll(self) -> None:
        # ponytail: polls even with zero readers (1 tiny query / 3s / process);
        # switch to Postgres LISTEN/NOTIFY if that ever matters.
        while True:
            try:
                version = await _db(content_version)
            except Exception:
                logger.exception("stream version poll failed")
                version = self.version
            if version != self.version:
                self.version = version
                self._cache = {}
                async with self.condition:
                    self.condition.notify_all()
            await asyncio.sleep(POLL_SECONDS)

    async def wait_for_change(self, seen) -> object:
        async with self.condition:
            try:
                await asyncio.wait_for(self.condition.wait_for(lambda: self.version != seen), PING_SECONDS)
            except asyncio.TimeoutError:
                pass
        return self.version

    async def payload(self, key, builder, *args):
        version = self.version
        cached = self._cache.get(key)
        if cached is not None and cached[0] == version:
            return cached[1]
        data = await _db(builder, *args)
        self._cache[key] = (version, data)
        return data


watcher = _Watcher()


def _home() -> dict:
    return {"lasthour": last_hour_payload(), "briefs": briefs_payload(0, 10)}


def _stream_response(event: str, key, builder, *args) -> StreamingHttpResponse:
    async def events():
        watcher.ensure_started()
        seen = watcher.version
        yield sse_event(event, await watcher.payload(key, builder, *args))
        while True:
            version = await watcher.wait_for_change(seen)
            if version == seen:
                yield ": ping\n\n"
                continue
            seen = version
            data = await watcher.payload(key, builder, *args)
            if data is not None:
                yield sse_event(event, data)

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # let nginx-style proxies flush each event
    return response


async def home_stream(request):
    return _stream_response("home", "home", _home)


async def article_stream(request, pk: str):
    if await _db(article_payload, pk) is None:
        return JsonResponse({"detail": "Not found."}, status=404)
    return _stream_response("article", ("article", pk), article_payload, pk)
