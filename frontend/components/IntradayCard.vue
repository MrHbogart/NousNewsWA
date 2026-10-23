<template>
  <article v-if="isCurrent" class="lead-story">
    <div class="lead-text">
      <p class="lead-live" role="status">
        {{ card.id ? 'Live: updating through this 4-hour block' : 'Waiting for the first stories of this block' }}
      </p>
      <h2 class="lead-title">
        <NuxtLink v-if="link" :to="link">{{ card.title || 'Market brief' }}</NuxtLink>
        <template v-else>{{ card.title || 'Market brief' }}</template>
      </h2>
      <div class="lead-facts">
        <time :datetime="card.period_start">{{ timeRange }}</time>
        <ImportanceMarker :score="card.importance_score" />
      </div>
      <p class="lead-summary">{{ card.summary || 'No summary yet.' }}</p>
      <NuxtLink v-if="link" :to="link" class="btn btn--ink lead-more">Read the full brief</NuxtLink>
    </div>
    <PriceChart class="lead-chart" :series="card.price_series || []" :initially-open="true" />
  </article>

  <article v-else class="story">
    <div class="story-facts">
      <time :datetime="card.period_start">{{ timeRange }}</time>
      <ImportanceMarker :score="card.importance_score" />
    </div>
    <div class="story-body">
      <h2 class="story-title">
        <NuxtLink v-if="link" :to="link">{{ card.title || 'Market brief' }}</NuxtLink>
        <template v-else>{{ card.title || 'Market brief' }}</template>
      </h2>
      <p class="story-summary">{{ card.summary || 'No summary yet.' }}</p>
      <NuxtLink v-if="link" :to="link" class="text-link story-more">Read the full brief</NuxtLink>
      <PriceChart class="story-chart" :series="card.price_series || []" />
    </div>
  </article>
</template>

<script setup>
const props = defineProps({
  card: { type: Object, required: true },
  isCurrent: { type: Boolean, default: false },
})

const link = computed(() => (props.card.slug || props.card.id ? `/articles/${props.card.slug || props.card.id}` : ''))

// UTC like the periods and chart axes; local time also differed between SSR and hydration.
const timeRange = computed(() => {
  const start = new Date(props.card.period_start || props.card.hour_start || '')
  if (Number.isNaN(start.getTime())) return ''
  const end = new Date(props.card.period_end || start.getTime() + 4 * 3600 * 1000)
  const day = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
  const hh = (d) => String(d.getUTCHours()).padStart(2, '0')
  return `${day}, ${hh(start)}:00 to ${hh(end)}:00 UTC`
})
</script>

<style scoped>
.lead-story {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  column-gap: var(--gap-columns);
  row-gap: var(--space-xl);
  align-items: start;
  padding-block: var(--space-md) var(--space-2xl);
  border-top: var(--rule-bar) solid var(--color-ink);
}

.lead-text {
  grid-column: 1 / span 5;
  min-width: 0;
}

.lead-chart {
  grid-column: 7 / span 6;
  min-width: 0;
}

.lead-live {
  margin-bottom: var(--space-sm);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-accent);
}

.lead-title {
  max-width: 22ch;
  font-size: clamp(1.75rem, 1.6vw + 0.75rem, 2.5rem);
  line-height: 1.08;
}

.lead-title a {
  text-decoration: none;
}

.lead-title a:hover {
  text-decoration: underline;
  text-decoration-thickness: 2px;
}

.lead-facts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-xs) var(--space-md);
  margin-top: var(--space-md);
  font-size: var(--text-sm);
  color: var(--color-muted);
}

.lead-summary {
  margin-top: var(--space-md);
  max-width: 60ch;
  font-size: var(--text-md);
  line-height: 1.6;
}

.lead-more {
  margin-top: var(--space-lg);
}

@media (max-width: 60rem) {
  .lead-text,
  .lead-chart {
    grid-column: 1 / -1;
  }
}
</style>
