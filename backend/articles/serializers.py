from rest_framework import serializers
from bs4 import BeautifulSoup

from articles.models import CardArticle
from articles.slugging import build_article_slug
from articles.services import aggregate_candles, enabled_price_source_labels, resolve_timeframe


def _sanitize_article_text(value: str, *, keep_paragraphs: bool = False) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
        tag.decompose()
    for node in soup.select("blockquote.twitter-tweet, blockquote.instagram-media, blockquote.tiktok-embed"):
        node.decompose()
    extracted = soup.get_text("\n" if keep_paragraphs else " ")
    if keep_paragraphs:
        extracted = extracted.replace("\xa0", " ")
        extracted = extracted.replace("\r\n", "\n")
        extracted = extracted.replace("\r", "\n")
        extracted = "\n".join(line.strip() for line in extracted.split("\n"))
        extracted = "\n\n".join(part for part in extracted.split("\n\n") if part.strip())
        return extracted.strip()
    return " ".join(extracted.replace("\xa0", " ").split()).strip()


class PriceSeriesMixin:
    def _enabled_price_source_symbol_labels(self) -> dict[str, str]:
        # One query per serializer tree (list views share the context dict).
        if "_price_labels" not in self.context:
            self.context["_price_labels"] = enabled_price_source_labels()
        return self.context["_price_labels"]

    def _serialize_price_series(
        self,
        card,
        include_detail: bool = False,
        *,
        window_start=None,
        window_end=None,
    ) -> list[dict]:
        interval_minutes, max_buckets, timeframe_label = resolve_timeframe(card.timeframe)
        start = window_start or card.period_start
        end = window_end or card.period_end
        if window_start is not None or window_end is not None:
            # Custom window (e.g. an aftermath article's post-brief period) is sized
            # independently of the card's own timeframe bucket count.
            span_minutes = max(0, (end - start).total_seconds() / 60)
            max_buckets = max(1, int(-(-span_minutes // max(1, interval_minutes))))  # ceil div
        enabled_symbol_labels = self._enabled_price_source_symbol_labels()
        if not enabled_symbol_labels:
            return []
        series_payloads: list[dict] = []

        for asset in card.assets.select_related("series").all().order_by("series__symbol"):
            symbol = asset.series.symbol
            if symbol not in enabled_symbol_labels:
                continue

            candles = aggregate_candles(
                series=asset.series,
                start=start,
                end=end,
                interval_minutes=interval_minutes,
                max_buckets=max_buckets,
            )
            formatted_candles = [
                {
                    "timestamp": c["timestamp"].strftime("%Y-%m-%d %H:%M"),
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                }
                for c in candles
            ]
            payload = {
                "label": enabled_symbol_labels.get(symbol) or asset.label or asset.series.label or symbol,
                "symbol": symbol,
                "candles": formatted_candles,
                "expected_count": max_buckets,
            }
            if include_detail:
                payload["timeframe"] = timeframe_label
                payload["candle_count"] = len(formatted_candles)
            series_payloads.append(payload)

        return series_payloads


class CardArticleListSerializer(PriceSeriesMixin, serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid", read_only=True)
    timeframe = serializers.CharField(source="card.timeframe", read_only=True)
    period_start = serializers.DateTimeField(source="card.period_start", read_only=True)
    period_end = serializers.DateTimeField(source="card.period_end", read_only=True)
    hour_start = serializers.DateTimeField(source="card.period_start", read_only=True)
    source_name = serializers.CharField(source="card.source_name", read_only=True)
    published_at = serializers.DateTimeField(source="card.published_at", read_only=True)
    summary = serializers.SerializerMethodField()
    importance_score = serializers.IntegerField(source="card.importance_score", read_only=True)
    importance_reason = serializers.CharField(source="card.importance_reason", read_only=True)
    is_daily_summary = serializers.SerializerMethodField()
    price_series = serializers.SerializerMethodField()

    slug = serializers.SerializerMethodField()

    class Meta:
        model = CardArticle
        fields = [
            "id",
            "slug",
            "timeframe",
            "period_start",
            "period_end",
            "hour_start",
            "published_at",
            "title",
            "summary",
            "source_name",
            "importance_score",
            "importance_reason",
            "kind",
            "is_daily_summary",
            "price_series",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_summary(self, obj):
        return _sanitize_article_text(obj.summary or "", keep_paragraphs=False)

    def get_is_daily_summary(self, obj):
        return obj.card.timeframe in ["day", "week", "month"]

    def get_price_series(self, obj):
        return self._serialize_price_series(obj.card, include_detail=False)

    def get_slug(self, obj):
        if obj.slug:
            return obj.slug
        title = (obj.title or obj.card.title or "").strip()
        return build_article_slug(
            title=title,
            period_start=obj.card.period_start,
            article_uuid=obj.uuid,
            kind=obj.kind,
        )


class CardArticleDetailSerializer(PriceSeriesMixin, serializers.ModelSerializer):
    slug = serializers.SerializerMethodField()
    id = serializers.UUIDField(source="uuid", read_only=True)
    timeframe = serializers.CharField(source="card.timeframe", read_only=True)
    period_start = serializers.DateTimeField(source="card.period_start", read_only=True)
    period_end = serializers.DateTimeField(source="card.period_end", read_only=True)
    hour_start = serializers.DateTimeField(source="card.period_start", read_only=True)
    source_name = serializers.CharField(source="card.source_name", read_only=True)
    article_count = serializers.IntegerField(source="card.article_count", read_only=True)
    published_at = serializers.DateTimeField(source="card.published_at", read_only=True)
    summary = serializers.SerializerMethodField()
    importance_score = serializers.IntegerField(source="card.importance_score", read_only=True)
    importance_reason = serializers.CharField(source="card.importance_reason", read_only=True)
    is_daily_summary = serializers.SerializerMethodField()
    price_series = serializers.SerializerMethodField()
    related_articles = serializers.SerializerMethodField()
    article_content = serializers.SerializerMethodField()
    aftermath = serializers.SerializerMethodField()

    class Meta:
        model = CardArticle
        fields = [
            "id",
            "slug",
            "timeframe",
            "period_start",
            "period_end",
            "hour_start",
            "published_at",
            "title",
            "summary",
            "article_content",
            "impacts",
            "references",
            "article_count",
            "source_name",
            "importance_score",
            "importance_reason",
            "kind",
            "is_daily_summary",
            "price_series",
            "related_articles",
            "aftermath",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_summary(self, obj):
        return _sanitize_article_text(obj.summary or "", keep_paragraphs=False)

    def get_article_content(self, obj):
        return _sanitize_article_text(obj.body or "", keep_paragraphs=True)

    def get_is_daily_summary(self, obj):
        return obj.card.timeframe in ["day", "week", "month"]

    def get_slug(self, obj):
        if obj.slug:
            return obj.slug
        title = (obj.title or obj.card.title or "").strip()
        return build_article_slug(
            title=title,
            period_start=obj.card.period_start,
            article_uuid=obj.uuid,
            kind=obj.kind,
        )

    def get_price_series(self, obj):
        if obj.kind == CardArticle.KIND_AFTERMATH and obj.aftermath_price_until:
            return self._serialize_price_series(
                obj.card,
                include_detail=True,
                window_start=obj.card.period_end,
                window_end=obj.aftermath_price_until,
            )
        return self._serialize_price_series(obj.card, include_detail=True)

    def get_aftermath(self, obj):
        if obj.kind != CardArticle.KIND_MAIN:
            return None
        aftermath = obj.card.articles.filter(kind=CardArticle.KIND_AFTERMATH).values("uuid", "slug", "title").first()
        if not aftermath:
            return None
        return {
            "uuid": aftermath["uuid"],
            "slug": aftermath["slug"],
            "title": aftermath["title"],
        }

    def get_related_articles(self, obj):
        related_qs = (
            obj.card.articles.exclude(id=obj.id)
            .order_by("kind", "created_at")
            .values("uuid", "title", "kind", "slug")
        )
        related = []
        for item in related_qs:
            title = (item.get("title") or "").strip()
            slug = item.get("slug") or build_article_slug(
                title=title,
                period_start=obj.card.period_start,
                article_uuid=item.get("uuid"),
                kind=item.get("kind") or CardArticle.KIND_SIDE,
            )
            related.append({"uuid": item.get("uuid"), "title": item.get("title"), "kind": item.get("kind"), "slug": slug})
        return related
