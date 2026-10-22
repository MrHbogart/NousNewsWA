from __future__ import annotations

import os
import re
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
import logging

import httpx
from dateutil import parser as dtparser
from django.utils import timezone

from agent.models import PriceSource
from articles.models import AssetCandle, AssetSeries


@dataclass
class PriceFeedStats:
    feeds_checked: int = 0
    items_parsed: int = 0
    prices_recorded: int = 0
    api_feeds_checked: int = 0
    api_prices_recorded: int = 0
    errors: list[str] = field(default_factory=list)


logger = logging.getLogger(__name__)

# AssetSeries.symbol -> provider ticker. Only these are requested, so a series
# a provider can't serve (FRED, Treasury) never costs a failing call.
YF_SYMBOLS = {
    "^GSPC": "^GSPC",
    "^IXIC": "^IXIC",
    "DX-Y.NYB": "DX-Y.NYB",
    "EURUSD=X": "EURUSD=X",
    "XAUUSD=X": "GC=F",
    "XAGUSD=X": "SI=F",
    "CL=F": "CL=F",
    "^TNX": "^TNX",
}
# Crypto comes from an exchange via ccxt (live 1m bars); Yahoo serves it when that fails.
CCXT_SYMBOLS = {"BTC-USD": "BTC/USDT", "ETH-USD": "ETH/USDT"}
YF_CRYPTO_FALLBACK = {"BTC-USD": "BTC-USD", "ETH-USD": "ETH-USD"}
# Binance blocks some regions (HTTP 451); kraken, coinbase or bitstamp also work (USD markets).
CCXT_EXCHANGE = os.getenv("PRICE_CRYPTO_EXCHANGE", "binance").strip().lower() or "binance"
CCXT_RETRY_SECONDS = 600
# Gaps (worker downtime) are refilled up to this far back; Yahoo keeps 1m bars for ~30 days.
BACKFILL_MAX = timedelta(days=5)
FRESH_SERIES_HISTORY = timedelta(days=1)

# yfinance trips pandas deprecation warnings on every call; they'd flood the worker log.
warnings.filterwarnings("ignore", module=r"yfinance(\.|$)")

_ccxt_paused_until = 0.0
# Last successful yfinance download and the symbols it covered (a symbol new
# to the set, e.g. a crypto fallback, still gets its own backfill).
_yf_synced_at: datetime | None = None
_yf_covered: set[str] = set()
YF_OVERLAP = timedelta(minutes=10)


def sync_price_feeds(*, user_agent: str | None = None) -> PriceFeedStats:
    """Built-in providers first (ccxt for crypto, yfinance for the rest), then configured PriceSource feeds.

    A PriceSource only fills a symbol the built-in providers didn't serve this
    time, so two providers never write into the same candle.
    """
    stats = PriceFeedStats()
    now = timezone.now()
    served: set[str] = set()
    try:
        served |= _sync_from_ccxt(stats, now)
    except Exception as exc:
        _record_error(stats, f"_sync_from_ccxt: {exc}")
    fallback = {
        symbol: ticker
        for symbol, ticker in YF_CRYPTO_FALLBACK.items()
        if symbol not in served and AssetSeries.objects.filter(symbol=symbol).exists()
    }
    try:
        served |= _sync_from_yfinance(stats, now, extra=fallback)
    except Exception as exc:
        _record_error(stats, f"_sync_from_yfinance: {exc}")
    _sync_from_price_sources(stats, now, user_agent, skip_symbols=served)
    return stats


def _record_error(stats: PriceFeedStats, message: str) -> None:
    logger.warning("price sync: %s", message)
    stats.errors.append(message[:500])


