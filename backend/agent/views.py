from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.control_auth import control_password_configured, issue_control_token, verify_control_password
from agent.models import AgentLogEvent, AgentRun
from agent.permissions import ControlLoginThrottle, HasAgentControlToken
from agent.serializers import AgentConfigSerializer, AgentControlLoginSerializer, AgentLogEventSerializer
from agent.services import (
    agent_live_status,
    get_config,
    request_pause,
    request_resume,
    request_run_once,
    request_start,
    request_stop,
    worker_status,
)


def _int_param(raw_value, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def _build_stats(hours: int) -> dict:
    since = timezone.now() - timedelta(hours=hours)

    run_qs = AgentRun.objects.filter(started_at__gte=since)
    run_counts = {row["status"]: row["count"] for row in run_qs.values("status").annotate(count=Count("id"))}
    runs_total = run_qs.count()

    logs_qs = AgentLogEvent.objects.filter(created_at__gte=since)
    log_levels = {row["level"]: row["count"] for row in logs_qs.values("level").annotate(count=Count("id"))}
    log_steps = {
        row["step"]: row["count"]
        for row in logs_qs.values("step").annotate(count=Count("id")).order_by("-count")[:10]
    }

    latest_run = run_qs.order_by("-started_at").first()

    return {
        "window_hours": hours,
        "since": since,
        "runs_total": runs_total,
        "run_status_counts": run_counts,
        "log_total": logs_qs.count(),
        "log_level_counts": log_levels,
        "top_log_steps": log_steps,
        "latest_run": {
            "status": latest_run.status,
            "started_at": latest_run.started_at,
            "ended_at": latest_run.ended_at,
            "pages_processed": latest_run.pages_processed,
            "articles_created": latest_run.articles_created,
            "queued_urls": latest_run.queued_urls,
            "last_error": latest_run.last_error,
        }
        if latest_run
        else None,
    }


def _log_control_event(message: str, *, level: str = AgentLogEvent.LEVEL_INFO, metadata: dict | None = None) -> None:
    AgentLogEvent.objects.create(
        run=None,
        step=AgentLogEvent.STEP_LOOP_STATE,
        level=level,
        message=message[:255],
        metadata=metadata or {},
    )


class AgentProtectedView(APIView):
    authentication_classes = []
    permission_classes = [HasAgentControlToken]


class AgentConfigView(AgentProtectedView):
    def get(self, request):
        config = get_config()
        return Response(AgentConfigSerializer(config).data)

    def put(self, request):
        config = get_config()
        serializer = AgentConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class AgentLogsView(AgentProtectedView):
    def get(self, request):
        qs = AgentLogEvent.objects.order_by("-created_at")
        run_id = request.query_params.get("run_id")
        if run_id:
            qs = qs.filter(run_id=run_id)
        step = request.query_params.get("step")
        if step:
            qs = qs.filter(step=step)
        limit = _int_param(request.query_params.get("limit", "50"), default=50, min_value=1, max_value=200)
        logs = qs[:limit]
        serializer = AgentLogEventSerializer(logs, many=True)
        return Response({"results": serializer.data, "limit": limit})


class AgentControlLoginView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [ControlLoginThrottle]

    def post(self, request):
        serializer = AgentControlLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data["password"]

        if not control_password_configured():
            return Response(
                {"detail": "control_password_not_configured", "hint": "Set control password in Django admin."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not verify_control_password(password):
            _log_control_event(
                "control_login_failed",
                level=AgentLogEvent.LEVEL_WARN,
                metadata={"ip": request.META.get("REMOTE_ADDR", "")},
            )
            return Response({"detail": "invalid_credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        token, expires_in = issue_control_token()
        _log_control_event(
            "control_login_success",
            metadata={"ip": request.META.get("REMOTE_ADDR", ""), "expires_in": expires_in},
        )
        return Response(
            {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": expires_in,
            }
        )


class AgentControlBaseView(APIView):
    authentication_classes = []
    permission_classes = [HasAgentControlToken]


def _state() -> dict:
    return {
        "agent": agent_live_status(),
        "run_forever": worker_status(),
        "server_time": timezone.now(),
    }


class AgentControlStateView(AgentControlBaseView):
    def get(self, request):
        return Response(_state())


class AgentControlStatsView(AgentControlBaseView):
    def get(self, request):
        hours = _int_param(request.query_params.get("hours", "24"), default=24, min_value=1, max_value=168)
        return Response(_build_stats(hours))


class AgentControlLogsView(AgentControlBaseView):
    def get(self, request):
        qs = AgentLogEvent.objects.order_by("-created_at")
        run_id = request.query_params.get("run_id")
        if run_id:
            qs = qs.filter(run_id=run_id)
        step = request.query_params.get("step")
        if step:
            qs = qs.filter(step=step)
        level = request.query_params.get("level")
        if level:
            qs = qs.filter(level=level)

        limit = _int_param(request.query_params.get("limit", "100"), default=100, min_value=1, max_value=500)
        logs = qs[:limit]
        serializer = AgentLogEventSerializer(logs, many=True)
        return Response({"results": serializer.data, "limit": limit})


class AgentControlDashboardView(AgentControlBaseView):
    def get(self, request):
        hours = _int_param(request.query_params.get("hours", "24"), default=24, min_value=1, max_value=168)
        limit = _int_param(request.query_params.get("limit", "100"), default=100, min_value=1, max_value=300)
        logs = AgentLogEvent.objects.order_by("-created_at")[:limit]
        return Response(
            {
                "state": _state(),
                "stats": _build_stats(hours),
                "logs": AgentLogEventSerializer(logs, many=True).data,
            }
        )


class _ControlActionView(AgentControlBaseView):
    """POST writes a control flag; the worker container picks it up within ~1s."""

    action = None
    status_label = ""

    def post(self, request):
        state = type(self).action()
        return Response(
            {"status": self.status_label, "state": state, "agent": agent_live_status()},
            status=status.HTTP_202_ACCEPTED,
        )


class AgentControlStartView(_ControlActionView):
    action = staticmethod(request_start)
    status_label = "start_requested"


class AgentControlRunOnceView(_ControlActionView):
    action = staticmethod(request_run_once)
    status_label = "run_once_requested"


class AgentControlPauseView(_ControlActionView):
    action = staticmethod(request_pause)
    status_label = "pause_requested"


class AgentControlResumeView(_ControlActionView):
    action = staticmethod(request_resume)
    status_label = "resume_requested"


class AgentControlStopView(_ControlActionView):
    action = staticmethod(request_stop)
    status_label = "stop_requested"
