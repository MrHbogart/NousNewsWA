from rest_framework import serializers

from agent.models import AgentConfig, AgentLogEvent


class AgentConfigSerializer(serializers.ModelSerializer):
    control_password_set = serializers.SerializerMethodField()

    class Meta:
        model = AgentConfig
        fields = [
            "id",
            "llm_enabled",
            "use_llm_summaries",
            "llm_model",
            "llm_base_url",
            "llm_api_key",
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
            "memory_enabled",
            "memory_token_limit",
            "run_forever_enabled",
            "control_token_ttl_minutes",
            "control_password_set",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_control_password_set(self, obj) -> bool:
        return bool((getattr(obj, "control_password_hash", "") or "").strip())


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
