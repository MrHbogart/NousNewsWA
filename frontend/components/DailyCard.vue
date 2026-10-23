<template>
  <div class="daily">
    <p class="daily-dateline"><time :datetime="card.period_start">{{ dividerLabel }}</time></p>
    <article class="story daily-story">
      <div class="story-facts">
        <span class="daily-kind">{{ badge }}</span>
        <time :datetime="card.period_start">{{ dateRange }}</time>
        <ImportanceMarker :score="card.importance_score" />
      </div>
      <div class="story-body">
        <h2 class="story-title daily-title">
          <NuxtLink :to="`/articles/${card.slug || card.id}`">{{ card.title || 'Market summary' }}</NuxtLink>
        </h2>
        <p class="story-summary daily-summary">{{ card.summary }}</p>
        <NuxtLink :to="`/articles/${card.slug || card.id}`" class="text-link story-more">Read the full {{ noun }}</NuxtLink>
        <PriceChart class="story-chart" :series="card.price_series || []" />
      </div>
    </article>
  </div>
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
  return `${fmt(start, short)} to ${fmt(new Date(end.getTime() - 1), { ...short, year: 'numeric' })} (UTC)`
})
</script>

<style scoped>
.daily {
  margin-top: var(--space-2xl);
}

.daily-dateline {
  padding-top: var(--space-sm);
  border-top: var(--rule-bar) solid var(--color-ink);
  font-family: var(--font-display);
  font-size: var(--text-display-s);
  line-height: 1;
  letter-spacing: var(--tracking-display);
  text-transform: uppercase;
  overflow-wrap: break-word;
}

.daily-story {
  border-top: 0;
}

.daily-kind {
  font-weight: 600;
  color: var(--color-ink);
}

.daily-title {
  font-size: var(--text-2xl);
}

.daily-summary {
  -webkit-line-clamp: none;
  font-size: var(--text-lg);
  color: var(--color-ink);
}
</style>
