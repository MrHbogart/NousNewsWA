<template>
  <article class="card" :class="{ 'is-live': isCurrent }" :aria-labelledby="`card-${uid}-title`">
    <header class="card-meta">
      <span v-if="isCurrent" class="card-live" role="status">{{ card.id ? 'Live' : 'Starting' }}</span>
      <span class="card-kind">{{ kind }}</span>
      <span aria-hidden="true">·</span>
      <time :datetime="card.period_start">{{ when }}</time>
      <ImportanceMarker class="card-importance" :score="card.importance_score" />
    </header>

    <h2 :id="`card-${uid}-title`" class="card-title">
      <NuxtLink v-if="link" :to="link">{{ card.title || fallbackTitle }}</NuxtLink>
      <template v-else>{{ card.title || fallbackTitle }}</template>
    </h2>

    <p :id="`card-${uid}-summary`" ref="summaryEl" class="card-summary" :class="{ 'is-clamped': !expanded }">
      {{ card.summary || (isCurrent ? 'Scanning the wires for the first stories of this block…' : 'Summary on its way.') }}
    </p>
    <button
      v-if="overflows || expanded"
      type="button"
      class="card-toggle"
      :aria-expanded="expanded"
      :aria-controls="`card-${uid}-summary`"
      @click="expanded = !expanded"
    >
      {{ expanded ? 'Show less' : 'Keep reading' }}
    </button>

    <footer class="card-actions">
      <button
        v-if="series.length"
        type="button"
        class="card-action"
        :aria-expanded="chartsOpen"
        :aria-controls="`card-${uid}-charts`"
        @click="chartsOpen = !chartsOpen"
      >
        <svg class="card-icon" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M2 13h12M4 10V7M8 10V3M12 10V5" />
        </svg>
        {{ chartsOpen ? 'Hide charts' : `See the moves (${series.length})` }}
      </button>
      <NuxtLink v-if="link" :to="link" class="card-action card-read">
        Read the full story
        <svg class="card-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4" /></svg>
      </NuxtLink>
    </footer>

    <PriceChart v-if="chartsOpen" :id="`card-${uid}-charts`" class="card-charts" :series="series" initially-open />
  </article>
</template>

<script setup>
const props = defineProps({
  card: { type: Object, required: true },
  isCurrent: { type: Boolean, default: false },
})

const uid = useId()
const expanded = ref(false)
const overflows = ref(false)
// The live brief opens with its charts showing; past ones stay compact.
const chartsOpen = ref(props.isCurrent)
const summaryEl = ref(null)

const series = computed(() => props.card.price_series || [])
const link = computed(() => (props.card.slug || props.card.id ? `/articles/${props.card.slug || props.card.id}` : ''))

// Day, week and month briefs carry a timeframe; 4-hour briefs do not.
const KINDS = { day: 'Daily summary', week: 'Weekly review', month: 'Monthly review' }
const isSummary = computed(() => Boolean(props.card.is_daily_summary))
const kind = computed(() => (isSummary.value ? KINDS[props.card.timeframe] || 'Summary' : '4-hour brief'))
const fallbackTitle = computed(() => (isSummary.value ? 'Market summary' : 'Market brief'))

// UTC like the periods and chart axes; local time also differed between SSR and hydration.
const fmt = (d, opts) => d.toLocaleDateString('en-US', { timeZone: 'UTC', ...opts })
const when = computed(() => {
  const start = new Date(props.card.period_start || props.card.hour_start || '')
  if (Number.isNaN(start.getTime())) return ''
  const short = { month: 'short', day: 'numeric' }
  if (!isSummary.value) {
    const end = new Date(props.card.period_end || start.getTime() + 4 * 3600 * 1000)
    const hh = (d) => String(d.getUTCHours()).padStart(2, '0')
    return `${fmt(start, short)}, ${hh(start)}:00–${hh(end)}:00 UTC`
  }
  if (props.card.timeframe === 'month') return fmt(start, { month: 'long', year: 'numeric' })
  const end = new Date(props.card.period_end || '')
  // period_end is exclusive (next midnight): a day brief covers just its start date.
  if (props.card.timeframe === 'day' || Number.isNaN(end.getTime())) return fmt(start, { ...short, year: 'numeric' })
  return `${fmt(start, short)}–${fmt(new Date(end.getTime() - 1), { ...short, year: 'numeric' })}`
})

// "Read more" only when the clamp actually hides text.
function measure() {
  const el = summaryEl.value
  if (el && !expanded.value) overflows.value = el.scrollHeight > el.clientHeight + 1
}

let observer = null
onMounted(() => {
  measure()
  observer = new ResizeObserver(measure)
  observer.observe(summaryEl.value)
})
onBeforeUnmount(() => observer?.disconnect())
watch(() => props.card.summary, () => nextTick(measure))
</script>

<style scoped>
.card {
  padding: var(--space-lg) var(--space-lg) var(--space-sm);
  border: var(--rule-hair) solid var(--color-rule);
  background: var(--color-card);
}

.card.is-live {
  border-color: var(--color-ink);
  box-shadow: inset 0 var(--rule-frame) 0 var(--color-accent);
}

.card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2xs) var(--space-xs);
  font-size: var(--text-sm);
  color: var(--color-muted);
}

.card-kind {
  font-weight: 600;
  color: var(--color-ink);
}

.card-live {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2xs);
  font-weight: 600;
  color: var(--color-accent);
}

.card-live::before {
  content: "";
  width: var(--space-xs);
  height: var(--space-xs);
  border-radius: 50%;
  background: currentColor;
}

.card-importance {
  margin-left: auto;
}

.card-title {
  max-width: none;
  margin-top: var(--space-sm);
  font-size: var(--text-xl);
  line-height: 1.2;
}

.card-title a {
  text-decoration: none;
}

.card-title a:hover {
  text-decoration: underline;
  text-decoration-thickness: 2px;
}

.card-summary {
  margin-top: var(--space-sm);
  font-size: var(--text-lg);
  line-height: 1.55;
  color: var(--color-ink-2);
}

.card-summary.is-clamped {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-toggle {
  margin-top: var(--space-2xs);
  padding: var(--space-2xs) 0;
  border: 0;
  background: none;
  font-weight: 600;
  color: var(--color-accent);
  cursor: pointer;
}

.card-toggle:hover {
  text-decoration: underline;
}

.card-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-sm);
  margin-top: var(--space-md);
  padding-top: var(--space-2xs);
  border-top: var(--rule-hair) solid var(--color-rule);
}

.card-action {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  min-height: var(--control-h);
  padding-inline: var(--space-xs);
  margin-inline: calc(-1 * var(--space-xs));
  border: 0;
  background: none;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-ink-2);
  text-decoration: none;
  cursor: pointer;
  transition: color var(--dur-micro) var(--ease-out), background-color var(--dur-micro) var(--ease-out);
}

.card-action:hover {
  color: var(--color-ink);
  background: var(--color-paper-2);
}

.card-action[aria-expanded="true"] {
  color: var(--color-ink);
}

/* Alone in the bar (a brief without charts), the link still sits right. */
.card-read {
  margin-left: auto;
}

.card-icon {
  width: var(--space-md);
  height: var(--space-md);
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.card-charts {
  margin-block: var(--space-xs) var(--space-sm);
}

@media (max-width: 40rem) {
  .card {
    padding-inline: var(--space-md);
  }

  .card-title {
    font-size: var(--text-lg);
  }

  .card-summary {
    font-size: var(--text-md);
  }
}

@media (prefers-reduced-motion: reduce) {
  .card-action {
    transition: none;
  }
}
</style>
