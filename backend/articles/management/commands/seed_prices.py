from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from articles.models import AssetCandle, AssetSeries
from articles.services import get_hour_window


ASSETS = [
    ("USDidx", "US Dollar Index", "USDidx.csv"),
    ("BTCUSD", "Bitcoin", "BTCUSD.csv"),
    ("XAUUSD", "Gold", "XAUUSD.csv"),
    ("S&P500", "S&P 500", "SP500.csv"),
]


class Command(BaseCommand):
    help = "Seed demo price series and candles for the latest hour."

    def handle(self, *args, **options):
        now = timezone.now()
        hour_start, hour_end = get_hour_window(now)
        created_series = 0
        created_candles = 0
        fixture_dir = Path(__file__).resolve().parent.parent.parent / "fixtures"
        rows_cache = {}
        for symbol, label, filename in ASSETS:
            if filename not in rows_cache:
                rows_cache[filename] = self._load_rows(fixture_dir / filename)
            rows = rows_cache[filename]
            series, was_created = AssetSeries.objects.get_or_create(
                symbol=symbol,
                defaults={"timeframe": "1m", "label": label},
            )
            if was_created:
                created_series += 1

            if not AssetCandle.objects.filter(series=series, timestamp__gte=hour_start, timestamp__lt=hour_end).exists():
                for idx, row in enumerate(rows):
                    ts = hour_start + timedelta(minutes=idx)
                    open_price = row["open"]
                    high = row["high"]
                    low = row["low"]
                    close_price = row["close"]
                    volume = row["volume"]
                    AssetCandle.objects.create(
                        series=series,
                        timestamp=ts,
                        open=open_price,
                        high=high,
                        low=low,
                        close=close_price,
                        volume=volume,
                    )
                    created_candles += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded price series: {created_series} created, {created_candles} candles."
            )
        )

    def _load_rows(self, path: Path) -> list[dict]:
        rows: list[dict] = []
        if not path.exists():
            return rows
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append(
                    {
                        "open": float(row.get("Open") or 0),
                        "high": float(row.get("High") or 0),
                        "low": float(row.get("Low") or 0),
                        "close": float(row.get("Close") or 0),
                        "volume": float(row.get("Volume") or 0),
                    }
                )
        if len(rows) >= 60:
            return rows[-60:]
        if not rows:
            return []
        last = rows[-1]
        while len(rows) < 60:
            rows.append(last.copy())
        return rows
