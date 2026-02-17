from __future__ import annotations

from datetime import timedelta

from articles.models import AssetCandle, AssetSeries


def get_hour_window(at_time):
    start = at_time.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    return start, end


def get_period_window(at_time, timeframe: str):
    if timeframe == "hour":
        return get_hour_window(at_time)
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
        "hour": (1, 60, "1m"),
        "day": (15, 96, "15m"),
        "week": (240, 42, "4h"),
        "month": (1440, 30, "1d"),
    }
    return mapping.get(timeframe, (1, 60, "1m"))


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
    candles = list(
        AssetCandle.objects.filter(series=series, timestamp__gte=start, timestamp__lt=end)
        .order_by("timestamp")
    )
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
