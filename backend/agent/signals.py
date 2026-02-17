from django.db.models.signals import post_save
from django.dispatch import receiver

from agent.models import AgentRun
from agent.services import start_agent_async


@receiver(post_save, sender=AgentRun)
def start_run_on_create(sender, instance: AgentRun, created: bool, **kwargs):
    if not created:
        return
    if instance.status != AgentRun.STATUS_RUNNING:
        return
    start_agent_async(run_id=instance.id)
