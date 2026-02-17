from django.core.management.base import BaseCommand

from agent.price_sync import sync_price_feeds
from agent.services import get_config


class Command(BaseCommand):
    help = "Fetch price RSS feeds and store 1-minute candles."

    def handle(self, *args, **options):
        config = get_config()
        stats = sync_price_feeds(user_agent=config.user_agent)
        self.stdout.write(
            self.style.SUCCESS(
                "Price feeds synced: "
                f"{stats.feeds_checked} feeds, "
                f"{stats.items_parsed} items, "
                f"{stats.prices_recorded} prices."
            )
        )
