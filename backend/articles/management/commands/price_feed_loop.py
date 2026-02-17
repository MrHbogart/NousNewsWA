import time

from django.core.management.base import BaseCommand

from agent.services import get_config
from agent.price_sync import sync_price_feeds


class Command(BaseCommand):
    help = "Continuously sync price RSS feeds on a fixed interval."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=None,
            help="Seconds to wait between syncs.",
        )

    def handle(self, *args, **options):
        config = get_config()
        interval_override = options["interval"]
        if interval_override is not None:
            interval = max(5.0, float(interval_override))
        else:
            interval = max(5.0, float(config.price_loop_interval_seconds or 60.0))
        self.stdout.write(self.style.SUCCESS(f"Starting price feed loop (interval={interval}s)"))
        while True:
            stats = sync_price_feeds(user_agent=config.user_agent)
            self.stdout.write(
                self.style.SUCCESS(
                    "Price feeds synced: "
                    f"{stats.feeds_checked} feeds, "
                    f"{stats.items_parsed} items, "
                    f"{stats.prices_recorded} prices."
                )
            )
            time.sleep(interval)
