<template>
  <section class="space-y-6">
    <NuxtLink
      to="/"
      class="inline-flex items-center gap-2 text-xs text-ink-500 transition hover:text-ink-900"
    >
      <span class="h-px w-10 bg-ink-900/20" />
      Back to brief
    </NuxtLink>

    <div
      v-if="pending"
      class="rounded-2xl border border-ink-900/10 bg-white p-6 text-ink-500"
    >
      Loading report...
    </div>

    <div
      v-else-if="error"
      class="rounded-2xl border border-ember-500/40 bg-white p-6 text-ember-600"
    >
      This report could not be loaded. Verify the article ID and API base URL.
    </div>

    <article v-else class="article-layout">
      <Transition name="update-banner">
        <div
          v-if="hasPendingArticleUpdate"
          class="rounded-xl border border-sky-500/30 bg-sky-50 px-4 py-3 text-sky-800"
        >
          <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p class="text-sm">
              A newer version of this article is available.
            </p>
            <button
              type="button"
              class="inline-flex items-center justify-center rounded-md border border-sky-500/40 bg-white px-3 py-1.5 text-xs font-medium uppercase tracking-[0.08em] text-sky-700 transition hover:bg-sky-100"
              @click="applyPendingUpdate"
            >
              Load update
            </button>
          </div>
        </div>
      </Transition>

      <div
        v-if="displayedArticle?.day_article"
        class="rounded-xl border border-ink-900/10 bg-white px-4 py-3 text-sm text-ink-700"
      >
        This 4-hour brief is part of the full day's article:
        <NuxtLink :to="`/articles/${displayedArticle.day_article.slug}`" class="font-medium text-ink-900 underline">
          {{ displayedArticle.day_article.title || 'Read the whole day' }}
        </NuxtLink>
      </div>

      <Transition name="article-fade" mode="out-in">
        <div :key="articleRenderKey" class="article-stack">
          <header class="rounded-2xl border border-ink-900/10 bg-white p-6 sm:p-8">
            <p class="article-kicker">
              {{ kindLabel }}<span v-if="periodLabel">, {{ periodLabel }}</span>
            </p>
            <h1 class="article-title">{{ displayedArticle?.title || 'Untitled report' }}</h1>
            <p v-if="cleanSummary" class="article-lead">{{ cleanSummary }}</p>
            <div class="article-meta">
              <ImportanceMarker :score="displayedArticle?.importance_score" />
              <span v-if="readingMinutes">{{ readingMinutes }} min read</span>
              <span v-if="updatedLabel">Updated {{ updatedLabel }}</span>
            </div>
            <div class="article-share">
              <button type="button" class="share-btn" @click="copyLink">{{ copied ? 'Link copied' : 'Copy link' }}</button>
              <a class="share-btn" :href="shareLinks.x" target="_blank" rel="noopener noreferrer">Share on X</a>
              <a class="share-btn" :href="shareLinks.linkedin" target="_blank" rel="noopener noreferrer">Share on LinkedIn</a>
            </div>
          </header>

          <section v-if="takeaways.length" class="takeaways" aria-labelledby="takeaways-title">
            <h2 id="takeaways-title">Key takeaways</h2>
            <ul>
              <li v-for="item in takeaways" :key="item">{{ item }}</li>
            </ul>
          </section>

          <div class="rounded-2xl border border-ink-900/10 bg-white p-6 sm:p-8">
            <div v-if="articleBlocks.length" class="article-body-content">
              <template v-for="(block, index) in articleBlocks" :key="index">
                <h2 v-if="block.type === 'h2'">{{ block.text }}</h2>
                <ul v-else-if="block.type === 'ul'">
                  <li v-for="(item, i) in block.items" :key="i">{{ item }}</li>
                </ul>
                <p v-else>{{ block.text }}</p>
              </template>
            </div>
            <p v-else class="text-ink-400">The full text of this brief isn't available yet.</p>
          </div>

          <section v-if="performance.length" class="rounded-2xl border border-ink-900/10 bg-white p-6 sm:p-8">
            <h2 class="section-title">How markets moved{{ displayedArticle?.kind === 'aftermath' ? ' after the brief' : ' in this period' }}</h2>
            <div class="perf-wrap">
              <table class="perf">
                <thead>
                  <tr><th scope="col">Market</th><th scope="col">Open</th><th scope="col">Last</th><th scope="col">Change</th><th scope="col">Range</th></tr>
                </thead>
                <tbody>
                  <tr v-for="row in performance" :key="row.label">
                    <th scope="row">{{ row.label }}</th>
                    <td>{{ formatPrice(row.open) }}</td>
                    <td>{{ formatPrice(row.close) }}</td>
                    <td :class="`is-${changeDirection(row.pct)}`">{{ formatChange(row.pct) }}</td>
                    <td>{{ formatPrice(row.low) }} – {{ formatPrice(row.high) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <PriceChart class="mt-5" :series="priceSeriesList" initially-open />
          </section>

          <div v-if="aftermathLink" class="rounded-2xl border border-ink-900/10 bg-white p-6">
            <NuxtLink :to="`/articles/${aftermathLink.slug}`" class="text-sm font-medium text-ink-900 underline">
              What happened to prices after this brief
            </NuxtLink>
          </div>

          <div v-if="relatedLinks.length" class="rounded-2xl border border-ink-900/10 bg-white p-6">
            <h2 class="section-title">Also in this period</h2>
            <ul class="mt-3 space-y-2 text-sm text-ink-700">
              <li v-for="item in relatedLinks" :key="item.uuid">
                <NuxtLink :to="`/articles/${item.slug || item.uuid}`" class="hover:text-ink-900">
                  {{ item.title || 'Untitled brief' }}
                </NuxtLink>
              </li>
            </ul>
          </div>

          <div v-if="references.length" class="rounded-2xl border border-ink-900/10 bg-white p-6">
            <h2 class="section-title">Sources</h2>
            <ol class="sources">
              <li v-for="ref in references" :key="ref.url">
                <a :href="ref.url" target="_blank" rel="noopener noreferrer nofollow">{{ ref.host }}</a>
                <span class="sources-path">{{ ref.path }}</span>
              </li>
            </ol>
          </div>
        </div>
      </Transition>
    </article>
  </section>
</template>

<script setup>
const route = useRoute()
const api = useNewsApi()
const config = useRuntimeConfig()
const articleId = computed(() => String(route.params.id || ''))

function resetArticleScroll() {
  if (!process.client) return
  const main = document.querySelector('.app-main')
  if (main && typeof main.scrollTo === 'function') {
    main.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }
  window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
}

function cloneArticlePayload(payload) {
  if (!payload || typeof payload !== 'object') return null
  return JSON.parse(JSON.stringify(payload))
}

// Text only: price ticks update the charts live without re-rendering the
// article or raising the "newer version" banner.
function articleFingerprint(payload) {
  if (!payload || typeof payload !== 'object') return ''
  return [
    payload.updated_at || '',
    payload.title || '',
    payload.summary || '',
    payload.article_content || '',
  ].join('|')
}

function sanitizeArticleText(value = '') {
  return String(value || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<blockquote[^>]*class=["'][^"']*(twitter-tweet|instagram-media|tiktok-embed)[^"']*["'][^>]*>[\s\S]*?<\/blockquote>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&rsquo;/gi, "'")
    .replace(/&ldquo;/gi, '"')
    .replace(/&rdquo;/gi, '"')
    .replace(/&ndash;/gi, '-')
    .replace(/&mdash;/gi, '-')
    .replace(/\s+/g, ' ')
    .trim()
}

const pendingArticleUpdate = ref(null)
const displayedArticle = ref(null)

const { data: articleData, pending, error, refresh: refreshArticle } = await useAsyncData(
  () => `article-${articleId.value}`,
  () => api.getArticle(articleId.value)
)

// A real 404/503 status for crawlers instead of a 200 page with an error message.
if (error.value) {
  const notFound = error.value.statusCode === 404
  throw createError({
    statusCode: notFound ? 404 : 503,
    statusMessage: notFound ? 'Report not found' : 'Report temporarily unavailable',
    fatal: true,
  })
}

watch(articleId, () => {
  refreshArticle()
})

watch(
  articleData,
  (value) => {
    if (!value) return
    if (!displayedArticle.value) {
      displayedArticle.value = cloneArticlePayload(value)
      pendingArticleUpdate.value = null
    }
  },
  { immediate: true }
)

watch(
  () => displayedArticle.value?.slug,
  async (slug) => {
    if (!slug) return
    if (String(route.params.id) === slug) return
    await navigateTo(`/articles/${slug}`, { replace: true })
  }
)

// Live updates arrive over SSE; they're offered as a pending update rather
// than swapped in under the reader.
useEventStream(() => (articleId.value ? `/stream/articles/${encodeURIComponent(articleId.value)}/` : ''), {
  article: (latest) => {
    if (!latest || !displayedArticle.value) return
    const latestSig = articleFingerprint(latest)
    if (latestSig && latestSig !== articleFingerprint(displayedArticle.value)) {
      pendingArticleUpdate.value = cloneArticlePayload(latest)
    } else {
      applyLivePrices(latest)
    }
  },
  prices: applyLivePrices,
})

function applyLivePrices(payload) {
  if (!payload?.price_series || !displayedArticle.value) return
  if (payload.id !== displayedArticle.value.id) return
  displayedArticle.value = { ...displayedArticle.value, price_series: payload.price_series }
  if (pendingArticleUpdate.value) {
    pendingArticleUpdate.value = { ...pendingArticleUpdate.value, price_series: payload.price_series }
  }
}

function applyPendingUpdate() {
  if (!pendingArticleUpdate.value) return
  displayedArticle.value = cloneArticlePayload(pendingArticleUpdate.value)
  pendingArticleUpdate.value = null
}

onMounted(() => {
  resetArticleScroll()
})

watch(
  () => route.fullPath,
  () => {
    resetArticleScroll()
  }
)

const hasPendingArticleUpdate = computed(() => Boolean(pendingArticleUpdate.value))
const articleRenderKey = computed(() => articleFingerprint(displayedArticle.value))
const updatedLabel = computed(() => formatDate(displayedArticle.value?.updated_at))
const KIND_LABELS = { intraday: '4-hour market brief', day: 'Daily market brief', week: 'Weekly market brief', month: 'Monthly market brief' }
const kindLabel = computed(() =>
  displayedArticle.value?.kind === 'aftermath'
    ? 'Aftermath analysis'
    : KIND_LABELS[displayedArticle.value?.timeframe] || 'Market brief'
)
const aftermathLink = computed(() => displayedArticle.value?.aftermath || null)
const relatedLinks = computed(() => {
  const items = displayedArticle.value?.related_articles || []
  return items.filter((item) => item.kind === 'side').slice(0, 2)
})
const cleanSummary = computed(() => sanitizeArticleText(displayedArticle.value?.summary || ''))
const articleBlocks = computed(() => parseArticleBlocks(displayedArticle.value?.article_content || ''))
const takeaways = computed(() =>
  (displayedArticle.value?.impacts || []).filter((item) => typeof item === 'string' && item.trim()).slice(0, 6)
)
const readingMinutes = computed(() => {
  const words = `${cleanSummary.value} ${displayedArticle.value?.article_content || ''}`.split(/\s+/).filter(Boolean).length
  return words > 60 ? Math.max(1, Math.round(words / 220)) : 0
})
const priceSeriesList = computed(() => displayedArticle.value?.price_series || [])
const performance = computed(() =>
  priceSeriesList.value
    .map((series) => ({ label: series.label || series.symbol, ...seriesChange(series) }))
    .filter((row) => Number.isFinite(row.pct))
)
const references = computed(() =>
  (displayedArticle.value?.references || []).flatMap((url) => {
    try {
      const parsed = new URL(url)
      return [{ url, host: parsed.hostname.replace(/^www\./, ''), path: parsed.pathname.length > 1 ? parsed.pathname : '' }]
    } catch {
      return []
    }
  })
)
const PERIOD_FORMATS = {
  intraday: { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false },
  day: { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' },
  week: { month: 'long', day: 'numeric', year: 'numeric' },
  month: { month: 'long', year: 'numeric' },
}
const periodLabel = computed(() => {
  const article = displayedArticle.value
  const start = new Date(article?.period_start || '')
  if (!article || Number.isNaN(start.getTime())) return ''
  const label = start.toLocaleString('en-US', { timeZone: 'UTC', ...(PERIOD_FORMATS[article.timeframe] || PERIOD_FORMATS.day) })
  if (article.timeframe === 'week') return `week of ${label}`
  return article.timeframe === 'intraday' ? `${label} UTC` : label
})

const copied = ref(false)
async function copyLink() {
  try {
    await navigator.clipboard.writeText(articleUrl.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    copied.value = false
  }
}

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  })
}

const siteUrl = config.public.siteDomain.replace(/\/$/, '')
const articleUrl = computed(() => `${siteUrl}/articles/${displayedArticle.value?.slug || articleId.value}`)
const shareLinks = computed(() => {
  const url = encodeURIComponent(articleUrl.value)
  const text = encodeURIComponent(displayedArticle.value?.title || '')
  return {
    x: `https://x.com/intent/post?url=${url}&text=${text}`,
    linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${url}`,
  }
})
const metaDescription = computed(() => cleanSummary.value.slice(0, 160) || 'NousNews market report.')

// schema.org NewsArticle; "<" escaped so article text can't close the script tag.
const jsonLd = computed(() => {
  const article = displayedArticle.value
  if (!article?.id) return ''
  const publisher = { '@type': 'Organization', name: 'NousNews', url: siteUrl }
  return JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'NewsArticle',
    headline: article.title,
    description: metaDescription.value,
    url: articleUrl.value,
    mainEntityOfPage: articleUrl.value,
    image: [`${siteUrl}/og-image.png`],
    datePublished: article.published_at || article.period_end || article.created_at,
    dateModified: article.updated_at,
    author: publisher,
    publisher: { ...publisher, logo: { '@type': 'ImageObject', url: `${siteUrl}/icon-512.png` } },
  }).replace(/</g, '\\u003c')
})

useHead(() => ({
  title: displayedArticle.value?.title ? `${displayedArticle.value.title} · NousNews` : 'NousNews · Report',
  meta: [
    { name: 'description', content: metaDescription.value },
    // Folded into a day article: keep the page reachable but out of the index.
    ...(displayedArticle.value?.day_article ? [{ name: 'robots', content: 'noindex, follow' }] : []),
    { property: 'og:title', content: displayedArticle.value?.title || 'NousNews report' },
    { property: 'og:description', content: metaDescription.value },
    { property: 'og:type', content: 'article' },
    { property: 'og:url', content: articleUrl.value },
  ],
  link: [{ rel: 'canonical', href: articleUrl.value }],
  script: jsonLd.value ? [{ type: 'application/ld+json', innerHTML: jsonLd.value }] : [],
}))
</script>

<style scoped>
.article-fade-enter-active,
.article-fade-leave-active {
  transition: opacity 260ms ease, transform 260ms ease;
}

.article-fade-enter-from,
.article-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

.update-banner-enter-active,
.update-banner-leave-active {
  transition: opacity 220ms ease, transform 220ms ease;
}

.update-banner-enter-from,
.update-banner-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.article-layout {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.article-stack {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.article-kicker {
  margin: 0;
  font-size: 13px;
  color: var(--accent);
  font-weight: 500;
}

.article-title {
  margin: 10px 0 0;
  font-size: clamp(1.75rem, 1.2rem + 2vw, 2.4rem);
  line-height: 1.18;
  letter-spacing: -0.015em;
  color: var(--ink);
}

.article-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  margin-top: 16px;
  font-size: 13px;
  color: var(--ink-soft);
}

.article-share {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.share-btn {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  padding: 5px 12px;
  font: inherit;
  font-size: 12.5px;
  color: var(--ink-soft);
  text-decoration: none;
  cursor: pointer;
}

.share-btn:hover {
  color: var(--ink);
  border-color: rgba(15, 20, 30, 0.2);
}

.share-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.takeaways {
  border-left: 3px solid var(--accent);
  border-radius: 12px;
  background: var(--accent-soft);
  padding: 18px 22px;
}

.takeaways h2,
.section-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}

.takeaways ul {
  margin: 10px 0 0;
  padding-left: 1.1em;
  display: grid;
  gap: 6px;
  font-size: 15px;
  line-height: 1.6;
  color: var(--ink);
}

.perf-wrap {
  margin-top: 14px;
  overflow-x: auto;
}

.perf {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.perf th,
.perf td {
  padding: 8px 10px;
  text-align: right;
  border-bottom: 1px solid var(--line);
}

.perf th:first-child {
  text-align: left;
  font-weight: 500;
  color: var(--ink);
}

.perf thead th {
  font-weight: 500;
  font-size: 12px;
  color: var(--ink-soft);
}

.perf .is-up {
  color: var(--up);
}

.perf .is-down {
  color: var(--down);
}

.sources {
  margin: 12px 0 0;
  padding-left: 1.3em;
  display: grid;
  gap: 6px;
  font-size: 13.5px;
}

.sources a {
  color: var(--ink);
  font-weight: 500;
}

.sources-path {
  margin-left: 6px;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}

.article-lead {
  margin-top: 1rem;
  font-size: 1.04rem;
  line-height: 1.8;
  color: var(--ink-soft);
  max-width: 68ch;
}

.article-body-content {
  max-width: 72ch;
  color: var(--ink);
  font-size: 1.04rem;
  line-height: 1.9;
}

.article-body-content p {
  margin: 0 0 1.1em;
}

.article-body-content p:last-child {
  margin-bottom: 0;
}

.article-body-content h2 {
  margin: 1.6em 0 0.5em;
  font-size: 1.2rem;
  line-height: 1.35;
  font-weight: 600;
}

.article-body-content h2:first-child {
  margin-top: 0;
}

.article-body-content ul {
  margin: 0 0 1.1em;
  padding-left: 1.2em;
  list-style: disc;
}

.article-body-content li {
  margin-bottom: 0.35em;
}

@media (max-width: 640px) {
  .article-kicker {
  margin: 0;
  font-size: 13px;
  color: var(--accent);
  font-weight: 500;
}

.article-title {
  margin: 10px 0 0;
  font-size: clamp(1.75rem, 1.2rem + 2vw, 2.4rem);
  line-height: 1.18;
  letter-spacing: -0.015em;
  color: var(--ink);
}

.article-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  margin-top: 16px;
  font-size: 13px;
  color: var(--ink-soft);
}

.article-share {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.share-btn {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  padding: 5px 12px;
  font: inherit;
  font-size: 12.5px;
  color: var(--ink-soft);
  text-decoration: none;
  cursor: pointer;
}

.share-btn:hover {
  color: var(--ink);
  border-color: rgba(15, 20, 30, 0.2);
}

.share-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.takeaways {
  border-left: 3px solid var(--accent);
  border-radius: 12px;
  background: var(--accent-soft);
  padding: 18px 22px;
}

.takeaways h2,
.section-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}

.takeaways ul {
  margin: 10px 0 0;
  padding-left: 1.1em;
  display: grid;
  gap: 6px;
  font-size: 15px;
  line-height: 1.6;
  color: var(--ink);
}

.perf-wrap {
  margin-top: 14px;
  overflow-x: auto;
}

.perf {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.perf th,
.perf td {
  padding: 8px 10px;
  text-align: right;
  border-bottom: 1px solid var(--line);
}

.perf th:first-child {
  text-align: left;
  font-weight: 500;
  color: var(--ink);
}

.perf thead th {
  font-weight: 500;
  font-size: 12px;
  color: var(--ink-soft);
}

.perf .is-up {
  color: var(--up);
}

.perf .is-down {
  color: var(--down);
}

.sources {
  margin: 12px 0 0;
  padding-left: 1.3em;
  display: grid;
  gap: 6px;
  font-size: 13.5px;
}

.sources a {
  color: var(--ink);
  font-weight: 500;
}

.sources-path {
  margin-left: 6px;
  color: var(--ink-soft);
  overflow-wrap: anywhere;
}

.article-lead {
    font-size: 1rem;
    line-height: 1.72;
  }

  .article-body-content {
    font-size: 1rem;
    line-height: 1.8;
  }
}
</style>
