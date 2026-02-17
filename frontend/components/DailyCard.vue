<template>
  <div class="daily-card">
    <div class="daily-card-divider">
      <div class="daily-card-line"></div>
      <div class="daily-card-label">{{ formattedDate }}</div>
      <div class="daily-card-line"></div>
    </div>

    <div class="daily-card-content">
      <div class="daily-card-badge">24-Hour Summary</div>

      <div class="daily-card-header">
        <h2 class="daily-card-title">{{ card.title || 'Daily Market Summary' }}</h2>
        <div class="daily-card-header-right">
          <span class="daily-card-time">{{ formatDateRange(card) }}</span>
          <div class="daily-card-importance" :class="`level-${importanceScore}`" :aria-label="importanceTooltip" :title="importanceTooltip">
            <span
              v-for="index in importanceScore"
              :key="`daily-importance-${card.id || card.slug || 'card'}-${index}`"
              class="daily-card-importance-triangle"
            >
              <svg viewBox="0 0 12 10" fill="currentColor" aria-hidden="true">
                <path d="M6 1L11 9H1L6 1Z" />
              </svg>
            </span>
          </div>
        </div>
      </div>

      <div class="daily-card-body">
        <div class="daily-card-text">
          <p class="daily-card-summary">{{ card.summary || 'Comprehensive analysis of today\'s market movements.' }}</p>
          <NuxtLink v-if="showReadMore" :to="`/articles/${card.slug || card.id}`" class="daily-card-readmore">
            Read full analysis
          </NuxtLink>
        </div>

        <div v-if="hasPriceSeries" class="daily-card-chart-controls" role="tablist" aria-label="Daily related charts">
          <button
            v-for="(series, index) in priceSeries"
            :key="`daily-series-${card.id}-${index}`"
            class="daily-card-chart-tab"
            :class="{ 'is-active': activeSeriesIndex === index }"
            :aria-selected="chartsOpen && activeSeriesIndex === index"
            @click="onChartTab(index)"
          >
            {{ series.label || series.symbol || 'Asset' }}
          </button>
        </div>

        <div v-if="hasPriceSeries" class="daily-card-charts" :class="{ 'is-open': chartsOpen }">
          <div class="daily-card-chart-wrapper">
            <Transition :name="chartTransitionName" mode="out-in">
              <svg
                v-if="currentSeriesData.candles.length"
                :key="`daily-chart-${activeSeriesIndex}`"
                class="daily-card-chart-canvas"
                :viewBox="`0 0 ${chartConfig.width} ${chartConfig.height}`"
                role="img"
                :aria-label="`${priceSeries[activeSeriesIndex]?.label} 24-hour candlestick chart`"
              >
                <g class="chart-grid">
                  <line
                    v-for="(tick, idx) in currentSeriesData.yTicks"
                    :key="`y-grid-${idx}`"
                    :x1="chartConfig.bounds.left"
                    :x2="chartConfig.bounds.right"
                    :y1="tick.y"
                    :y2="tick.y"
                  />
                  <line
                    v-for="(tick, idx) in currentSeriesData.xTicks"
                    :key="`x-grid-${idx}`"
                    :y1="chartConfig.bounds.top"
                    :y2="chartConfig.bounds.bottom"
                    :x1="tick.x"
                    :x2="tick.x"
                  />
                </g>

                <g class="chart-axis">
                  <text
                    v-for="(tick, idx) in currentSeriesData.yTicks"
                    :key="`y-label-${idx}`"
                    :x="chartConfig.bounds.left - 6"
                    :y="tick.y + 4"
                    text-anchor="end"
                  >
                    {{ tick.label }}
                  </text>
                  <text
                    v-for="(tick, idx) in currentSeriesData.xTicks"
                    :key="`x-label-${idx}`"
                    :x="tick.x"
                    :y="chartConfig.bounds.bottom + 18"
                    text-anchor="middle"
                  >
                    {{ tick.label }}
                  </text>
                </g>

                <g class="chart-guide">
                  <line
                    v-for="(guide, idx) in (currentSeriesData.priceLines || [])"
                    :key="`guide-${idx}`"
                    :x1="chartConfig.bounds.left"
                    :x2="chartConfig.bounds.right"
                    :y1="guide.y"
                    :y2="guide.y"
                    :stroke="guide.color"
                    stroke-width="1.2"
                    stroke-dasharray="4 4"
                  />
                  <text
                    v-for="(guide, idx) in (currentSeriesData.priceLines || [])"
                    v-if="guide && guide.kind !== 'last'"
                    :key="`guide-label-${idx}`"
                    :x="chartConfig.width - 6"
                    :y="guide.kind === 'high' ? guide.y - 6 : guide.y + 12"
                    text-anchor="end"
                    :fill="guide.color"
                  >
                    {{ guide.label }}
                  </text>
                  <text
                    v-if="currentSeriesData.lastPriceLabel"
                    :x="chartConfig.width - 6"
                    :y="chartConfig.bounds.top + 12"
                    text-anchor="end"
                    class="chart-last-price"
                  >
                    {{ currentSeriesData.lastPriceLabel }}
                  </text>
                </g>

                <line
                  v-for="(candle, idx) in currentSeriesData.candles"
                  :key="`wick-${idx}`"
                  :x1="candle.x"
                  :x2="candle.x"
                  :y1="candle.highY"
                  :y2="candle.lowY"
                  :stroke="candle.color"
                  stroke-width="1.4"
                  stroke-linecap="round"
                />

                <rect
                  v-for="(candle, idx) in currentSeriesData.candles"
                  :key="`body-${idx}`"
                  :x="candle.bodyX"
                  :y="candle.bodyY"
                  :width="candle.bodyWidth"
                  :height="candle.bodyHeight"
                  :fill="candle.color"
                  rx="1"
                />
              </svg>
            </Transition>
            <div v-if="!currentSeriesData.candles.length" class="chart-empty">
              No price data available
            </div>
          </div>
        </div>

        <div v-if="relatedArticleId" class="daily-card-related">
          <p class="daily-card-related-label">Related Economics Article</p>
          <NuxtLink :to="`/articles/${relatedArticleId}`" class="daily-card-related-link">
            View comprehensive economic analysis →
          </NuxtLink>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  card: {
    type: Object,
    required: true,
  },
  relatedArticleId: {
    type: [String, Number],
    default: null,
  },
})

