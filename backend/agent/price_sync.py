from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta

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


def sync_price_feeds(*, user_agent: str | None = None) -> PriceFeedStats:
    """Sync prices using hybrid approach: yfinance/ccxt first, then fallback to RSS/API.

    Priority:
    1. Try yfinance for equity/ETF/index symbols
    2. Try ccxt for crypto symbols
    3. Fallback to PriceSource (RSS/API) entries
    """
    stats = PriceFeedStats()
    now = timezone.now()

    try:
        _sync_from_yfinance(stats, now)
    except Exception:
        pass  # Graceful degradation

    try:
        _sync_from_ccxt(stats, now)
    except Exception:
        pass  # Graceful degradation

    # Fallback: sync from configured RSS/API sources
    _sync_from_price_sources(stats, now, user_agent)

    return stats


def _sync_from_yfinance(stats: PriceFeedStats, now: datetime) -> None:
    """Fetch latest prices from yfinance for configured symbols."""
    try:
        import yfinance as yf
    except ImportError:
        return

    symbols = list(
        AssetSeries.objects.filter(symbol__isnull=False)
        .exclude(symbol__in=["BTC-USD", "ETH-USD", "BTCUSDT"])
        .values_list("symbol", flat=True)
        .distinct()
    )
    if not symbols:
        return

    stats.api_feeds_checked += len(symbols)
    minute_ts = now.replace(second=0, microsecond=0)

    try:
        tickers = yf.Tickers(" ".join(symbols))
    except Exception:
        tickers = None

    for symbol in symbols:
        try:
            series = AssetSeries.objects.filter(symbol=symbol).first()
            if not series:
                continue

            ticker_obj = None
            if tickers is not None:
                try:
                    ticker_obj = tickers.tickers.get(symbol) or tickers.tickers.get(symbol.upper())
                except Exception:
                    ticker_obj = None
            if ticker_obj is None:
                ticker_obj = yf.Ticker(symbol)

            history = ticker_obj.history(period="1d", interval="1m")
            if history is None or history.empty:
                continue

            latest = history.iloc[-1]
            close = _as_float(latest.get("Close"))
            open_price = _as_float(latest.get("Open"))
            high = _as_float(latest.get("High"))
            low = _as_float(latest.get("Low"))
            volume = _as_float(latest.get("Volume"), default=0.0)

            if close is None or close <= 0:
                continue

            open_value = open_price if open_price is not None and open_price > 0 else close
            high_value = high if high is not None and high > 0 else max(open_value, close)
            low_value = low if low is not None and low > 0 else min(open_value, close)

            candle, created = AssetCandle.objects.get_or_create(
                series=series,
                timestamp=minute_ts,
                defaults={
                    "open": open_value,
                    "high": high_value,
                    "low": low_value,
                    "close": close,
                    "volume": volume,
                },
            )
            if not created:
                candle.high = max(candle.high, high_value)
                candle.low = min(candle.low, low_value)
                candle.close = close
                candle.volume = max(candle.volume, volume)
                candle.save(update_fields=["high", "low", "close", "volume"])
            stats.api_prices_recorded += 1
        except Exception:
            continue


def _sync_from_ccxt(stats: PriceFeedStats, now: datetime) -> None:
    """Fetch latest prices from CCXT for crypto symbols."""
    try:
        import ccxt
    except ImportError:
        return

    symbols = [
        s
        for s in AssetSeries.objects.filter(
            symbol__in=["BTC-USD", "ETH-USD", "BTCUSDT", "BTC/USD", "ETH/USD"]
        ).values_list("symbol", flat=True)
    ]
    if not symbols:
        return

    try:
        exchange = ccxt.binance()
        stats.api_feeds_checked += len(symbols)
        minute_ts = now.replace(second=0, microsecond=0)

        for symbol in symbols:
            try:
                series = AssetSeries.objects.filter(symbol=symbol).first()
                if not series:
                    continue

                exchange_symbol = symbol.replace("-", "/") if "-" in symbol else symbol
                ohlcv = exchange.fetch_ohlcv(exchange_symbol, "1m", limit=1)
                if not ohlcv:
                    continue

                candle_row = ohlcv[-1]
                open_price, high, low, close, volume = candle_row[1:]

                if close <= 0:
                    continue

                candle, created = AssetCandle.objects.get_or_create(
                    series=series,
                    timestamp=minute_ts,
                    defaults={
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    },
                )
                if not created:
                    candle.high = max(candle.high, high)
                    candle.low = min(candle.low, low)
                    candle.close = close
                    candle.save(update_fields=["high", "low", "close"])
                stats.api_prices_recorded += 1
            except Exception:
                pass
    except Exception:
        pass


