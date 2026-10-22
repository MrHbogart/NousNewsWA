<template>
  <article class="card" :class="{ 'is-current': isCurrent }">
    <p v-if="isCurrent" class="card-live">
      <span class="card-live-dot" aria-hidden="true"></span>
      {{ card.id ? 'Live: updating through this 4-hour block' : 'Waiting for the first stories of this block' }}
    </p>
    <h2 class="card-title">
      <NuxtLink v-if="card.slug || card.id" :to="`/articles/${card.slug || card.id}`">{{ card.title || 'Market brief' }}</NuxtLink>
      <template v-else>{{ card.title || 'Market brief' }}</template>
    </h2>
    <div class="card-meta">
      <time :datetime="card.period_start">{{ timeRange }}</time>
      <ImportanceMarker :score="card.importance_score" />
    </div>
    <p class="card-summary">{{ card.summary || 'No summary yet.' }}</p>
    <NuxtLink v-if="card.slug || card.id" :to="`/articles/${card.slug || card.id}`" class="card-readmore">
      Read the full brief
    </NuxtLink>
    <PriceChart class="card-chart" :series="card.price_series || []" :initially-open="isCurrent" />
  </article>
</template>

<script setup>
const props = defineProps({
  card: { type: Object, required: true },
  isCurrent: { type: Boolean, default: false },
})

// UTC like the periods and chart axes; local time also differed between SSR and hydration.
const timeRange = computed(() => {
  const start = new Date(props.card.period_start || props.card.hour_start || '')
  if (Number.isNaN(start.getTime())) return ''
  const end = new Date(props.card.period_end || start.getTime() + 4 * 3600 * 1000)
  const day = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
  const hh = (d) => String(d.getUTCHours()).padStart(2, '0')
  return `${day}, ${hh(start)}:00–${hh(end)}:00 UTC`
})
</script>

<style scoped>
.card {
  background: var(--glass);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 20px 24px;
  box-shadow: var(--shadow-soft);
  margin-bottom: 16px;
}

.card.is-current {
  padding: 26px 28px;
  box-shadow: var(--shadow);
  margin-bottom: 8px;
}

.card-live {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 10px;
  font-size: 12.5px;
  color: var(--accent);
}

.card-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.25;
  }
}

.card-title {
  margin: 0;
  font-size: 19px;
  line-height: 1.35;
  font-weight: 600;
  color: var(--ink);
}

.card.is-current .card-title {
  font-size: 27px;
  line-height: 1.25;
  letter-spacing: -0.01em;
}

.card-title a {
  color: inherit;
  text-decoration: none;
}

.card-title a:hover {
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--ink-soft);
}

.card-summary {
  margin: 14px 0 0;
  font-size: 15.5px;
  line-height: 1.7;
  color: var(--ink-soft);
  display: -webkit-box;
  -webkit-line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card.is-current .card-summary {
  -webkit-line-clamp: none;
  font-size: 17px;
  color: var(--ink);
}

.card-readmore {
  display: inline-block;
  margin-top: 10px;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--accent);
  text-decoration: none;
}

.card-readmore:hover {
  text-decoration: underline;
}

.card-chart {
  margin-top: 18px;
}

@media (max-width: 640px) {
  .card,
  .card.is-current {
    padding: 16px;
  }

  .card.is-current .card-title {
    font-size: 22px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .card-live-dot {
    animation: none;
  }
}
</style>
