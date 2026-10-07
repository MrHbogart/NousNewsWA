from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from agent.models import PriceSource
from articles.models import AssetCandle, AssetSeries


def enabled_price_source_labels() -> dict[str, str]:
    """symbol -> chart label for every series that gets price data.

    That is series synced by the built-in yfinance/ccxt providers plus
    enabled PriceSource rows; an explicit chart_label wins over a name.
    """
    from agent.price_sync import CCXT_SYMBOLS, YF_SYMBOLS

    symbol_labels: dict[str, str] = {
        series.symbol: series.label or series.symbol
        for series in AssetSeries.objects.filter(symbol__in=[*YF_SYMBOLS, *CCXT_SYMBOLS])
    }
    explicit_labels: dict[str, bool] = {symbol: False for symbol in symbol_labels}
    rows = (
        PriceSource.objects.filter(enabled=True)
        .exclude(symbol__exact="")
        .order_by("symbol", "name", "id")
        .values("symbol", "chart_label", "name")
    )
    for row in rows:
        symbol = (row.get("symbol") or "").strip()
        if not symbol:
            continue
        chart_label = (row.get("chart_label") or "").strip()
        explicit = bool(chart_label)
        label = chart_label or (row.get("name") or "").strip() or symbol
        if symbol not in symbol_labels or (explicit and not explicit_labels.get(symbol)):
            symbol_labels[symbol] = label
            explicit_labels[symbol] = explicit
    return symbol_labels


INTRADAY_HOURS = 4


def get_period_window(at_time, timeframe: str):
    if timeframe == "intraday":
        start = at_time.replace(hour=at_time.hour - at_time.hour % INTRADAY_HOURS, minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=INTRADAY_HOURS)
    if timeframe == "day":
        start = at_time.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end
    if timeframe == "week":
        start = (at_time - timedelta(days=at_time.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(days=7)
        return start, end
    if timeframe == "month":
        start = at_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def resolve_timeframe(timeframe: str) -> tuple[int, int, str]:
    mapping = {
        "intraday": (5, 48, "5m"),
        "day": (15, 96, "15m"),
        "week": (240, 42, "4h"),
        "month": (1440, 30, "1d"),
    }
    return mapping.get(timeframe, (5, 48, "5m"))


def aggregate_candles(
    *,
    series: AssetSeries,
    start,
    end,
    interval_minutes: int,
    max_buckets: int,
) -> list[dict]:
    if interval_minutes <= 0 or max_buckets <= 0:
        return []
    # Plain tuples, not model instances: a month card reads ~43k rows per series.
    # ponytail: buckets in Python; move to SQL date_bin() if this shows up in profiles.
    rows = (
        AssetCandle.objects.filter(series=series, timestamp__gte=start, timestamp__lt=end)
        .order_by("timestamp")
        .values_list("timestamp", "open", "high", "low", "close", "volume")
    )
    candles = [
        SimpleNamespace(timestamp=t, open=o, high=h, low=lo, close=c, volume=v) for t, o, h, lo, c, v in rows
    ]
    if not candles:
        return []
    buckets: list[dict] = []
    bucket = None
    bucket_index = None
    start_ts = start
    for candle in candles:
        minutes = int((candle.timestamp - start_ts).total_seconds() // 60)
        index = minutes // interval_minutes
        if bucket_index is None or index != bucket_index:
            if bucket is not None:
                buckets.append(bucket)
            bucket_index = index
            bucket_start = start_ts + timedelta(minutes=index * interval_minutes)
            bucket = {
                "timestamp": bucket_start,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
        else:
            bucket["high"] = max(bucket["high"], candle.high)
            bucket["low"] = min(bucket["low"], candle.low)
            bucket["close"] = candle.close
            bucket["volume"] += candle.volume
    if bucket is not None:
        buckets.append(bucket)
    if len(buckets) > max_buckets:
        buckets = buckets[-max_buckets:]
    return buckets
