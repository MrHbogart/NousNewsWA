import time

from django.core.management.base import BaseCommand

from agent.services import AgentService, get_config


class Command(BaseCommand):
    help = "Continuously run the agent on a fixed interval."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=None,
            help="Seconds to wait between agent runs (overrides admin setting).",
        )

    def handle(self, *args, **options):
        config = get_config()
        interval_override = options["interval"]
        if interval_override is not None:
            interval = float(interval_override)
        else:
            if config.loop_interval_minutes is None:
                self.stdout.write(self.style.ERROR("loop_interval_minutes is not set in AgentConfig."))
                return
            interval = float(config.loop_interval_minutes) * 60.0
        self.stdout.write(
            self.style.SUCCESS(
                f"Starting agent loop (interval={interval}s)"
            )
        )
        while True:
            service = AgentService(config=config)
            service.run()
            time.sleep(max(1.0, interval))