def _upsert_candle(series: AssetSeries, timestamp: datetime, open_: float, high: float, low: float, close: float, volume: float) -> None:
    """Merge a quote into its minute (feeds that report several ticks per minute)."""
    candle, created = AssetCandle.objects.get_or_create(
        series=series,
        timestamp=timestamp,
        defaults={"open": open_, "high": high, "low": low, "close": close, "volume": volume},
    )
    if not created:
        candle.high = max(candle.high, high)
        candle.low = min(candle.low, low)
        candle.close = close
        candle.volume = max(candle.volume, volume)
        candle.save(update_fields=["high", "low", "close", "volume"])


def _write_bars(series: AssetSeries, bars: list[tuple]) -> int:
    """Upsert provider bars (timestamp, open, high, low, close, volume): the provider's bar is authoritative."""
    rows = [
        AssetCandle(series=series, timestamp=ts, open=o, high=h, low=lo, close=c, volume=v or 0.0)
        for ts, o, h, lo, c, v in bars
        if c and c > 0
    ]
    if rows:
        AssetCandle.objects.bulk_create(
            rows,
            update_conflicts=True,
            unique_fields=["series", "timestamp"],
            update_fields=["open", "high", "low", "close", "volume", "updated_at"],
        )
    return len(rows)


def _last_bar_at(series: AssetSeries) -> datetime | None:
    return AssetCandle.objects.filter(series=series).order_by("-timestamp").values_list("timestamp", flat=True).first()


def _yfinance_targets() -> dict[str, str]:
    present = AssetSeries.objects.filter(symbol__in=list(YF_SYMBOLS)).values_list("symbol", flat=True)
    return {symbol: YF_SYMBOLS[symbol] for symbol in present}


def _sync_from_yfinance(stats: PriceFeedStats, now: datetime, extra: dict[str, str] | None = None) -> set[str]:
    targets = {**_yfinance_targets(), **(extra or {})}
    if not targets:
        return set()
    import yfinance as yf

    series_by_symbol = {s.symbol: s for s in AssetSeries.objects.filter(symbol__in=list(targets))}
    last_at = {symbol: _last_bar_at(series) for symbol, series in series_by_symbol.items()}
    # One request for every ticker, starting at the oldest gap: an idle minute
    # refetches a couple of bars, a restart refills what was missed.
    global _yf_synced_at
    start = min((ts or now - FRESH_SERIES_HISTORY) for ts in last_at.values())
    # A closed market's last bar stays put (weekends); once a sync has covered
    # it, later ones start from that sync instead of re-downloading days of bars.
    if _yf_synced_at is not None and set(targets) <= _yf_covered:
        start = max(start, _yf_synced_at - YF_OVERLAP)
    start = max(start, now - BACKFILL_MAX) - timedelta(minutes=1)
    tickers = sorted(set(targets.values()))
    data = yf.download(
        tickers, start=start, interval="1m", group_by="ticker", progress=False, threads=False, auto_adjust=False
    )
    stats.api_feeds_checked += len(targets)
    _yf_synced_at = now
    _yf_covered.clear()
    _yf_covered.update(targets)
    served = set()
    for symbol, ticker in targets.items():
        series = series_by_symbol.get(symbol)
        try:
            frame = data[ticker] if ticker in getattr(data.columns, "levels", [[]])[0] else data
            frame = frame.dropna(subset=["Close"])
        except (KeyError, TypeError):
            frame = None
        if series is None or frame is None or frame.empty:
            continue  # market closed or nothing new: not an error
        since = last_at.get(symbol)
        bars = []
        for index, row in frame.iterrows():
            bar_time = index.to_pydatetime().astimezone(dt_timezone.utc).replace(second=0, microsecond=0)
            if since and bar_time < since:
                continue
            close = _as_float(row.get("Close"))
            if close is None:
                continue
            open_value = _as_float(row.get("Open")) or close
            bars.append(
                (
                    bar_time,
                    open_value,
                    _as_float(row.get("High")) or max(open_value, close),
                    _as_float(row.get("Low")) or min(open_value, close),
                    close,
                    _as_float(row.get("Volume"), default=0.0),
                )
            )
        recorded = _write_bars(series, bars)
        stats.api_prices_recorded += recorded
        if recorded:
            served.add(symbol)
    return served


