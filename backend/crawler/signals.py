from django.db.models.signals import post_save
from django.dispatch import receiver

from crawler.models import CrawlRun
from crawler.services import start_crawler_async


@receiver(post_save, sender=CrawlRun)
def start_run_on_create(sender, instance: CrawlRun, created: bool, **kwargs):
    if not created:
        return
    if instance.status != CrawlRun.STATUS_RUNNING:
        return
    start_crawler_async(run_id=instance.id)
