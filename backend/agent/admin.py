from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError

from .models import (
    AgentLogEvent,
    AgentRun,
    AgentConfig,
    MemoryState,
    NewsSource,
    PriceSource,
)
from .llm import LLMClient
from .models import provider_key_env
from .services import request_start


def _api_key_status(source) -> str:
    if (source.api_key or "").strip():
        return "set"
    env_name = provider_key_env(source.base_url)
    if env_name and source.resolved_api_key:
        return f"from {env_name}"
    if not source.requires_api_key:
        return "not needed"
    return f"missing (set {env_name})" if env_name else "missing"


class AgentConfigAdminForm(forms.ModelForm):
    control_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Set or rotate the agent control password used by the control login API.",
    )
    control_password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Re-enter control password.",
    )

    class Meta:
        model = AgentConfig
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        password = (cleaned.get("control_password") or "").strip()
        confirm = (cleaned.get("control_password_confirm") or "").strip()
        if password or confirm:
            if password != confirm:
                raise ValidationError("Control password and confirmation must match.")
            if len(password) < 12:
                raise ValidationError("Control password must be at least 12 characters.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        password = (self.cleaned_data.get("control_password") or "").strip()
        if password:
            instance.control_password_hash = make_password(password)
        if commit:
            instance.save()
        return instance


@admin.register(AgentConfig)
class AgentConfigAdmin(admin.ModelAdmin):
    form = AgentConfigAdminForm
    list_display = (
        "llm_enabled",
        "use_llm_summaries",
        "run_forever_enabled",
        "llm_model",
        "loop_interval_minutes",
        "price_loop_interval_seconds",
        "control_password_status",
    )
    readonly_fields = ("control_password_status",)
    actions = ["start_run_forever_loop", "test_llm_connection"]
    change_form_template = "admin/agent/agentconfig/change_form.html"

    fieldsets = (
        ("LLM", {
            "fields": (
                "llm_enabled",
                "use_llm_summaries",
                "llm_model",
                "llm_base_url",
                "llm_api_key",
                "llm_temperature",
                "llm_max_output_tokens",
            )
        }),
        ("Runtime", {
            "fields": (
                "run_forever_enabled",
                "run_forever_paused",
                "loop_interval_minutes",
                "price_loop_interval_seconds",
            )
        }),
        ("Sources", {
            "fields": (
                "max_items_per_source",
                "max_context_chars",
                "user_agent",
            )
        }),
        ("Prompts", {
            "fields": (
                "article_prompt_template",
                "filter_prompt_template",
                "signals_prompt_template",
                "writing_prompt_template",
                "aftermath_prompt_template",
            )
        }),
        ("Aftermath Articles", {
            "fields": (
                "aftermath_min_importance_score",
                "aftermath_delay_hour_minutes",
                "aftermath_delay_day_minutes",
                "aftermath_delay_week_minutes",
                "aftermath_delay_month_minutes",
            )
        }),
        ("Memory", {
            "fields": (
                "memory_enabled",
                "memory_token_limit",
            )
        }),
        ("Control Access", {
            "fields": (
                "control_password_status",
                "control_token_ttl_minutes",
                "control_password",
                "control_password_confirm",
            )
        }),
    )

    @admin.display(description="Control Password")
    def control_password_status(self, obj):
        if obj and (getattr(obj, "control_password_hash", "") or "").strip():
            return "configured"
        return "not set"

    def start_run_forever_loop(self, request, queryset):
        request_start()
        self.message_user(request, "Worker loop enabled; the agent container picks it up within seconds.", level=messages.SUCCESS)

    start_run_forever_loop.short_description = "Start run_forever loop"

    @admin.action(description="Test LLM connection")
    def test_llm_connection(self, request, queryset):
        config = queryset.first()
        llm = LLMClient(config)
        if not llm.enabled:
            self.message_user(
                request, "LLM is disabled or has no API key (set it here or LLM_API_KEY in .env).", level=messages.WARNING
            )
            return
        if llm.generate_json('Reply with the JSON object {"ok": true}.') is not None:
            self.message_user(request, f"LLM OK: {config.llm_model} answered.", level=messages.SUCCESS)
        else:
            self.message_user(request, f"LLM call failed: {llm.last_error}", level=messages.ERROR)

    def response_change(self, request, obj):
        if "_start_run_forever" in request.POST:
            request_start()
            self.message_user(request, "Worker loop enabled; the agent container picks it up within seconds.", level=messages.SUCCESS)
            return self.response_post_save_change(request, obj)
        return super().response_change(request, obj)


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = (
        "status",
        "started_at",
        "ended_at",
        "pages_processed",
        "articles_created",
        "use_llm_filtering",
    )
    list_filter = ("status",)
    ordering = ("-started_at",)


@admin.register(AgentLogEvent)
class AgentLogEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "step", "message", "seed_url", "url")
    list_filter = ("level", "step")
    search_fields = ("message", "seed_url", "url", "content")
    ordering = ("-created_at",)


@admin.register(NewsSource)
class NewsSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "source_type", "enabled", "api_key_set", "last_fetched_at", "failure_count")
    list_filter = ("source_type", "enabled")
    search_fields = ("name", "base_url", "query", "topic")
    readonly_fields = ("last_fetched_at", "failure_count", "last_error", "backoff_until")
    fieldsets = (
        ("Source", {"fields": ("name", "source_type", "enabled", "base_url")}),
        ("Authentication", {"fields": ("api_key", "api_key_param", "api_key_header")}),
        (
            "Query Mapping",
            {
                "fields": (
                    "query_param",
                    "query",
                    "topic_param",
                    "topic",
                    "language_param",
                    "language",
                    "region_param",
                    "region",
                    "since_param",
                    "since_format",
                )
            },
        ),
        (
            "Runtime",
            {
                "fields": (
                    "rate_limit_seconds",
                    "last_fetched_at",
                    "failure_count",
                    "backoff_until",
                    "last_error",
                )
            },
        ),
    )

    @admin.display(description="API key")
    def api_key_set(self, obj):
        return _api_key_status(obj)


@admin.register(PriceSource)
class PriceSourceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "chart_label",
        "symbol",
        "source_type",
        "enabled",
        "api_key_set",
        "last_fetched_at",
        "failure_count",
    )
    list_filter = ("source_type", "enabled")
    search_fields = ("name", "chart_label", "symbol", "base_url")
    ordering = ("name",)
    readonly_fields = ("last_fetched_at", "failure_count", "last_error", "backoff_until")
    fieldsets = (
        ("Source", {"fields": ("name", "chart_label", "symbol", "source_type", "enabled", "base_url")}),
        ("Authentication", {"fields": ("api_key", "api_key_param", "api_key_header")}),
        ("Provider Mapping", {"fields": ("symbol_param",)}),
        ("Parsing", {"fields": ("price_regex", "price_scale")}),
        (
            "Runtime",
            {
                "fields": (
                    "rate_limit_seconds",
                    "last_fetched_at",
                    "failure_count",
                    "backoff_until",
                    "last_error",
                )
            },
        ),
    )

    @admin.display(description="API key")
    def api_key_set(self, obj):
        return _api_key_status(obj)


@admin.register(MemoryState)
class MemoryStateAdmin(admin.ModelAdmin):
    list_display = ("updated_at", "created_at")
