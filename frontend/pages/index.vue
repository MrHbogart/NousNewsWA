<template>
  <div class="front">
    <header class="front-head">
      <h1 class="front-title">What moved the markets today</h1>
      <p class="lead front-lede">
        A new brief every 4 hours on what happened and how prices reacted. Each past day is summed up in one article.
      </p>
    </header>

    <!-- Current 4-hour block (always at top) -->
    <IntradayCard v-if="currentCard && !timeframe" :card="currentCard" :is-current="true" />

    <!-- Historical cards, newest first (today's 4-hour briefs, then one article per past day) -->
    <div class="feed">
      <template v-for="card in historicalCards" :key="`${card.is_daily_summary ? 'daily' : 'intraday'}-${card.id}`">
        <DailyCard
          v-if="card.is_daily_summary"
          :card="card"
        />
        <IntradayCard v-else :card="card" :is-current="false" />
      </template>

      <!-- Load more sentinel -->
      <div ref="sentinel" class="scroll-sentinel"></div>

      <!-- End of list indicator -->
      <p v-if="!infiniteScroll.hasMore && totalCards > 0" class="feed-note feed-end">You’ve reached the beginning of our records</p>

      <!-- Empty state -->
      <p v-if="totalCards === 0 && !infiniteScroll.isLoading" class="feed-note">No articles available yet. Check back soon.</p>

      <!-- Loading indicator -->
      <p v-if="infiniteScroll.isLoading" class="feed-note feed-loading" role="status">
        <span class="feed-spinner keep-motion" aria-hidden="true"></span>
        Loading more articles…
      </p>
    </div>
  </div>
</template>

<script setup>
const api = useNewsApi()
const route = useRoute()
const pageSize = 10
// ?timeframe=day|week|month narrows the feed (header links); empty = everything.
const timeframe = computed(() => (['day', 'week', 'month'].includes(route.query.timeframe) ? route.query.timeframe : ''))

const infiniteScroll = useInfiniteScroll(
  async (page, limit) => {
    try {
      const response = await api.getBriefs({ page, limit, timeframe: timeframe.value })
      return response?.results || []
    } catch (err) {
      console.error('Error fetching historical cards:', err)
      return []
    }
  },
  { threshold: 500, pageSize, autoLoad: true }
)
// `ref="sentinel"` in the template only binds to a top-level ref of this name;
// without this alias the composable's IntersectionObserver never attaches.
const sentinel = infiniteScroll.sentinel

// Rendered on the server; live updates arrive over SSE afterwards.
const { data: initial } = await useAsyncData(`home-${timeframe.value}`, async () => {
  const [lasthour, briefs] = await Promise.all([
    api.getLastHour().catch(() => null),
    api.getBriefs({ page: 0, limit: pageSize, timeframe: timeframe.value }).catch(() => null),
  ])
  return { lasthour, briefs: briefs?.results || [] }
})

const currentCard = ref(initial.value?.lasthour || null)
if (initial.value?.briefs?.length) infiniteScroll.seed(initial.value.briefs)

const historicalCards = computed(() =>
  (infiniteScroll.items.value || []).filter((card) => card.id !== currentCard.value?.id)
)
const totalCards = computed(() => (currentCard.value ? 1 : 0) + historicalCards.value.length)

// Prepend newly published briefs and refresh edited ones, without discarding
// pages already scrolled into.
watch(timeframe, () => {
  infiniteScroll.reset()
  infiniteScroll.loadMore()
})

function mergeLatestBriefs(newest) {
  // The live payload is the unfiltered feed.
  if (!newest?.length || timeframe.value) return
  const byId = new Map(newest.map((item) => [item.id, item]))
  const known = infiniteScroll.items.value.map((item) => byId.get(item.id) || item)
  const knownIds = new Set(known.map((item) => item.id))
  const fresh = newest.filter((item) => !knownIds.has(item.id))
  infiniteScroll.items.value = [...fresh, ...known]
}

useEventStream('/stream/home/', {
  home: (payload) => {
    if (payload?.lasthour) currentCard.value = payload.lasthour
    mergeLatestBriefs(payload?.briefs?.results)
  },
  // Live chart ticks for the current hour's brief.
  prices: (payload) => {
    if (payload?.id && payload.id === currentCard.value?.id) {
      currentCard.value = { ...currentCard.value, price_series: payload.price_series }
    }
  },
})

useSeoMeta({
  title: 'NousNews · What moved the markets today',
  description:
    'Market news every 4 hours: what happened, why it matters, and how stocks, bonds, gold, oil and crypto reacted — with live price charts.',
  ogTitle: 'NousNews · What moved the markets today',
  ogDescription: 'Market news every 4 hours with the price reaction charted next to it.',
  ogType: 'website',
})
</script>

<style scoped>
.front-head {
  container-type: inline-size;
  padding-block: var(--space-lg) var(--space-md);
}

/* Fitted to the measure: one line of Six Caps across the twelve columns. */
.front-title {
  max-width: none;
  font-size: 14.6cqi;
  line-height: 0.88;
  text-transform: uppercase;
  white-space: nowrap;
}

.front-lede {
  margin-top: var(--space-md);
  max-width: 60ch;
  color: var(--color-ink-2);
}

.feed {
  display: flex;
  flex-direction: column;
}

.scroll-sentinel {
  height: 2px;
  visibility: hidden;
}

.feed-note {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding-block: var(--space-xl);
  border-top: var(--rule-hair) solid var(--color-rule);
  color: var(--color-muted);
}

.feed-end {
  margin-top: var(--space-xl);
  border-top: var(--rule-bar) solid var(--color-ink);
}

.feed-spinner {
  width: var(--space-md);
  height: var(--space-md);
  border: 2px solid var(--color-rule);
  border-top-color: var(--color-ink);
  border-radius: 50%;
  animation: spin 800ms linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .feed-spinner {
    animation-duration: 2400ms;
  }
}
</style>
