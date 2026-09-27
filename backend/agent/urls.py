from django.urls import path

from agent import views


urlpatterns = [
    path("agent/config/", views.AgentConfigView.as_view(), name="agent-config"),
    path("agent/logs/", views.AgentLogsView.as_view(), name="agent-logs"),
    path("agent/control/login/", views.AgentControlLoginView.as_view(), name="agent-control-login"),
    path("agent/control/state/", views.AgentControlStateView.as_view(), name="agent-control-state"),
    path("agent/control/stats/", views.AgentControlStatsView.as_view(), name="agent-control-stats"),
    path("agent/control/logs/", views.AgentControlLogsView.as_view(), name="agent-control-logs"),
    path("agent/control/dashboard/", views.AgentControlDashboardView.as_view(), name="agent-control-dashboard"),
    path("agent/control/start/", views.AgentControlStartView.as_view(), name="agent-control-start"),
    path("agent/control/run-once/", views.AgentControlRunOnceView.as_view(), name="agent-control-run-once"),
    path("agent/control/pause/", views.AgentControlPauseView.as_view(), name="agent-control-pause"),
    path("agent/control/resume/", views.AgentControlResumeView.as_view(), name="agent-control-resume"),
    path("agent/control/stop/", views.AgentControlStopView.as_view(), name="agent-control-stop"),
]
