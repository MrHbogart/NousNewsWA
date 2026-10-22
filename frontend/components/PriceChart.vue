<template>
  <div v-if="series.length" class="pc">
    <div class="pc-tabs" role="tablist" aria-label="Price charts">
      <button
        v-for="(item, index) in series"
        :key="item.symbol || index"
        type="button"
        role="tab"
        class="pc-tab"
        :class="{ 'is-active': isOpen && active === index }"
        :aria-selected="isOpen && active === index"
        @click="select(index)"
      >
        <span>{{ item.label || item.symbol }}</span>
        <span v-if="changes[index]" class="pc-change" :class="`is-${changeDirection(changes[index].pct)}`">
          {{ formatChange(changes[index].pct) }}
        </span>
      </button>
    </div>

    <div v-if="isOpen && chart" class="pc-panel">
      <div class="pc-summary">
        <span class="pc-last">{{ formatPrice(chart.last) }}</span>
        <span class="pc-range">Low {{ formatPrice(chart.min) }} · High {{ formatPrice(chart.max) }}</span>
        <span v-if="current.timeframe" class="pc-range">{{ current.timeframe }} candles, UTC</span>
      </div>
      <div class="pc-frame" @pointerleave="hover = null">
        <svg
          class="pc-svg"
          :viewBox="`0 0 ${W} ${H}`"
          role="img"
          :aria-label="`${current.label} candlestick chart`"
          @pointermove="onPointer"
        >
          <g class="pc-grid">
            <line v-for="tick in chart.yTicks" :key="`y${tick.y}`" :x1="PAD.l" :x2="W - PAD.r" :y1="tick.y" :y2="tick.y" />
          </g>
          <g class="pc-axis">
            <text v-for="tick in chart.yTicks" :key="`yl${tick.y}`" :x="W - PAD.r + 6" :y="tick.y + 4">{{ tick.label }}</text>
            <text v-for="tick in chart.xTicks" :key="`xl${tick.x}`" :x="tick.x" :y="H - 8" text-anchor="middle">{{ tick.label }}</text>
          </g>
          <g v-for="(c, i) in chart.candles" :key="i" :class="c.up ? 'pc-up' : 'pc-down'">
            <line :x1="c.x" :x2="c.x" :y1="c.highY" :y2="c.lowY" stroke-width="1.2" />
            <rect :x="c.x - chart.bodyWidth / 2" :y="c.bodyY" :width="chart.bodyWidth" :height="c.bodyHeight" rx="0.5" />
          </g>
          <line class="pc-last-line" :x1="PAD.l" :x2="W - PAD.r" :y1="chart.lastY" :y2="chart.lastY" />
          <line v-if="hover" class="pc-cursor" :x1="hover.x" :x2="hover.x" :y1="PAD.t" :y2="H - PAD.b" />
        </svg>
        <div
          v-if="hover"
          class="pc-tooltip"
          :class="{ 'is-left': hover.x > W * 0.6 }"
          :style="{ left: `${(hover.x / W) * 100}%` }"
        >
          <strong>{{ hover.row.timestamp }} UTC</strong>
          <span>O {{ formatPrice(hover.row.open) }}</span>
          <span>H {{ formatPrice(hover.row.high) }}</span>
          <span>L {{ formatPrice(hover.row.low) }}</span>
          <span>C {{ formatPrice(hover.row.close) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  series: { type: Array, default: () => [] },
  initiallyOpen: { type: Boolean, default: false },
})

// Drawn in a fixed viewBox and stretched to the container width.
const W = 720
const H = 260
const PAD = { l: 4, r: 64, t: 10, b: 26 }

const active = ref(0)
const isOpen = ref(props.initiallyOpen)
const hover = ref(null)

const changes = computed(() => props.series.map(seriesChange))
const current = computed(() => props.series[active.value] || props.series[0] || {})

watch(
  () => props.series.length,
  (length) => {
    if (active.value >= length) active.value = 0
  }
)

function select(index) {
  hover.value = null
  if (isOpen.value && active.value === index) {
    isOpen.value = false
    return
  }
  active.value = index
  isOpen.value = true
}

