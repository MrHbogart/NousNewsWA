<template>
  <div v-if="rows.length" class="ticker" aria-label="Markets, change over 24 hours">
    <div class="ticker-track">
      <div
        v-for="row in rows"
        :key="row.symbol"
        class="ticker-item"
        :class="{ 'is-stale': row.is_stale }"
        :title="row.is_stale ? `Market closed. Last price at ${lastAt(row)} UTC` : `24h range ${formatPrice(row.low)} – ${formatPrice(row.high)}`"
      >
        <span class="ticker-label">{{ shortLabel(row.label) }}</span>
        <span class="ticker-price">{{ formatPrice(row.last) }}</span>
        <span class="ticker-change" :class="`is-${changeDirection(row.change_pct)}`">{{ formatChange(row.change_pct) }}</span>
        <svg v-if="row.sparkline?.length > 1" class="ticker-spark" viewBox="0 0 60 18" aria-hidden="true">
          <polyline :points="sparkPoints(row.sparkline)" :class="`is-${changeDirection(row.change_pct)}`" />
        </svg>
      </div>
    </div>
  </div>
</template>

<script setup>
const api = useNewsApi()

// Rendered on the server, then kept live over SSE (one tick per price sync).
const { data } = await useAsyncData('market-overview', () => api.getMarketOverview().catch(() => null))
const rows = ref(data.value?.results || [])

useEventStream('/stream/ticker/', {
  ticker: (payload) => {
    if (Array.isArray(payload?.results)) rows.value = payload.results
  },
})

// "Gold (XAUUSD)" -> "Gold": the strip has little room; the full label is in the title.
function shortLabel(label = '') {
  return label.replace(/\s*\(.*\)\s*$/, '').replace(/ Index$/, '').replace(/ Composite$/, '')
}

function lastAt(row) {
  return String(row.last_at || '').replace('T', ' ').slice(0, 16)
}

function sparkPoints(values) {
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  return values
    .map((v, i) => `${((i / (values.length - 1)) * 60).toFixed(1)},${(16 - ((v - min) / range) * 14).toFixed(1)}`)
    .join(' ')
}
</script>

<style scoped>
.ticker {
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.6);
  overflow-x: auto;
  scrollbar-width: none;
}

.ticker::-webkit-scrollbar {
  display: none;
}

.ticker-track {
  display: flex;
  width: max-content;
  margin: 0 auto;
  padding: 0 14px;
}

.ticker-item {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 12px;
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  border-right: 1px solid var(--line);
}

.ticker-item:last-child {
  border-right: 0;
}

.ticker-item.is-stale {
  opacity: 0.6;
}

.ticker-label {
  color: var(--ink-soft);
}

.ticker-price {
  font-weight: 600;
  color: var(--ink);
}

.ticker-change.is-up,
.ticker-spark .is-up {
  color: var(--up);
  stroke: var(--up);
}

.ticker-change.is-down,
.ticker-spark .is-down {
  color: var(--down);
  stroke: var(--down);
}

.ticker-change.is-flat,
.ticker-spark .is-flat {
  color: var(--ink-soft);
  stroke: var(--ink-soft);
}

.ticker-spark {
  width: 48px;
  height: 16px;
}

.ticker-spark polyline {
  fill: none;
  stroke-width: 1.4;
  stroke-linejoin: round;
  stroke-linecap: round;
}
</style>
