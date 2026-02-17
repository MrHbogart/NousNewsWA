<template>
  <section class="space-y-6">
    <NuxtLink
      to="/"
      class="inline-flex items-center gap-2 text-xs text-ink-500 transition hover:text-ink-900"
    >
      <span class="h-px w-10 bg-ink-900/20" />
      Back to brief
    </NuxtLink>

    <div
      v-if="pending"
      class="rounded-2xl border border-ink-900/10 bg-white p-6 text-ink-500"
    >
      Loading report...
    </div>

    <div
      v-else-if="error"
      class="rounded-2xl border border-ember-500/40 bg-white p-6 text-ember-600"
    >
      This report could not be loaded. Verify the article ID and API base URL.
    </div>

    <article v-else class="article-layout">
      <Transition name="update-banner">
        <div
          v-if="hasPendingArticleUpdate"
          class="rounded-xl border border-sky-500/30 bg-sky-50 px-4 py-3 text-sky-800"
        >
          <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p class="text-sm">
              A newer version of this article is available.
            </p>
            <button
              type="button"
              class="inline-flex items-center justify-center rounded-md border border-sky-500/40 bg-white px-3 py-1.5 text-xs font-medium uppercase tracking-[0.08em] text-sky-700 transition hover:bg-sky-100"
              @click="applyPendingUpdate"
            >
              Load update
            </button>
          </div>
        </div>
      </Transition>

      <Transition name="article-fade" mode="out-in">
        <div :key="articleRenderKey" class="article-stack">
      <div class="rounded-2xl border border-ink-900/10 bg-white p-6 sm:p-8">
        <p class="text-xs text-ink-500">
          Hourly market brief
          <span v-if="publishedLabel"> · {{ publishedLabel }}</span>
        </p>
        <h1 class="mt-3 text-3xl text-ink-900 sm:text-4xl">
          {{ displayedArticle?.title || 'Untitled report' }}
        </h1>
        <p v-if="cleanSummary" class="article-lead">
          {{ cleanSummary }}
        </p>
        <p class="mt-3 text-sm text-ink-500">
          Updated {{ updatedLabel || 'unknown time' }}
        </p>
      </div>

      <div class="article-body-card rounded-2xl border border-ink-900/10 bg-white p-6 sm:p-8">
        <div v-if="articleParagraphs.length" class="article-body-content">
          <p v-for="(paragraph, index) in articleParagraphs" :key="`paragraph-${index}`">
            {{ paragraph }}
          </p>
        </div>
        <p v-else class="text-ink-400">No article body available yet.</p>
      </div>

      <div
        v-if="priceSeriesList.length"
        class="news-chart"
        :style="{ '--chart-count': chartTabs.length }"
      >
        <div class="news-chart-tabs" role="tablist" aria-label="Related charts">
          <button
            v-for="(item, index) in chartTabs"
            :key="`${item}-${index}`"
            class="news-chart-tab"
            :class="{ 'is-active': chartOpen && activeChart === index }"
            type="button"
            role="tab"
            :aria-selected="chartOpen && activeChart === index"
            @click="onChartTab(index)"
          >
            {{ item }}
          </button>
        </div>
        <div class="news-chart-panel" :class="{ 'is-open': chartOpen }">
          <div
            class="news-chart-track"
            :style="{ transform: `translateX(-${activeChart * (100 / chartTabs.length)}%)` }"
          >
            <div
              v-for="(label, chartIndex) in chartTabs"
              :key="`chart-${chartIndex}`"
              class="news-chart-frame"
            >
              <svg
                class="news-chart-canvas"
                :viewBox="`0 0 ${chart.width} ${chart.height}`"
                role="img"
                :aria-label="`${label} candlestick chart`"
              >
                <g v-if="chartDataSets[chartIndex]?.candles.length">
                  <g class="news-chart-grid">
                    <line
                      v-for="(tick, idx) in chartDataSets[chartIndex].yTicks"
                      :key="`y-grid-${chartIndex}-${idx}`"
                      :x1="chart.bounds.left"
                      :x2="chart.bounds.right"
                      :y1="tick.y"
                      :y2="tick.y"
                    />
                    <line
                      v-for="(tick, idx) in chartDataSets[chartIndex].xTicks"
                      :key="`x-grid-${chartIndex}-${idx}`"
                      :y1="chart.bounds.top"
                      :y2="chart.bounds.bottom"
                      :x1="tick.x"
                      :x2="tick.x"
                    />
                  </g>
                  <g class="news-chart-axis">
                    <text
                      v-for="(tick, idx) in chartDataSets[chartIndex].yTicks"
                      :key="`y-label-${chartIndex}-${idx}`"
                      :x="chart.bounds.left - 6"
                      :y="tick.y + 4"
                      text-anchor="end"
                    >
                      {{ tick.label }}
                    </text>
                    <text
                      v-for="(tick, idx) in chartDataSets[chartIndex].xTicks"
                      :key="`x-label-${chartIndex}-${idx}`"
                      :x="tick.x"
                      :y="chart.bounds.bottom + 18"
                      text-anchor="middle"
                    >
                      {{ tick.label }}
                    </text>
                  </g>
                  <g class="news-chart-guide">
                    <line
                      v-for="(guide, idx) in (chartDataSets[chartIndex]?.priceLines || [])"
                      :key="`guide-${chartIndex}-${idx}`"
                      :x1="chart.bounds.left"
                      :x2="chart.bounds.right"
                      :y1="guide.y"
                      :y2="guide.y"
                      :stroke="guide.color"
                      stroke-width="1.2"
                      stroke-dasharray="4 4"
                    />
                    <text
                      v-for="(guide, idx) in (chartDataSets[chartIndex]?.priceLines || [])"
                      v-if="guide && guide.kind !== 'last'"
                      :key="`guide-label-${chartIndex}-${idx}`"
                      :x="chart.width - 6"
                      :y="guide.kind === 'high' ? guide.y - 6 : guide.y + 12"
                      text-anchor="end"
                      :fill="guide.color"
                    >
                      {{ guide.label }}
                    </text>
                    <text
                      v-if="chartDataSets[chartIndex].lastPriceLabel"
                      :x="chart.width - 6"
                      :y="chart.bounds.top + 12"
                      text-anchor="end"
                      class="news-chart-last"
                    >
                      {{ chartDataSets[chartIndex].lastPriceLabel }}
                    </text>
                  </g>
                  <line
                    v-for="(candle, idx) in chartDataSets[chartIndex].candles"
                    :key="`wick-${chartIndex}-${idx}`"
                    :x1="candle.x"
                    :x2="candle.x"
                    :y1="candle.highY"
                    :y2="candle.lowY"
                    :stroke="candle.color"
                    stroke-width="1.4"
                    stroke-linecap="round"
                  />
                  <rect
                    v-for="(candle, idx) in chartDataSets[chartIndex].candles"
                    :key="`body-${chartIndex}-${idx}`"
                    :x="candle.bodyX"
                    :y="candle.bodyY"
                    :width="candle.bodyWidth"
                    :height="candle.bodyHeight"
                    :fill="candle.color"
                    rx="1"
                  />
                </g>
              </svg>
            </div>
          </div>
        </div>
      </div>

      <div v-if="relatedLinks.length" class="rounded-2xl border border-ink-900/10 bg-white p-6">
        <p class="text-xs uppercase tracking-[0.12em] text-ink-500">Related briefs</p>
        <ul class="mt-3 space-y-2 text-sm text-ink-700">
          <li v-for="item in relatedLinks" :key="item.uuid">
            <NuxtLink :to="`/articles/${item.slug || item.uuid}`" class="hover:text-ink-900">
              {{ item.title || 'Untitled brief' }}
            </NuxtLink>
          </li>
        </ul>
      </div>

      <div v-if="displayedArticle?.references?.length" class="rounded-2xl border border-ink-900/10 bg-white p-6">
        <p class="text-xs uppercase tracking-[0.12em] text-ink-500">References</p>
        <ul class="mt-3 space-y-2">
          <li v-for="ref in displayedArticle?.references || []" :key="ref">
            <a
              :href="ref"
              target="_blank"
              rel="noreferrer"
              class="inline-flex items-start text-sm text-ink-700 hover:text-ink-900 transition break-all"
              :title="ref"
            >
              <span class="inline-flex items-center gap-1.5 flex-1">
                {{ ref }}
                <svg class="w-3 h-3 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </span>
            </a>
          </li>
        </ul>
      </div>
      </div>
      </Transition>
    </article>
  </section>
