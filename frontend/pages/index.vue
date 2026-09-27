<template>
  <div class="page-container">
    <!-- Current hour card (always at top) -->
    <div v-if="currentCard" class="current-card-section">
      <HourlyCard :card="currentCard" :is-current="true" />
    </div>

    <!-- Historical cards, newest first (hourly and daily interleaved) -->
    <div class="cards-stack">
      <template v-for="(card, index) in historicalCards" :key="`${card.is_daily_summary ? 'daily' : 'hourly'}-${card.id}`">
        <DailyCard
          v-if="card.is_daily_summary"
          :card="card"
          :related-article-id="card.related_article_id"
          :style="{ '--animation-delay': `${index * 50}ms` }"
        />
        <HourlyCard v-else :card="card" :is-current="false" :style="{ '--animation-delay': `${index * 50}ms` }" />
      </template>

      <!-- Load more sentinel -->
      <div ref="sentinel" class="scroll-sentinel"></div>

      <!-- End of list indicator -->
      <div v-if="!infiniteScroll.hasMore && totalCards > 0" class="end-of-list">
        <div class="end-of-list-visual"></div>
        <p class="end-of-list-text">You've reached the beginning of our records</p>
      </div>

      <!-- Empty state -->
      <div v-if="totalCards === 0 && !infiniteScroll.isLoading" class="empty-state">
        <p class="empty-state-text">No articles available yet. Check back soon.</p>
      </div>

      <!-- Loading indicator -->
      <div v-if="infiniteScroll.isLoading" class="loading-indicator">
        <div class="loading-spinner"></div>
        <p>Loading more articles...</p>
      </div>
    </div>
  </div>
</template>

<script setup>
const api = useNewsApi()
const pageSize = 10

const infiniteScroll = useInfiniteScroll(
  async (page, limit) => {
    try {
      const response = await api.getBriefs({ page, limit })
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
const { data: initial } = await useAsyncData('home', async () => {
  const [lasthour, briefs] = await Promise.all([
    api.getLastHour().catch(() => null),
    api.getBriefs({ page: 0, limit: pageSize }).catch(() => null),
  ])
  return { lasthour, briefs: briefs?.results || [] }
})

const currentCard = ref(initial.value?.lasthour || null)
if (initial.value?.briefs?.length) infiniteScroll.seed(initial.value.briefs)

const historicalCards = computed(() =>
  (infiniteScroll.items.value || []).filter((card) => card.id !== currentCard.value?.id)
)
const totalCards = computed(() => (currentCard.value ? 1 : 0) + historicalCards.value.length)

// Prepend newly published briefs without discarding pages already scrolled into.
function mergeLatestBriefs(newest) {
  if (!newest?.length) return
  const knownIds = new Set(infiniteScroll.items.value.map((item) => item.id))
  const fresh = newest.filter((item) => !knownIds.has(item.id))
  if (fresh.length) infiniteScroll.items.value = [...fresh, ...infiniteScroll.items.value]
}

useEventStream('/stream/home/', {
  home: (payload) => {
    if (payload?.lasthour) currentCard.value = payload.lasthour
    mergeLatestBriefs(payload?.briefs?.results)
  },
})

useHead({
  title: 'NousNews · Live Brief',
  meta: [
    {
      name: 'description',
      content: 'NousNews: Agent-driven economic intelligence with real-time market analysis.',
    },
  ],
})
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding-bottom: 48px;
}

.current-card-section {
  padding-top: 32px;
  padding-bottom: 0;
}

.cards-stack {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin-top: 24px;
}

.scroll-sentinel {
  height: 2px;
  visibility: hidden;
}

.end-of-list {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 20px;
  margin-top: 40px;
}

.end-of-list-visual {
  width: 40px;
  height: 2px;
  background: linear-gradient(to right, transparent, var(--line), transparent);
  position: relative;
}

.end-of-list-visual::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 6px;
  height: 6px;
  background: var(--ink-soft);
  border-radius: 50%;
}

.end-of-list-text {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-soft);
  text-align: center;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
}

.empty-state-text {
  margin: 0;
  font-size: 15px;
  color: var(--ink-soft);
  max-width: 300px;
}

.loading-indicator {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 20px;
}

.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--line);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 800ms linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-indicator p {
  margin: 0;
  font-size: 12px;
  color: var(--ink-soft);
}

@media (max-width: 640px) {
  .page-container {
    padding-bottom: 32px;
  }

  .current-card-section {
    padding-top: 24px;
  }

  .cards-stack {
    margin-top: 16px;
  }
}
</style>