const chart = computed(() => {
  const rows = current.value?.candles || []
  if (!rows.length) return null
  const slots = Math.max(rows.length, Number(current.value.expected_count) || rows.length)
  const max = Math.max(...rows.map((r) => Number(r.high)))
  const min = Math.min(...rows.map((r) => Number(r.low)))
  const range = Math.max(max - min, Math.abs(max) * 1e-6, 1e-9)
  const top = PAD.t
  const bottom = H - PAD.b
  const y = (value) => top + ((max - Number(value)) / range) * (bottom - top)
  const step = (W - PAD.l - PAD.r) / slots
  const candles = rows.map((row, i) => {
    const openY = y(row.open)
    const closeY = y(row.close)
    return {
      x: PAD.l + i * step + step / 2,
      highY: y(row.high),
      lowY: y(row.low),
      bodyY: Math.min(openY, closeY),
      bodyHeight: Math.max(1, Math.abs(openY - closeY)),
      up: Number(row.close) >= Number(row.open),
    }
  })
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => {
    const value = max - range * t
    return { y: y(value), label: formatPrice(value) }
  })
  const xTicks = [0, 0.33, 0.66, 1]
    .map((t) => Math.min(rows.length - 1, Math.round((slots - 1) * t)))
    .filter((index, i, all) => all.indexOf(index) === i && index < rows.length)
    .map((index) => ({ x: PAD.l + index * step + step / 2, label: timeLabel(rows[index].timestamp) }))
  const last = Number(rows[rows.length - 1].close)
  return { candles, yTicks, xTicks, min, max, last, lastY: y(last), step, bodyWidth: Math.max(1.5, Math.min(10, step * 0.62)) }
})

function timeLabel(timestamp = '') {
  const [date, time] = String(timestamp).split(' ')
  if (!time) return date
  // Multi-day windows label the day, intraday ones the time.
  const rows = current.value?.candles || []
  const multiDay = rows.length && rows[0].timestamp.slice(0, 10) !== rows[rows.length - 1].timestamp.slice(0, 10)
  return multiDay ? date.slice(5) : time.slice(0, 5)
}

function onPointer(event) {
  const data = chart.value
  if (!data) return
  const box = event.currentTarget.getBoundingClientRect()
  const x = ((event.clientX - box.left) / box.width) * W
  const index = Math.floor((x - PAD.l) / data.step)
  const rows = current.value.candles
  if (index < 0 || index >= rows.length) {
    hover.value = null
    return
  }
  hover.value = { x: data.candles[index].x, row: rows[index] }
}
</script>

<style scoped>
.pc {
  border-top: 1px solid var(--line);
  padding-top: 14px;
}

.pc-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pc-tab {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  padding: 5px 11px;
  font: inherit;
  font-size: 12.5px;
  color: var(--ink-soft);
  cursor: pointer;
  transition: border-color 160ms ease, color 160ms ease, background 160ms ease;
}

.pc-tab:hover {
  color: var(--ink);
  border-color: rgba(15, 20, 30, 0.2);
}

.pc-tab.is-active {
  color: var(--ink);
  border-color: var(--accent);
  background: var(--accent-soft);
}

.pc-tab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.pc-change {
  font-variant-numeric: tabular-nums;
  font-size: 11.5px;
}

.is-up {
  color: var(--up);
}

.is-down {
  color: var(--down);
}

.is-flat {
  color: var(--ink-soft);
}

.pc-panel {
  margin-top: 14px;
}

.pc-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 14px;
  margin-bottom: 6px;
}

.pc-last {
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.pc-range {
  font-size: 12px;
  color: var(--ink-soft);
  font-variant-numeric: tabular-nums;
}

.pc-frame {
  position: relative;
}

.pc-svg {
  display: block;
  width: 100%;
  height: auto;
  touch-action: pan-y;
}

.pc-grid line {
  stroke: rgba(15, 20, 30, 0.07);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.pc-axis text {
  fill: var(--ink-soft);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.pc-up line,
.pc-up rect {
  stroke: var(--up);
  fill: var(--up);
}

.pc-down line,
.pc-down rect {
  stroke: var(--down);
  fill: var(--down);
}

.pc-last-line {
  stroke: var(--ink);
  stroke-opacity: 0.35;
  stroke-dasharray: 3 4;
  vector-effect: non-scaling-stroke;
}

.pc-cursor {
  stroke: var(--ink);
  stroke-opacity: 0.4;
  vector-effect: non-scaling-stroke;
}

.pc-tooltip {
  position: absolute;
  top: 6px;
  transform: translateX(10px);
  display: grid;
  gap: 1px;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--shadow-soft);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: var(--ink-soft);
  pointer-events: none;
  white-space: nowrap;
}

.pc-tooltip.is-left {
  transform: translateX(calc(-100% - 10px));
}

.pc-tooltip strong {
  color: var(--ink);
  font-weight: 600;
}
</style>