const activeSeriesIndex = ref(0)
const chartsOpen = ref(false)
const chartSwipeDirection = ref('left')

const chartConfig = {
  width: 700,
  height: 280,
  margin: { top: 12, right: 12, bottom: 36, left: 56 },
  get bounds() {
    return {
      left: this.margin.left,
      right: this.width - this.margin.right,
      top: this.margin.top,
      bottom: this.height - this.margin.bottom,
    }
  },
}

const priceSeries = computed(() => props.card.price_series || [])
const hasPriceSeries = computed(() => priceSeries.value.length > 0)

const chartTransitionName = computed(() =>
  chartSwipeDirection.value === 'right' ? 'chart-swipe-right' : 'chart-swipe-left'
)

const formattedDate = computed(() => {
  const date = new Date(props.card.hour_start || props.card.created_at || '')
  if (Number.isNaN(date.getTime())) return 'Daily Summary'
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
})

const showReadMore = computed(() => {
  const summary = props.card.summary || ''
  return summary.length > 280
})

const importanceScore = computed(() => normalizeImportanceScore(props.card.importance_score))

const importanceTooltip = computed(() => {
  if (importanceScore.value === 3) return 'Global impact alert (3/3)'
  if (importanceScore.value === 2) return 'Regional or sector impact (2/3)'
  return 'Localized impact (1/3)'
})

const currentSeriesData = computed(() => {
  const series = priceSeries.value[activeSeriesIndex.value]
  return series ? buildChartData(series.candles || [], series.expected_count) : { candles: [], yTicks: [], xTicks: [], priceLines: [], lastPriceLabel: '' }
})

