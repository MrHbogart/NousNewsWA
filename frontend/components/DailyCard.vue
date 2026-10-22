<template>
  <article class="daily">
    <div class="daily-divider">
      <span class="daily-line"></span>
      <span class="daily-date">{{ dividerLabel }}</span>
      <span class="daily-line"></span>
    </div>
    <div class="daily-content">
      <p class="daily-badge">{{ badge }}</p>
      <h2 class="daily-title">
        <NuxtLink :to="`/articles/${card.slug || card.id}`">{{ card.title || 'Market summary' }}</NuxtLink>
      </h2>
      <div class="daily-meta">
        <time :datetime="card.period_start">{{ dateRange }}</time>
        <ImportanceMarker :score="card.importance_score" />
      </div>
      <p class="daily-summary">{{ card.summary }}</p>
      <NuxtLink :to="`/articles/${card.slug || card.id}`" class="daily-readmore">Read the full {{ noun }}</NuxtLink>
      <PriceChart class="daily-chart" :series="card.price_series || []" />
    </div>
  </article>
</template>

<script setup>
const props = defineProps({
  card: { type: Object, required: true },
})

// Week and month briefs render with this card too.
const BADGES = { day: 'Daily summary', week: 'Weekly review', month: 'Monthly review' }
const NOUNS = { day: 'day', week: 'week', month: 'month' }
const badge = computed(() => BADGES[props.card.timeframe] || 'Summary')
const noun = computed(() => `${NOUNS[props.card.timeframe] || 'summary'} in review`)

const fmt = (d, opts) => d.toLocaleDateString('en-US', { timeZone: 'UTC', ...opts })
const dividerLabel = computed(() => {
  const start = new Date(props.card.period_start || '')
  if (Number.isNaN(start.getTime())) return ''
  if (props.card.timeframe === 'month') return fmt(start, { month: 'long', year: 'numeric' })
  return fmt(start, { weekday: 'long', month: 'long', day: 'numeric' })
})
const dateRange = computed(() => {
  const start = new Date(props.card.period_start || '')
  const end = new Date(props.card.period_end || '')
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return ''
  const short = { month: 'short', day: 'numeric' }
  // period_end is exclusive (next midnight): a day brief covers just its start date.
  if (props.card.timeframe === 'day') return `${fmt(start, { ...short, year: 'numeric' })} (UTC)`
  return `${fmt(start, short)} – ${fmt(new Date(end.getTime() - 1), { ...short, year: 'numeric' })} (UTC)`
})
</script>

<style scoped>
.daily {
  margin-bottom: 20px;
}

.daily-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 28px 0 16px;
}

.daily-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--line), transparent);
}

.daily-date {
  font-size: 13px;
  color: var(--ink-soft);
  white-space: nowrap;
}

.daily-content {
  background: var(--glass);
  border: 1px solid var(--line);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius);
  padding: 24px;
  box-shadow: var(--shadow-soft);
}

.daily-badge {
  margin: 0 0 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--accent);
}

.daily-title {
  margin: 0;
  font-size: 23px;
  line-height: 1.3;
  font-weight: 600;
  color: var(--ink);
}

.daily-title a {
  color: inherit;
  text-decoration: none;
}

.daily-title a:hover {
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}

.daily-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--ink-soft);
}

.daily-summary {
  margin: 14px 0 0;
  font-size: 16px;
  line-height: 1.72;
  color: var(--ink-soft);
}

.daily-readmore {
  display: inline-block;
  margin-top: 10px;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--accent);
  text-decoration: none;
}

.daily-readmore:hover {
  text-decoration: underline;
}

.daily-chart {
  margin-top: 18px;
}

@media (max-width: 640px) {
  .daily-content {
    padding: 16px;
  }

  .daily-title {
    font-size: 20px;
  }

  .daily-summary {
    font-size: 15px;
  }
}
</style>
