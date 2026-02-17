<template>
  <div class="card-container" :class="{ 'is-current': isCurrent }">
    <div class="card-header">
      <div class="card-header-content">
        <h2 class="card-title">{{ card.title || 'Market Brief' }}</h2>
        <div class="card-meta-row">
          <span class="card-time">{{ formatTime(card) }}</span>
          <div class="card-importance" :class="`level-${importanceScore}`" :aria-label="importanceTooltip" :title="importanceTooltip">
            <span
              v-for="index in importanceScore"
              :key="`importance-${card.id || card.slug || 'card'}-${index}`"
              class="card-importance-triangle"
            >
              <svg viewBox="0 0 12 10" fill="currentColor" aria-hidden="true">
                <path d="M6 1L11 9H1L6 1Z" />
              </svg>
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="card-body">
      <div class="card-text">
        <p class="card-summary">{{ card.summary || 'No summary available yet.' }}</p>
        <NuxtLink v-if="showReadMore" :to="`/articles/${card.slug || card.id}`" class="card-readmore">
          Read full article
        </NuxtLink>
      </div>

      <div v-if="hasPriceSeries" class="card-chart-controls" role="tablist" aria-label="Related charts">
        <button
          v-for="(series, index) in priceSeries"
          :key="`series-${card.id}-${index}`"
          class="card-chart-tab"
          :class="{ 'is-active': activeSeriesIndex === index }"
          :aria-selected="chartOpen && activeSeriesIndex === index"
          @click="onChartTab(index)"
        >
          {{ series.label || series.symbol || 'Asset' }}
        </button>
      </div>

      <div v-if="hasPriceSeries" class="card-chart-section" :class="{ 'is-open': chartOpen }">
        <div class="card-chart-wrapper">
          <Transition :name="chartTransitionName" mode="out-in">
            <svg
              v-if="currentSeriesData.candles.length"
              :key="`chart-${activeSeriesIndex}`"
              class="card-chart-canvas"
              :viewBox="`0 0 ${chartConfig.width} ${chartConfig.height}`"
              role="img"
              :aria-label="`${priceSeries[activeSeriesIndex]?.label} candlestick chart`"
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
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  card: {
    type: Object,
    required: true,
  },
  isCurrent: {
    type: Boolean,
    default: false,
  },
})

const chartOpen = ref(props.isCurrent)
const activeSeriesIndex = ref(0)
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
      chartOpen.value = false
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
  if (chartOpen.value && activeSeriesIndex.value === index) {
    chartOpen.value = false
    return
  }
  chartSwipeDirection.value = index < activeSeriesIndex.value ? 'right' : 'left'
  activeSeriesIndex.value = index
  chartOpen.value = true
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

function formatTime(item) {
  const value = item.hour_start || item.created_at
  const date = new Date(value || '')
  if (Number.isNaN(date.getTime())) return 'Just now'

  const startHour = date.getHours().toString().padStart(2, '0')
  const endHour = ((date.getHours() + 1) % 24).toString().padStart(2, '0')

  return `${startHour}:00 - ${endHour}:00`
}
</script>

<style scoped>
.card-container {
  background: var(--glass);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 0;
  box-shadow: var(--shadow-soft);
  margin-bottom: 16px;
  transition: box-shadow 280ms ease, transform 280ms ease;
  animation: card-enter 400ms ease forwards;
  animation-delay: var(--animation-delay, 0ms);
}

.card-container:hover {
  box-shadow: var(--shadow);
}

.card-container.is-current {
  padding: 24px;
  background: var(--glass);
  box-shadow: var(--shadow);
  margin-bottom: 24px;
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

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  gap: 12px;
  border-bottom: 1px solid transparent;
}

.card-container.is-current .card-header {
  padding: 0 0 16px;
  border-top: 0;
}

.card-header-content {
  flex: 1;
  min-width: 0;
}

.card-title {
  margin: 0;
  font-size: 18px;
  line-height: 1.35;
  color: var(--ink);
  font-weight: 500;
}

.card-container.is-current .card-title {
  font-size: 28px;
  margin-bottom: 8px;
}

.card-meta-row {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.card-time {
  font-size: 12px;
  color: var(--ink-soft);
  white-space: nowrap;
}

.card-importance {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 6px;
  border-radius: 999px;
  border: 1px solid transparent;
}

.card-importance.level-1 {
  color: #7b661d;
  background: rgba(188, 142, 43, 0.12);
  border-color: rgba(188, 142, 43, 0.28);
}

.card-importance.level-2 {
  color: #6f4f17;
  background: rgba(184, 116, 33, 0.14);
  border-color: rgba(184, 116, 33, 0.3);
}

.card-importance.level-3 {
  color: #8d2f2f;
  background: rgba(179, 75, 75, 0.14);
  border-color: rgba(179, 75, 75, 0.34);
}

.card-importance-triangle {
  width: 10px;
  height: 9px;
  display: inline-flex;
}

.card-importance-triangle svg {
  width: 100%;
  height: 100%;
  display: block;
}

.card-body {
  padding: 0 24px 20px;
}

.card-container.is-current .card-body {
  padding: 0;
}

.card-text {
  margin-bottom: 0;
}

.card-container.is-current .card-text {
  margin-bottom: 24px;
}

.card-summary {
  margin: 0;
  font-size: 16px;
  line-height: 1.72;
  color: var(--ink-soft);
  display: -webkit-box;
  -webkit-line-clamp: 7;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-container.is-current .card-summary {
  -webkit-line-clamp: none;
  font-size: 17px;
}

.card-readmore {
  display: inline-flex;
  align-items: center;
  margin-top: 12px;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
  text-decoration: none;
  transition: color 200ms ease;
}

.card-readmore:hover {
  color: var(--accent);
  text-decoration: underline;
}

.card-chart-controls {
  display: flex;
  gap: 10px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  align-items: center;
  flex-wrap: wrap;
}

.card-chart-section {
  max-height: 0;
  overflow: hidden;
  opacity: 0;
  transition: max-height 380ms cubic-bezier(0.4, 0, 0.2, 1), opacity 280ms ease;
}

.card-chart-section.is-open {
  max-height: 620px;
  opacity: 1;
  margin-top: 14px;
}

.card-chart-tab {
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

.card-chart-tab.is-active {
  color: var(--ink);
  border-bottom-color: var(--accent);
}

.card-chart-tab:hover:not(.is-active) {
  color: var(--ink);
  background: rgba(29, 78, 216, 0.05);
  border-radius: 2px;
  padding: 6px 4px;
}

.card-chart-wrapper {
  background: transparent;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
}

.card-chart-canvas {
  width: 100%;
  height: 240px;
  display: block;
  max-width: 100%;
  transition: opacity 200ms ease;
}

.card-container.is-current .card-chart-canvas {
  height: 280px;
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

@media (max-width: 640px) {
  .card-container.is-current {
    padding: 16px;
  }

  .card-header,
  .card-body {
    padding-left: 16px;
    padding-right: 16px;
  }

  .card-title {
    font-size: 20px;
  }

  .card-container.is-current .card-title {
    font-size: 24px;
  }

  .card-summary {
    font-size: 15px;
  }

  .card-chart-canvas {
    height: 200px;
  }

  .card-container.is-current .card-chart-canvas {
    height: 240px;
  }
}
</style>
