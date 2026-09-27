from rest_framework import serializers

from agent.models import AgentConfig, AgentLogEvent


class AgentConfigSerializer(serializers.ModelSerializer):
    control_password_set = serializers.SerializerMethodField()
    llm_api_key_set = serializers.SerializerMethodField()
    llm_api_key = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=255)

    class Meta:
        model = AgentConfig
        fields = [
            "id",
            "llm_enabled",
            "use_llm_summaries",
            "llm_model",
            "llm_base_url",
            "llm_api_key",
            "llm_api_key_set",
            "llm_temperature",
            "llm_max_output_tokens",
            "loop_interval_minutes",
            "price_loop_interval_seconds",
            "max_items_per_source",
            "max_context_chars",
            "user_agent",
            "article_prompt_template",
            "filter_prompt_template",
            "signals_prompt_template",
            "writing_prompt_template",
            "aftermath_prompt_template",
            "aftermath_min_importance_score",
            "aftermath_delay_hour_minutes",
            "aftermath_delay_day_minutes",
            "aftermath_delay_week_minutes",
            "aftermath_delay_month_minutes",
            "memory_enabled",
            "memory_token_limit",
            "run_forever_enabled",
            "control_token_ttl_minutes",
            "control_password_set",
            "created_at",
            "updated_at",
        ]
        # llm_base_url is admin-only: with the API key attached, changing it
        # via the control API could send the key to an arbitrary host.
        read_only_fields = ["llm_base_url", "created_at", "updated_at"]

    def get_control_password_set(self, obj) -> bool:
        return bool((getattr(obj, "control_password_hash", "") or "").strip())

    def get_llm_api_key_set(self, obj) -> bool:
        return bool((getattr(obj, "llm_api_key", "") or "").strip())


class AgentLogEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentLogEvent
        fields = [
            "id",
            "run",
            "seed_url",
            "url",
            "step",
            "level",
            "message",
            "content",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


class AgentControlLoginSerializer(serializers.Serializer):
    password = serializers.CharField(trim_whitespace=False, min_length=8, max_length=256)