watch(
  priceSeries,
  (series) => {
    if (!series.length) {
      activeSeriesIndex.value = 0
      chartsOpen.value = false
      return
    }
    if (activeSeriesIndex.value >= series.length) {
      activeSeriesIndex.value = 0
    }
  },
  { immediate: true }
)

function onChartTab(index) {
  if (!hasPriceSeries.value) return
  if (chartsOpen.value && activeSeriesIndex.value === index) {
    chartsOpen.value = false
    return
  }
  chartSwipeDirection.value = index < activeSeriesIndex.value ? 'right' : 'left'
  activeSeriesIndex.value = index
  chartsOpen.value = true
}

function normalizeImportanceScore(value) {
  const parsed = Number(value)
  if (Number.isNaN(parsed)) return 1
  return Math.min(3, Math.max(1, Math.round(parsed)))
}

function buildChartData(rows, expectedCount) {
  const bounds = chartConfig.bounds
  if (!rows.length) {
    return { candles: [], yTicks: [], xTicks: [], priceLines: [], lastPriceLabel: '' }
  }

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
    buildPriceGuide('High', max, scaleY, '#1f6f52', 'high'),
    buildPriceGuide('Last', last?.close ?? max, scaleY, '#1d2326', 'last'),
    buildPriceGuide('Low', min, scaleY, '#a04343', 'low'),
  ]

  const lastClose = Number(last?.close)
  const lastPriceLabel = Number.isFinite(lastClose) ? `Last ${lastClose.toFixed(2)}` : ''

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

function buildPriceGuide(label, value, scaleY, color, kind) {
  return {
    y: scaleY(value),
    label: `${label} ${value.toFixed(2)}`,
    color,
    kind,
  }
}

function formatTimeLabel(value) {
  if (!value) return ''
  const parts = value.split(' ')
  if (parts.length < 2) return value
  return parts[1].slice(0, 5)
}

function formatDateRange(item) {
  const date = new Date(item.hour_start || item.created_at || '')
  if (Number.isNaN(date.getTime())) return 'Daily Summary'

  const startDate = new Date(date)
  const endDate = new Date(startDate)
  endDate.setDate(endDate.getDate() + 1)

  return `${startDate.toLocaleDateString('en-US', { month: 'short', day: '2-digit' })} 00:00 - ${endDate.toLocaleDateString('en-US', { month: 'short', day: '2-digit' })} 00:00`
}
</script>

<style scoped>
.daily-card {
  margin-bottom: 24px;
  animation: card-enter 400ms ease forwards;
  animation-delay: var(--animation-delay, 0ms);
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.chart-swipe-left-enter-active,
.chart-swipe-right-enter-active {
  transition: opacity 280ms cubic-bezier(0.4, 0, 0.2, 1),
              transform 320ms cubic-bezier(0.4, 0, 0.2, 1);
}

.chart-swipe-left-leave-active,
.chart-swipe-right-leave-active {
  transition: opacity 200ms cubic-bezier(0.4, 0, 0.2, 1),
              transform 240ms cubic-bezier(0.4, 0, 0.2, 1);
}

.chart-swipe-left-enter-from {
  opacity: 0;
  transform: translateX(24px);
}

.chart-swipe-left-leave-to {
  opacity: 0;
  transform: translateX(-24px);
}

.chart-swipe-right-enter-from {
  opacity: 0;
  transform: translateX(-24px);
}

.chart-swipe-right-leave-to {
  opacity: 0;
  transform: translateX(24px);
}

.daily-card-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  margin-top: 24px;
}

.daily-card-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(
    to right,
    transparent,
    var(--line),
    transparent
  );
}

.daily-card-label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-soft);
  white-space: nowrap;
  font-weight: 500;
}

.daily-card-content {
  background: var(--glass);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 24px;
  box-shadow: var(--shadow-soft);
  transition: box-shadow 280ms ease, transform 280ms ease;
}

.daily-card-content:hover {
  box-shadow: var(--shadow);
}

.daily-card-badge {
  display: inline-block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--accent);
  background: var(--accent-soft);
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 12px;
  font-weight: 600;
}

