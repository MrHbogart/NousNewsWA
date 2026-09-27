from django.core.management.base import BaseCommand

from agent.retention import prune_old_data


class Command(BaseCommand):
    help = "Delete agent logs, raw news and candles older than their retention windows."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f"Pruned: {prune_old_data()}"))
