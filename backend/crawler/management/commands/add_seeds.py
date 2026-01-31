from django.core.management.base import BaseCommand

from crawler.models import CrawlSeed
from crawler.services import get_config


SEED_URLS = [
    "https://www.forexlive.com/",
    "https://www.dailyfx.com/",
    "https://www.investing.com/",
    "https://www.forexfactory.com/",
    "https://www.marketwatch.com/",
    "https://newsquawk.com/",
    "https://finance.yahoo.com/",
    "https://www.financemagnates.com/",
    "https://www.barrons.com/",
    "https://seekingalpha.com/",
    "https://www.tradingview.com/news/",
    "https://www.benzinga.com/",
    "https://www.stockmarketwatch.com/",
    "https://www.zacks.com/",
    "https://www.morningstar.com/",
    "https://www.kitco.com/",
    "https://oilprice.com/",
    "https://www.coindesk.com/",
    "https://cointelegraph.com/",
    "https://www.zerohedge.com/",
]


class Command(BaseCommand):
    help = "Add default crawl seed URLs."

    def handle(self, *args, **options):
        config = get_config()
        created = 0
        updated = 0
        seed_set = set(SEED_URLS)
        for url in SEED_URLS:
            seed, was_created = CrawlSeed.objects.get_or_create(
                url=url,
                defaults={"config": config},
            )
            if was_created:
                created += 1
            else:
                updated += 1
                if seed.config_id is None:
                    seed.config = config
            if not seed.is_active:
                seed.is_active = True
            if seed.is_active and seed.config_id:
                seed.save(update_fields=["is_active", "config"])
            elif seed.is_active:
                seed.save(update_fields=["is_active"])
        deactivated = (
            CrawlSeed.objects.exclude(url__in=seed_set)
            .filter(is_active=True)
            .update(is_active=False)
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Seeds added. "
                f"created={created} existing={updated} deactivated={deactivated}"
            )
        )