.daily-card-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.daily-card-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.daily-card-title {
  margin: 0;
  font-size: 24px;
  line-height: 1.32;
  color: var(--ink);
}

.daily-card-time {
  font-size: 12px;
  color: var(--ink-soft);
  white-space: nowrap;
}

.daily-card-importance {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 6px;
  border-radius: 999px;
  border: 1px solid transparent;
}

.daily-card-importance.level-1 {
  color: #7b661d;
  background: rgba(188, 142, 43, 0.12);
  border-color: rgba(188, 142, 43, 0.28);
}

.daily-card-importance.level-2 {
  color: #6f4f17;
  background: rgba(184, 116, 33, 0.14);
  border-color: rgba(184, 116, 33, 0.3);
}

.daily-card-importance.level-3 {
  color: #8d2f2f;
  background: rgba(179, 75, 75, 0.14);
  border-color: rgba(179, 75, 75, 0.34);
}

.daily-card-importance-triangle {
  width: 10px;
  height: 9px;
  display: inline-flex;
}

.daily-card-importance-triangle svg {
  width: 100%;
  height: 100%;
  display: block;
}

.daily-card-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.daily-card-text {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.daily-card-summary {
  margin: 0;
  font-size: 16px;
  line-height: 1.72;
  color: var(--ink-soft);
}

.daily-card-readmore {
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
  text-decoration: none;
  transition: color 200ms ease;
  width: fit-content;
}

.daily-card-readmore:hover {
  color: var(--accent);
  text-decoration: underline;
}

.daily-card-chart-controls {
  display: flex;
  gap: 10px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  align-items: center;
  flex-wrap: wrap;
}

.daily-card-charts {
  max-height: 0;
  opacity: 0;
  overflow: hidden;
  transition: max-height 380ms cubic-bezier(0.4, 0, 0.2, 1), opacity 280ms ease;
}

.daily-card-charts.is-open {
  max-height: 540px;
  opacity: 1;
}

.daily-card-chart-tab {
  appearance: none;
  border: 0;
  background: transparent;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-soft);
  cursor: pointer;
  padding: 6px 0;
  border-bottom: 2px solid transparent;
  transition: color 180ms ease, border-color 180ms ease, background 140ms ease;
}

.daily-card-chart-tab.is-active {
  color: var(--ink);
  border-bottom-color: var(--accent);
}

.daily-card-chart-tab:hover:not(.is-active) {
  color: var(--ink);
  background: rgba(29, 78, 216, 0.05);
  border-radius: 2px;
  padding: 6px 4px;
}

.daily-card-chart-wrapper {
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  margin-top: 14px;
}

.daily-card-chart-canvas {
  width: 100%;
  height: 240px;
  display: block;
  max-width: 100%;
  transition: opacity 200ms ease;
}

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 240px;
  color: var(--ink-soft);
  font-size: 14px;
}

.chart-grid line {
  stroke: rgba(15, 20, 30, 0.08);
  stroke-width: 1;
}

.chart-axis text {
  fill: var(--ink-soft);
  font-size: 12px;
  letter-spacing: 0.04em;
  font-weight: 500;
}

.chart-guide text {
  fill: var(--ink);
  font-size: 12px;
  letter-spacing: 0.04em;
  font-weight: 500;
}

.chart-last-price {
  font-weight: 700;
  font-size: 13px;
  fill: var(--ink);
}

.daily-card-related {
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.daily-card-related-label {
  margin: 0 0 8px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-soft);
  font-weight: 600;
}

.daily-card-related-link {
  display: inline-flex;
  align-items: center;
  font-size: 14px;
  color: var(--accent);
  text-decoration: none;
  transition: color 200ms ease;
}

.daily-card-related-link:hover {
  color: var(--accent);
  text-decoration: underline;
}

@media (max-width: 640px) {
  .daily-card-content {
    padding: 16px;
  }

  .daily-card-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .daily-card-title {
    font-size: 20px;
  }

  .daily-card-summary {
    font-size: 15px;
  }

  .daily-card-chart-canvas {
    height: 200px;
  }
}
</style>
