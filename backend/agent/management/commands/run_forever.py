import time

from django.core.management.base import BaseCommand

from agent.services import AgentService, get_config
from agent.price_sync import sync_price_feeds


class Command(BaseCommand):
    help = "Run news and price loops forever using admin-configured intervals."

    def handle(self, *args, **options):
        last_news = 0.0
        last_price = 0.0

        self.stdout.write(
            self.style.SUCCESS(
                "Starting run_forever (intervals from AgentConfig)"
            )
        )

        while True:
            config = get_config()
            if not config.run_forever_enabled:
                time.sleep(1.0)
                continue
            news_interval = max(60.0, float(config.loop_interval_minutes or 1.0) * 60.0)
            price_interval = max(5.0, float(config.price_loop_interval_seconds or 60.0))
            now = time.time()
            if now - last_news >= news_interval:
                service = AgentService(config=config)
                service.run()
                last_news = time.time()
            if now - last_price >= price_interval:
                sync_price_feeds(user_agent=config.user_agent)
                last_price = time.time()
            time.sleep(1.0)