def _ccxt_market(symbol: str) -> str:
    market = CCXT_SYMBOLS[symbol]
    return market if CCXT_EXCHANGE == "binance" else market.replace("/USDT", "/USD")


def _sync_from_ccxt(stats: PriceFeedStats, now: datetime) -> set[str]:
    global _ccxt_paused_until
    present = list(AssetSeries.objects.filter(symbol__in=list(CCXT_SYMBOLS)))
    if not present or time.monotonic() < _ccxt_paused_until:
        return set()
    import ccxt

    exchange = getattr(ccxt, CCXT_EXCHANGE)()
    stats.api_feeds_checked += len(present)
    served = set()
    for series in present:
        market = _ccxt_market(series.symbol)
        try:
            since = _last_bar_at(series)
            # From the last stored bar (refills gaps 1000 bars per sync); the latest 1000 for a new series.
            if since:
                ohlcv = exchange.fetch_ohlcv(market, "1m", since=int(since.timestamp() * 1000), limit=1000)
            else:
                ohlcv = exchange.fetch_ohlcv(market, "1m", limit=1000)
            bars = [
                (datetime.fromtimestamp(ts_ms / 1000, tz=dt_timezone.utc), o, h, lo, c, v)
                for ts_ms, o, h, lo, c, v in (row[:6] for row in ohlcv or [])
            ]
            recorded = _write_bars(series, bars)
            stats.api_prices_recorded += recorded
            if recorded:
                served.add(series.symbol)
        except Exception as exc:
            # Usually a regional block or outage: Yahoo covers crypto meanwhile,
            # retry the exchange later instead of failing every sync.
            _ccxt_paused_until = time.monotonic() + CCXT_RETRY_SECONDS
            _record_error(stats, f"ccxt {CCXT_EXCHANGE} {market}: {exc}")
            break
    return served


def _sync_from_price_sources(
    stats: PriceFeedStats, now: datetime, user_agent: str | None = None, skip_symbols: set[str] = frozenset()
) -> None:
    """Configured PriceSource entries (RSS/API), for symbols the built-in providers didn't serve."""
    sources = list(PriceSource.objects.filter(enabled=True).exclude(symbol__in=skip_symbols).order_by("name"))
    if not sources:
        return

    headers: dict[str, str] = {}
    if user_agent:
        headers["User-Agent"] = user_agent

    client = httpx.Client(timeout=20, headers=headers, follow_redirects=True)
    try:
        for source in sources:
            if source.backoff_until and source.backoff_until > now:
                continue
            # rate_limit_seconds is a minimum gap between fetches, not a sleep.
            if source.last_fetched_at and source.rate_limit_seconds and (
                now - source.last_fetched_at
            ).total_seconds() < source.rate_limit_seconds:
                continue
            stats.feeds_checked += 1

            try:
                if source.source_type == PriceSource.SOURCE_RSS:
                    items = _fetch_rss_items(client, source)
                elif source.source_type == PriceSource.SOURCE_API:
                    if source.requires_api_key and not source.resolved_api_key:
                        raise RuntimeError("missing_api_key")
                    items = _fetch_api_items(client, source)
                else:
                    continue

                stats.items_parsed += len(items)
                recorded = _store_prices_from_items(source, items, now)
                stats.prices_recorded += recorded

                source.last_fetched_at = now
                source.failure_count = 0
                source.last_error = ""
                source.backoff_until = None
                source.save(
                    update_fields=[
                        "last_fetched_at",
                        "failure_count",
                        "last_error",
                        "backoff_until",
                    ]
                )
            except Exception as exc:
                _record_price_source_error(source, str(exc))
                _record_error(stats, f"{source.name}: {exc}")
    finally:
        client.close()


