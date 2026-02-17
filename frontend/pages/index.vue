<template>
  <div class="page-container">
    <!-- Current hour card (always at top) -->
    <div v-if="currentCard" class="current-card-section">
      <HourlyCard :card="currentCard" :is-current="true" />
    </div>

    <!-- Historical cards (hourly then daily) -->
    <div class="cards-stack">
      <!-- Hourly cards -->
      <HourlyCard
        v-for="(card, index) in historicalHourlyCards"
        :key="`hourly-${card.id}`"
        :card="card"
        :is-current="false"
        :style="{ '--animation-delay': `${index * 50}ms` }"
      />

      <!-- Daily summary cards -->
      <DailyCard
        v-for="(card, index) in dailyCards"
        :key="`daily-${card.id}`"
        :card="card"
        :related-article-id="card.related_article_id"
        :style="{ '--animation-delay': `${(historicalHourlyCards.length + index) * 50}ms` }"
      />

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
const refreshIntervalMs = 20000
let refreshTimer

// Fetch history for infinite scroll
const fetchHistoricalCards = async (page, pageSize) => {
  try {
    const response = await api.getBriefs({ page, limit: pageSize })
    return response?.results || []
  } catch (err) {
    console.error('Error fetching historical cards:', err)
    return []
  }
}

const infiniteScroll = useInfiniteScroll(fetchHistoricalCards, {
  threshold: 500,
  pageSize: 10,
  autoLoad: true,
})

// Current card (updating hourly)
const currentCard = ref(null)
const currentCardPending = ref(true)
const currentCardError = ref(null)

// Get initial current card
const { pending: briefPending, error: briefError } = await useAsyncData(
  'current-hour',
  async () => {
    try {
      const brief = await api.getLastHour()
      currentCard.value = brief
      return brief
    } catch (err) {
      currentCardError.value = err
      return null
    }
  },
  { server: false }
)

watchEffect(() => {
  currentCardPending.value = briefPending.value
  currentCardError.value = briefError.value
})

// Separate historical cards into hourly and daily
const historicalHourlyCards = computed(() => {
  const all = infiniteScroll.items.value || []
  return all.filter((card) => {
    // Filter for hourly cards (not daily summaries)
    return !card.is_daily_summary && card.id !== currentCard.value?.id
  })
})

const dailyCards = computed(() => {
  const all = infiniteScroll.items.value || []
  return all.filter((card) => card.is_daily_summary === true)
})

const totalCards = computed(
  () => (currentCard.value ? 1 : 0) + historicalHourlyCards.value.length + dailyCards.value.length
)

// Refresh current card periodically
async function refreshCurrentCard() {
  try {
    const latest = await api.getLastHour()
    if (latest) {
      currentCard.value = latest
    }
  } catch (err) {
    // Ignore polling errors
  }
}

// Refresh history periodically
async function refreshHistory() {
  try {
    const latest = await api.getBriefs({ page: 0, limit: 10 })
    if (latest?.results) {
      // Reload infinite scroll if the first item changed
      const currentFirst = infiniteScroll.items.value[0]
      if (currentFirst && latest.results[0]?.id !== currentFirst.id) {
        infiniteScroll.reset()
        const newItems = await fetchHistoricalCards(0, 10)
        infiniteScroll.items.value = newItems
        infiniteScroll.page.value = 1
      }
    }
  } catch (err) {
    // Ignore polling errors
  }
}

onMounted(() => {
  refreshTimer = setInterval(() => {
    refreshCurrentCard()
    refreshHistory()
  }, refreshIntervalMs)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
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