</template>

<script setup>
const route = useRoute()
const api = useNewsApi()
const config = useRuntimeConfig()
const articleId = computed(() => String(route.params.id || ''))
const updateCheckIntervalMs = 15000
let articleUpdateTimer = null

function resetArticleScroll() {
  if (!process.client) return
  const main = document.querySelector('.app-main')
  if (main && typeof main.scrollTo === 'function') {
    main.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }
  window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
}

function cloneArticlePayload(payload) {
  if (!payload || typeof payload !== 'object') return null
  return JSON.parse(JSON.stringify(payload))
}

function articleFingerprint(payload) {
  if (!payload || typeof payload !== 'object') return ''
  const seriesSignature = (payload.price_series || [])
    .map((series) => {
      const candles = series.candles || []
      const last = candles[candles.length - 1] || {}
      return `${series.symbol || ''}:${candles.length}:${last.timestamp || ''}:${last.close || ''}`
    })
    .join(';')
  return [
    payload.updated_at || '',
    payload.title || '',
    payload.summary || '',
    payload.article_content || '',
    seriesSignature,
  ].join('|')
}

function sanitizeArticleText(value = '') {
  return String(value || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<blockquote[^>]*class=["'][^"']*(twitter-tweet|instagram-media|tiktok-embed)[^"']*["'][^>]*>[\s\S]*?<\/blockquote>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&rsquo;/gi, "'")
    .replace(/&ldquo;/gi, '"')
    .replace(/&rdquo;/gi, '"')
    .replace(/&ndash;/gi, '-')
    .replace(/&mdash;/gi, '-')
    .replace(/\s+/g, ' ')
    .trim()
}

const pendingArticleUpdate = ref(null)
const displayedArticle = ref(null)

const { data: articleData, pending, error, refresh: refreshArticle } = await useAsyncData(
  () => `article-${articleId.value}`,
  () => api.getArticle(articleId.value),
  { server: false }
)

watch(articleId, () => {
  refreshArticle()
})

watch(
  articleData,
  (value) => {
    if (!value) return
    if (!displayedArticle.value) {
      displayedArticle.value = cloneArticlePayload(value)
      pendingArticleUpdate.value = null
    }
  },
  { immediate: true }
)

watch(
  () => displayedArticle.value?.slug,
  async (slug) => {
    if (!slug) return
    if (String(route.params.id) === slug) return
    await navigateTo(`/articles/${slug}`, { replace: true })
  }
)

async function checkArticleUpdate() {
  if (pending.value || error.value || !displayedArticle.value) return
  try {
    const latest = await api.getArticle(route.params.id)
    if (!latest) return
    const currentSig = articleFingerprint(displayedArticle.value)
    const latestSig = articleFingerprint(latest)
    if (latestSig && latestSig !== currentSig) {
      pendingArticleUpdate.value = cloneArticlePayload(latest)
    }
  } catch {
    // Ignore polling errors for update checks.
  }
}

function applyPendingUpdate() {
  if (!pendingArticleUpdate.value) return
  displayedArticle.value = cloneArticlePayload(pendingArticleUpdate.value)
  pendingArticleUpdate.value = null
}

onMounted(() => {
  resetArticleScroll()
  articleUpdateTimer = setInterval(() => {
    checkArticleUpdate()
  }, updateCheckIntervalMs)
})

onBeforeUnmount(() => {
  if (articleUpdateTimer) {
    clearInterval(articleUpdateTimer)
    articleUpdateTimer = null
  }
})

watch(
  () => route.fullPath,
  () => {
    resetArticleScroll()
  }
)

const hasPendingArticleUpdate = computed(() => Boolean(pendingArticleUpdate.value))
const articleRenderKey = computed(() => articleFingerprint(displayedArticle.value))
const publishedLabel = computed(() => formatDate(displayedArticle.value?.hour_start))
const updatedLabel = computed(() => formatDate(displayedArticle.value?.updated_at))
const relatedLinks = computed(() => {
  const items = displayedArticle.value?.related_articles || []
  return items.filter((item) => item.kind === 'side').slice(0, 2)
})
const cleanSummary = computed(() => sanitizeArticleText(displayedArticle.value?.summary || ''))
const articleParagraphs = computed(() => {
  const raw = sanitizeArticleText(displayedArticle.value?.article_content || '').replace(/\r\n/g, '\n').trim()
  if (!raw) return []
  return raw
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
})
const chartOpen = ref(true)
const activeChart = ref(0)
const priceSeriesList = computed(() => displayedArticle.value?.price_series || [])
const chartTabs = computed(() =>
  priceSeriesList.value.map((series) => series.label || series.symbol || "Asset")
)

const chart = {
  width: 720,
  height: 280,
  margin: { top: 12, right: 0, bottom: 36, left: 20 },
  get bounds() {
    return {
      left: this.margin.left,
      right: this.width - this.margin.right,
      top: this.margin.top,
      bottom: this.height - this.margin.bottom,
    }
  },
}
const chartDataSets = computed(() =>
  priceSeriesList.value.map((series) => buildChartData(series.candles || [], series.expected_count))
)

function buildChartData(rows, expectedCount) {
  const bounds = chart.bounds
  if (!rows.length) return { candles: [], yTicks: [], xTicks: [], priceLines: [], lastPriceLabel: "" }
  const slotCount = Math.max(rows.length, Number(expectedCount) || rows.length)
  const highs = rows.map((row) => Number(row.high))
  const lows = rows.map((row) => Number(row.low))
  const max = Math.max(...highs)
  const min = Math.min(...lows)
  const range = Math.max(1e-6, max - min)
  const scaleY = (value) =>
    bounds.top + ((max - value) / range) * (bounds.bottom - bounds.top)
  const step = (bounds.right - bounds.left) / slotCount
  const bodyWidth = Math.max(4, step * 0.6)

  const candles = rows.map((row, index) => {
    const openValue = Number(row.open)
    const closeValue = Number(row.close)
    const highValue = Number(row.high)
    const lowValue = Number(row.low)
    const centerX = bounds.left + index * step + step / 2
    const openY = scaleY(openValue)
    const closeY = scaleY(closeValue)
    const highY = scaleY(highValue)
    const lowY = scaleY(lowValue)
    const bodyHeight = Math.max(2, Math.abs(openY - closeY))
    const bodyY = Math.min(openY, closeY)
    const color = closeValue >= openValue ? '#2f7f5e' : '#b34b4b'
    return {
      x: centerX,
      highY,
      lowY,
      bodyX: centerX - bodyWidth / 2,
      bodyY,
      bodyWidth,
      bodyHeight,
      color,
    }
  })
  const yTicks = buildYTicks(bounds, min, max)
  const xTicks = buildXTicks(rows, bounds, slotCount)
  const last = rows[rows.length - 1]
  const priceLines = [
    buildPriceGuide("High", max, scaleY, "#1f6f52", "high"),
    buildPriceGuide("Last", last?.close ?? max, scaleY, "#1d2326", "last"),
    buildPriceGuide("Low", min, scaleY, "#a04343", "low"),
  ]
  const lastClose = Number(last?.close)
  const lastPriceLabel = Number.isFinite(lastClose) ? `Last ${lastClose.toFixed(2)}` : ""
  return { candles, yTicks, xTicks, priceLines, lastPriceLabel }
}

function buildYTicks(bounds, min, max) {
  const tickCount = 5
  const ticks = []
  for (let i = 0; i < tickCount; i += 1) {
    const t = i / (tickCount - 1)
    const value = max - (max - min) * t
    const y = bounds.top + ((max - value) / Math.max(1e-6, max - min)) * (bounds.bottom - bounds.top)
    ticks.push({ y, label: value.toFixed(2) })
  }
  return ticks
}

function buildXTicks(rows, bounds, slotCount) {
  const tickCount = 4
  const step = (bounds.right - bounds.left) / Math.max(1, slotCount)
  const ticks = []
  for (let i = 0; i < tickCount; i += 1) {
    const index = Math.floor((slotCount - 1) * (i / (tickCount - 1)))
    const x = bounds.left + index * step + step / 2
    const label = index < rows.length ? formatTimeLabel(rows[index]?.timestamp || '') : ''
    ticks.push({ x, label })
  }
  return ticks
}

function formatTimeLabel(value) {
  if (!value) return ''
  const parts = value.split(' ')
  if (parts.length < 2) return value
  return parts[1].slice(0, 5)
}

function buildPriceGuide(label, value, scaleY, color, kind) {
  return {
    y: scaleY(value),
    label: `${label} ${value.toFixed(2)}`,
    color,
    kind,
  }
}

function onChartTab(index) {
  if (chartOpen.value && activeChart.value === index) {
    chartOpen.value = false
    return
  }
  activeChart.value = index
  chartOpen.value = true
}

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

useHead(() => ({
  title: displayedArticle.value?.title ? `NousNews · ${displayedArticle.value.title}` : 'NousNews · Report',
  meta: [
    {
      name: 'description',
      content: displayedArticle.value?.summary
        ? displayedArticle.value.summary.slice(0, 160)
        : 'NousNews report details.',
    },
    { property: 'og:title', content: displayedArticle.value?.title || 'NousNews report' },
    {
      property: 'og:description',
      content: displayedArticle.value?.summary
        ? displayedArticle.value.summary.slice(0, 160)
        : 'NousNews report details.',
    },
    { property: 'og:type', content: 'article' },
    {
      property: 'og:url',
      content: `${config.public.siteDomain.replace(/\/$/, '')}/articles/${displayedArticle.value?.slug || articleId.value}`,
    },
  ],
  link: [
    {
      rel: 'canonical',
      href: `${config.public.siteDomain.replace(/\/$/, '')}/articles/${displayedArticle.value?.slug || articleId.value}`,
    },
  ],
}))
</script>

<style scoped>
.article-fade-enter-active,
.article-fade-leave-active {
  transition: opacity 260ms ease, transform 260ms ease;
}

.article-fade-enter-from,
.article-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

.update-banner-enter-active,
.update-banner-leave-active {
  transition: opacity 220ms ease, transform 220ms ease;
}

.update-banner-enter-from,
.update-banner-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.article-layout {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.article-stack {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.article-lead {
  margin-top: 1rem;
  font-size: 1.04rem;
  line-height: 1.8;
  color: var(--ink-soft);
  max-width: 68ch;
}

.article-body-content {
  max-width: 72ch;
  color: var(--ink);
  font-size: 1.04rem;
  line-height: 1.9;
}

.article-body-content p {
  margin: 0 0 1.1em;
}

.article-body-content p:last-child {
  margin-bottom: 0;
}

@media (max-width: 640px) {
  .article-lead {
    font-size: 1rem;
    line-height: 1.72;
  }

  .article-body-content {
    font-size: 1rem;
    line-height: 1.8;
  }
}
</style>