def _fetch_rss_items(client: httpx.Client, source: PriceSource) -> list[dict]:
    from agent.services.fetching import parse_feed  # lazy: agent.services imports this module

    response = client.get(source.base_url)
    response.raise_for_status()
    return [
        {"title": item["title"], "description": item["content"], "published_at": _parse_datetime(item["published"])}
        for item in parse_feed(response.text)
    ]


def _fetch_api_items(client: httpx.Client, source: PriceSource) -> list[dict]:
    """Fetch items from API endpoint."""
    params: dict[str, str] = {}
    headers: dict[str, str] = {}

    api_key = source.resolved_api_key
    if source.api_key_param and api_key:
        params[source.api_key_param] = api_key
    if source.api_key_header and api_key:
        headers[source.api_key_header] = api_key
    if source.symbol_param and source.symbol:
        params[source.symbol_param] = source.symbol

    try:
        response = client.get(source.base_url, params=params, headers=headers)
        response.raise_for_status()
        raw_text = response.text
        try:
            data = response.json()
        except Exception:
            return [{"title": source.name, "description": raw_text, "published_at": timezone.now()}]
        return _parse_price_api_payload(data, raw_text)
    except Exception:
        return []


def _parse_price_api_payload(data: object, raw_text: str) -> list[dict]:
    items: list[dict] = []

    if isinstance(data, dict):
        direct_quote = _parse_price_candidate_row(data)
        if direct_quote:
            items.append(direct_quote)

        observations = data.get("observations")
        if isinstance(observations, list):
            for row in reversed(observations):
                if not isinstance(row, dict):
                    continue
                value = _as_float(row.get("value"))
                if value is None:
                    continue
                items.append(
                    {
                        "price": value,
                        "published_at": _parse_provider_timestamp(row.get("date")),
                    }
                )
                break

        for key in ("data", "results", "prices", "quotes", "values"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                for row in candidate:
                    parsed = _parse_price_candidate_row(row)
                    if parsed:
                        items.append(parsed)

        if not items:
            nested_spot = _extract_nested_spot_price(data)
            if nested_spot is not None:
                items.append({"price": nested_spot, "published_at": timezone.now()})

    elif isinstance(data, list):
        for row in data:
            parsed = _parse_price_candidate_row(row)
            if parsed:
                items.append(parsed)

    if not items:
        items.append({"title": "", "description": raw_text, "published_at": timezone.now()})
    return items


def _parse_price_candidate_row(row: object) -> dict | None:
    if not isinstance(row, dict):
        return None

    close = _as_float(row.get("close"))
    if close is None:
        close = _as_float(row.get("c"))
    if close is None:
        close = _as_float(row.get("price"))
    if close is None:
        close = _as_float(row.get("last"))
    if close is None:
        close = _as_float(row.get("last_price"))
    if close is None:
        close = _as_float(row.get("value"))
    if close is None:
        close = _as_float(row.get("avg_interest_rate_amt"))
    if close is None:
        close = _as_float(row.get("yield"))
    if close is None:
        close = _as_float(row.get("rate"))
    if close is None and "usd" in row:
        close = _as_float(row.get("usd"))
    if close is None:
        return None

    open_price = _as_float(row.get("open"))
    if open_price is None:
        open_price = _as_float(row.get("o"))
    if open_price is None:
        open_price = close

    high = _as_float(row.get("high"))
    if high is None:
        high = _as_float(row.get("h"))
    if high is None:
        high = max(open_price, close)

    low = _as_float(row.get("low"))
    if low is None:
        low = _as_float(row.get("l"))
    if low is None:
        low = min(open_price, close)

    volume = _as_float(row.get("volume"))
    if volume is None:
        volume = _as_float(row.get("v"), default=0.0)

    published = (
        row.get("published_at")
        or row.get("publishedAt")
        or row.get("timestamp")
        or row.get("datetime")
        or row.get("time")
        or row.get("date")
        or row.get("record_date")
        or row.get("t")
    )

    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "published_at": _parse_provider_timestamp(published),
    }


