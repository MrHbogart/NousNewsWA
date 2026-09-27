import signal
import sys

from django.core.management.base import BaseCommand

from agent.services.runtime import run_worker


class Command(BaseCommand):
    help = "Agent worker: runs news and price loops, controlled via AgentConfig flags."

    def handle(self, *args, **options):
        # Turn `docker stop` (SIGTERM) into a normal exit so the worker row
        # is marked stopped.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        self.stdout.write(self.style.SUCCESS("Agent worker started"))
        run_worker()