def _sync_from_price_sources(stats: PriceFeedStats, now: datetime, user_agent: str | None = None) -> None:
    """Fallback: sync from configured PriceSource entries (RSS/API)."""
    sources = list(PriceSource.objects.filter(enabled=True).order_by("name"))
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
            stats.feeds_checked += 1

            try:
                if source.source_type == PriceSource.SOURCE_RSS:
                    items = _fetch_rss_items(client, source)
                elif source.source_type == PriceSource.SOURCE_API:
                    if (source.api_key_param or source.api_key_header) and not (source.api_key or "").strip():
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
            time.sleep(max(0.0, float(source.rate_limit_seconds or 0)))
    finally:
        client.close()


def _fetch_rss_items(client: httpx.Client, source: PriceSource) -> list[dict]:
    """Fetch items from RSS feed."""
    response = client.get(source.base_url)
    response.raise_for_status()
    items: list[dict] = []
    try:
        root = ET.fromstring(response.text)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            description = (item.findtext("description") or "").strip()
            content_encoded = ""
            for child in list(item):
                if isinstance(child.tag, str) and child.tag.endswith("encoded"):
                    content_encoded = (child.text or "").strip()
                    break
            pub_date = (item.findtext("pubDate") or "").strip()
            items.append(
                {
                    "title": title,
                    "description": content_encoded or description,
                    "published_at": _parse_datetime(pub_date),
                }
            )

        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry") + root.findall(".//entry"):
            title = (
                entry.findtext("{http://www.w3.org/2005/Atom}title")
                or entry.findtext("title")
                or ""
            ).strip()
            summary = (
                entry.findtext("{http://www.w3.org/2005/Atom}summary")
                or entry.findtext("summary")
                or ""
            ).strip()
            content = (
                entry.findtext("{http://www.w3.org/2005/Atom}content")
                or entry.findtext("content")
                or summary
                or title
            ).strip()
            published = (
                entry.findtext("{http://www.w3.org/2005/Atom}updated")
                or entry.findtext("{http://www.w3.org/2005/Atom}published")
                or entry.findtext("updated")
                or entry.findtext("published")
                or ""
            ).strip()
            items.append(
                {
                    "title": title,
                    "description": content,
                    "published_at": _parse_datetime(published),
                }
            )
    except Exception:
        pass
    return items


def _fetch_api_items(client: httpx.Client, source: PriceSource) -> list[dict]:
    """Fetch items from API endpoint."""
    params: dict[str, str] = {}
    headers: dict[str, str] = {}

    if source.api_key_param and source.api_key:
        params[source.api_key_param] = source.api_key
    if source.api_key_header and source.api_key:
        headers[source.api_key_header] = source.api_key
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
            minute_ts = published_at.astimezone(timezone.utc).replace(second=0, microsecond=0)
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

        candle, created = AssetCandle.objects.get_or_create(
            series=series,
            timestamp=minute_ts,
            defaults={
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            },
        )
        if not created:
            candle.high = max(candle.high, high)
            candle.low = min(candle.low, low)
            candle.close = close
            candle.volume = max(candle.volume, volume)
            candle.save(update_fields=["high", "low", "close", "volume"])
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
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_provider_timestamp(value: object) -> datetime | None:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None

    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}T\d{6}", text):
        try:
            return datetime.strptime(text, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
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