def _extract_nested_spot_price(payload: dict) -> float | None:
    for value in payload.values():
        if not isinstance(value, dict):
            continue
        if "usd" in value:
            usd = _as_float(value.get("usd"))
            if usd is not None:
                return usd
        price = _as_float(value.get("price"))
        if price is not None:
            return price
    return None


def _store_prices_from_items(
    source: PriceSource, items: list[dict], now: datetime
) -> int:
    """Extract price from RSS/API items and store in AssetCandle."""
    recorded = 0
    symbol = (source.symbol or "").strip()
    if not symbol:
        return recorded

    series = AssetSeries.objects.filter(symbol=symbol).first()
    if not series:
        return recorded

    regex = source.price_regex or r"(?P<price>\d{1,3}(?:,\d{3})*(?:\.\d+)?)"

    for item in items:
        published_at = item.get("published_at")
        if isinstance(published_at, datetime):
            minute_ts = published_at.astimezone(dt_timezone.utc).replace(second=0, microsecond=0)
        else:
            minute_ts = now.replace(second=0, microsecond=0)

        close = _as_float(item.get("close"))
        used_regex = False
        if close is None:
            close = _as_float(item.get("price"))
        if close is None:
            text = " ".join(
                part.strip()
                for part in (item.get("title", ""), item.get("description", ""), item.get("raw", ""))
                if isinstance(part, str) and part.strip()
            )
            close = _extract_price(text, regex, source.price_scale)
            used_regex = True

        if close is None or close <= 0:
            continue

        open_price = _as_float(item.get("open"))
        if open_price is None:
            open_price = close

        high = _as_float(item.get("high"))
        if high is None:
            high = max(open_price, close)

        low = _as_float(item.get("low"))
        if low is None:
            low = min(open_price, close)

        volume = _as_float(item.get("volume"), default=0.0)

        scale = float(source.price_scale or 1.0)
        if not used_regex and scale != 1.0:
            open_price = open_price * scale
            high = high * scale
            low = low * scale
            close = close * scale

        _upsert_candle(series, minute_ts, open_price, high, low, close, volume)
        recorded += 1

    return recorded


def _extract_price(text: str, regex: str, scale: float) -> float | None:
    """Extract price from text using regex."""
    if not text:
        return None
    match = re.search(regex, text)
    if not match:
        return None
    if match.groupdict():
        value = match.groupdict().get("price")
    else:
        value = match.group(0)
    if value is None:
        return None
    cleaned = value.replace(",", "").strip()
    try:
        return float(cleaned) * (scale or 1.0)
    except ValueError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    """Parse datetime from various formats."""
    if not value:
        return None
    try:
        dt = dtparser.parse(str(value))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


def _parse_provider_timestamp(value: object) -> datetime | None:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=dt_timezone.utc)
        except Exception:
            return None

    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}T\d{6}", text):
        try:
            return datetime.strptime(text, "%Y%m%dT%H%M%S").replace(tzinfo=dt_timezone.utc)
        except ValueError:
            return None
    return _parse_datetime(text)


def _as_float(value: object, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        result = float(value)
        if result != result:  # NaN check
            return default
        return result

    text = str(value).strip()
    if not text or text in {".", "-", "null", "None", "nan", "NaN"}:
        return default
    cleaned = text.replace(",", "")
    try:
        result = float(cleaned)
    except Exception:
        return default
    if result != result:  # NaN check
        return default
    return result


def _record_price_source_error(source: PriceSource, message: str) -> None:
    """Record error and apply backoff."""
    now = timezone.now()
    source.failure_count = int(source.failure_count or 0) + 1
    source.last_error = message[:2000]
    source.backoff_until = now + timedelta(minutes=min(60, source.failure_count * 10))
    source.save(update_fields=["failure_count", "last_error", "backoff_until"])
