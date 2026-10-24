<template>
  <div class="front">
    <header class="front-head">
      <h1 class="front-title">The market story, as it breaks</h1>
      <p class="front-lede">Every 4 hours: the headlines that mattered and the price moves they caused, side by side.</p>
    </header>

    <!-- Newest first: the live 4-hour brief, then today's briefs, then one article per past day -->
    <div class="feed">
      <FeedCard v-if="currentCard && !timeframe" :card="currentCard" is-current />
      <FeedCard
        v-for="card in historicalCards"
        :key="`${card.is_daily_summary ? 'daily' : 'intraday'}-${card.id}`"
        :card="card"
      />

      <!-- Load more sentinel -->
      <div ref="sentinel" class="scroll-sentinel"></div>

      <p v-if="isLoading" class="feed-note" role="status">
        <span class="feed-spinner keep-motion" aria-hidden="true"></span>
        Digging up earlier briefs…
      </p>
      <p v-else-if="totalCards === 0" class="feed-note">The first brief is being written. Check back within the hour.</p>
      <p v-else-if="!hasMore" class="feed-note">That’s the whole archive. You’re all caught up.</p>
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
// The template only unwraps top-level refs: `ref="sentinel"` binds only to a
// top-level ref of this name (else the IntersectionObserver never attaches), and
// `infiniteScroll.isLoading` would be the ref object itself, always truthy.
const { sentinel, isLoading, hasMore } = infiniteScroll

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
// The current brief only shows on the unfiltered feed, so only count it there.
const totalCards = computed(() => (currentCard.value && !timeframe.value ? 1 : 0) + historicalCards.value.length)

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
  title: 'NousNews · The market story, as it breaks',
  description:
    'Sharp market briefs every 4 hours: the news that moved stocks, bonds, gold, oil, FX and crypto, with live charts of the reaction.',
  ogTitle: 'NousNews · The market story, as it breaks',
  ogDescription: 'The news that moved markets, every 4 hours, with the price reaction charted right beside it.',
  ogType: 'website',
})
</script>

<style scoped>
/* One centered column, like a timeline. */
.front {
  max-width: var(--measure-feed);
  margin-inline: auto;
  padding-block: var(--space-xl) var(--space-2xl);
}

.front-head {
  margin-bottom: var(--space-lg);
  text-align: center;
}

.front-title {
  max-width: none;
  font-size: var(--text-display);
  line-height: 0.95;
  text-transform: uppercase;
}

.front-lede {
  margin-top: var(--space-xs);
  color: var(--color-muted);
}

.feed {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.scroll-sentinel {
  height: 1px;
  margin-top: calc(-1 * var(--space-md));
  visibility: hidden;
}

.feed-note {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--space-sm);
  padding-block: var(--space-xl);
  font-size: var(--text-sm);
  color: var(--color-muted);
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
