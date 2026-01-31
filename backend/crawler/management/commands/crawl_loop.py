import time

from django.core.management.base import BaseCommand

from crawler.services import CrawlerService, get_config


class Command(BaseCommand):
    help = "Continuously run the crawler on a fixed interval."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=10.0,
            help="Seconds to wait between crawl runs.",
        )

    def handle(self, *args, **options):
        interval = float(options["interval"])
        config = get_config()
        self.stdout.write(
            self.style.SUCCESS(
                f"Starting crawl loop (interval={interval}s, max_pages_per_run={config.max_pages_per_run})"
            )
        )
        while True:
            service = CrawlerService(config=config)
            service.run()
            time.sleep(max(1.0, interval))
