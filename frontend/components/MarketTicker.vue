<template>
  <div v-if="rows.length" class="ticker" aria-label="Markets, change over 24 hours">
    <div class="ticker-track">
      <div
        v-for="row in rows"
        :key="row.symbol"
        class="ticker-item"
        :class="{ 'is-stale': row.is_stale }"
        :title="row.is_stale ? `Market closed. Last price at ${lastAt(row)} UTC` : `24h range ${formatPrice(row.low)} to ${formatPrice(row.high)}`"
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
  border-bottom: var(--rule-hair) solid var(--color-ink);
  background: var(--color-paper-2);
  overflow-x: auto;
  scrollbar-width: none;
}

.ticker::-webkit-scrollbar {
  display: none;
}

.ticker-track {
  display: flex;
  width: max-content;
  margin-inline: auto;
  padding-inline: var(--space-xs);
}

.ticker-item {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-md);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  border-right: var(--rule-hair) solid var(--color-rule);
}

.ticker-item:last-child {
  border-right: 0;
}

.ticker-item.is-stale .ticker-price,
.ticker-item.is-stale .ticker-change {
  color: var(--color-muted);
}

.ticker-label {
  color: var(--color-muted);
}

.ticker-price {
  font-weight: 600;
  color: var(--color-ink);
}

.ticker-change.is-up,
.ticker-spark .is-up {
  color: var(--color-up);
  stroke: var(--color-up);
}

.ticker-change.is-down,
.ticker-spark .is-down {
  color: var(--color-down);
  stroke: var(--color-down);
}

.ticker-change.is-flat,
.ticker-spark .is-flat {
  color: var(--color-muted);
  stroke: var(--color-muted);
}

.ticker-spark {
  width: var(--space-2xl);
  height: var(--space-md);
}

.ticker-spark polyline {
  fill: none;
  stroke-width: 1.4;
  stroke-linejoin: round;
  stroke-linecap: round;
}
</style>
