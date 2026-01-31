<template>
  <section class="enter-stage" style="--delay: 80ms">
    <div class="news-card">
      <p v-if="briefPending" class="news-title">Loading the latest brief...</p>
      <p v-else-if="briefError" class="news-title">
        We could not reach the crawler brief. Check the API base URL.
      </p>
      <p v-else class="news-title">
        {{ briefText }}
      </p>
      <div class="news-refresh">Updated {{ briefUpdatedAt || 'just now' }}</div>
    </div>

    <div class="news-list">
      <div class="news-list-head">
        <div class="news-list-title">Recent headlines</div>
        <NuxtLink to="/ops" class="news-list-link">Crawler logs</NuxtLink>
      </div>
      <ul class="news-items">
        <li v-for="item in recentItems" :key="item.slug" class="news-item">
          <NuxtLink
            :to="`/briefs/${item.slug}`"
            class="news-item-link"
            target="_blank"
            rel="noreferrer"
          >
            <span class="news-item-time">{{ formatTime(item) }}</span>
            <span class="news-item-title">{{ item.title || 'Untitled' }}</span>
          </NuxtLink>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup>
const refreshIntervalMs = 20000
let refreshTimer
const api = useNewsApi()

const {
  data: currentBrief,
  pending: briefPending,
  error: briefError,
  refresh: refreshBrief,
} = await useAsyncData('current-brief', () => api.getCurrentBrief(), {
  server: false,
})

const {
  data: headlines,
  refresh: refreshHeadlines,
} = await useAsyncData('brief-headlines', () => api.getBriefHeadlines(8), {
  server: false,
})

const briefText = computed(() => currentBrief.value?.summary || 'No summary available yet.')
const briefUpdatedAt = computed(() => formatDate(currentBrief.value?.updated_at))
const recentItems = computed(() =>
  Array.isArray(headlines.value?.results) ? headlines.value.results : []
)

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatTime(item) {
  const value = item.hour_start || item.created_at
  const date = new Date(value || '')
  if (Number.isNaN(date.getTime())) return 'Just now'
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(() => {
  refreshBrief()
  refreshHeadlines()
  refreshTimer = setInterval(() => {
    refreshBrief()
    refreshHeadlines()
  }, refreshIntervalMs)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})

useHead({
  title: 'NousNews · Brief',
  meta: [
    {
      name: 'description',
      content: 'NousNews delivers a live crawler brief with the latest headlines.',
    },
  ],
})
</script>
