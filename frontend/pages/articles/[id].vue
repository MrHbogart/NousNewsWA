<template>
  <section class="article-page">
    <NuxtLink to="/" class="text-link article-back">All briefs</NuxtLink>

    <p v-if="pending" class="article-state">Pulling up the brief…</p>

    <p v-else-if="error" class="article-state is-error">
      This report could not be loaded. Verify the article ID and API base URL.
    </p>

    <article v-else class="article">
      <div v-if="hasPendingArticleUpdate" class="article-update" role="status">
        <p>Fresh update: this story has moved on since you opened it.</p>
        <button type="button" class="btn article-update-btn" @click="applyPendingUpdate">Show the update</button>
      </div>

      <p v-if="displayedArticle?.day_article" class="article-dayline">
        This 4-hour brief is part of the full day’s article:
        <NuxtLink :to="`/articles/${displayedArticle.day_article.slug}`" class="text-link">
          {{ displayedArticle.day_article.title || 'Read the whole day' }}
        </NuxtLink>
      </p>

      <div :key="articleRenderKey" class="article-stack">
        <header class="article-head">
          <h1 class="article-title">{{ displayedArticle?.title || 'Untitled report' }}</h1>
          <div class="article-meta">
            <span class="article-kind">{{ kindLabel }}<span v-if="periodLabel">, {{ periodLabel }}</span></span>
            <ImportanceMarker :score="displayedArticle?.importance_score" />
            <span v-if="readingMinutes">{{ readingMinutes }} min read</span>
            <span v-if="updatedLabel">Updated {{ updatedLabel }}</span>
          </div>
          <p v-if="cleanSummary" class="lead article-lead">{{ cleanSummary }}</p>
          <div class="article-share">
            <button type="button" class="btn" @click="copyLink">{{ copied ? 'Link copied' : 'Copy link' }}</button>
            <a class="btn" :href="shareLinks.x" target="_blank" rel="noopener noreferrer">Share on X</a>
            <a class="btn" :href="shareLinks.linkedin" target="_blank" rel="noopener noreferrer">Share on LinkedIn</a>
          </div>
        </header>

        <div class="article-columns">
          <section v-if="takeaways.length" class="takeaways" aria-labelledby="takeaways-title">
            <h2 id="takeaways-title" class="takeaways-title">The short version</h2>
            <ul>
              <li v-for="item in takeaways" :key="item">{{ item }}</li>
            </ul>
          </section>

          <div class="article-body">
            <template v-if="articleBlocks.length">
              <template v-for="(block, index) in articleBlocks" :key="index">
                <h2 v-if="block.type === 'h2'">{{ block.text }}</h2>
                <ul v-else-if="block.type === 'ul'">
                  <li v-for="(item, i) in block.items" :key="i">{{ item }}</li>
                </ul>
                <p v-else>{{ block.text }}</p>
              </template>
            </template>
            <p v-else class="article-empty">The full write-up is still being drafted. The takeaways and charts are live now.</p>
          </div>
        </div>

        <section v-if="performance.length" class="article-section" aria-labelledby="markets-title">
          <h2 id="markets-title" class="rule-head">
            How markets moved{{ displayedArticle?.kind === 'aftermath' ? ' after the brief' : ' in this period' }}
          </h2>
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
                  <td>{{ formatPrice(row.low) }} to {{ formatPrice(row.high) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <PriceChart class="perf-chart" :series="priceSeriesList" initially-open />
        </section>

        <p v-if="aftermathLink" class="article-section article-aftermath">
          <NuxtLink :to="`/articles/${aftermathLink.slug}`" class="text-link">
            What happened to prices after this brief
          </NuxtLink>
        </p>

        <div class="article-refs">
          <section v-if="relatedLinks.length" class="article-section" aria-labelledby="related-title">
            <h2 id="related-title" class="rule-head">Meanwhile, in the same window</h2>
            <ul class="related">
              <li v-for="item in relatedLinks" :key="item.uuid">
                <NuxtLink :to="`/articles/${item.slug || item.uuid}`">
                  {{ item.title || 'Untitled brief' }}
                </NuxtLink>
              </li>
            </ul>
          </section>

          <section v-if="references.length" class="article-section" aria-labelledby="sources-title">
            <h2 id="sources-title" class="rule-head">Where the story came from</h2>
            <ol class="sources">
              <li v-for="ref in references" :key="ref.url">
                <a :href="ref.url" target="_blank" rel="noopener noreferrer nofollow">{{ ref.host }}</a>
                <span class="sources-path">{{ ref.path }}</span>
              </li>
            </ol>
          </section>
        </div>
      </div>
    </article>
  </section>
</template>

<script setup>
const route = useRoute()
const api = useNewsApi()
const config = useRuntimeConfig()
const articleId = computed(() => String(route.params.id || ''))

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
.article-page {
  padding-block: var(--space-xl) 0;
}

.article-back {
  font-size: var(--text-sm);
}

.article-state {
  margin-top: var(--space-xl);
  padding-block: var(--space-lg);
  border-top: var(--rule-hair) solid var(--color-ink);
  color: var(--color-muted);
}

.article-state.is-error {
  color: var(--color-error);
}

.article-update {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm) var(--space-lg);
  margin-top: var(--space-lg);
  padding: var(--space-sm) var(--space-lg);
  background: var(--color-ink);
  color: var(--color-paper);
}

.article-update-btn {
  border-color: var(--color-paper);
  color: var(--color-paper);
}

.article-update-btn:hover:not(:disabled) {
  background: var(--color-ink-2);
}

.article-dayline {
  margin-top: var(--space-lg);
  padding-block: var(--space-sm);
  border-block: var(--rule-hair) solid var(--color-rule);
  color: var(--color-ink-2);
}

.article-head {
  margin-top: var(--space-lg);
  padding-top: var(--space-lg);
  border-top: var(--rule-bar) solid var(--color-ink);
}

.article-title {
  min-width: 0;
  max-width: 24ch;
  overflow-wrap: break-word;
  font-family: var(--font-display-2);
  font-size: var(--text-display-s);
  line-height: 1.06;
  letter-spacing: 0;
}

.article-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-xs) var(--space-lg);
  margin-top: var(--space-lg);
  font-size: var(--text-sm);
  color: var(--color-muted);
}

.article-kind {
  font-weight: 600;
  color: var(--color-ink);
}

.article-lead {
  margin-top: var(--space-lg);
  max-width: 62ch;
  color: var(--color-ink-2);
}

.article-share {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
  margin-top: var(--space-lg);
}

/* Body on columns 1 to 7, the takeaways held beside it on 9 to 12. */
.article-columns {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  column-gap: var(--gap-columns);
  row-gap: var(--space-xl);
  align-items: start;
  margin-top: var(--space-2xl);
  padding-top: var(--space-xl);
  border-top: var(--rule-hair) solid var(--color-ink);
}

.article-body {
  grid-column: 1 / span 7;
  grid-row: 1;
  min-width: 0;
  font-size: var(--text-lg);
  line-height: 1.65;
}

.article-body p,
.article-body ul {
  max-width: 65ch;
  margin-bottom: var(--space-md);
}

.article-body p:last-child {
  margin-bottom: 0;
}

.article-body h2 {
  text-wrap: balance;
  margin-top: var(--space-xl);
  margin-bottom: var(--space-sm);
  font-size: var(--text-xl);
  line-height: 1.15;
}

.article-body h2:first-child {
  margin-top: 0;
}

.article-body ul {
  padding-left: 1.2em;
}

.article-body li {
  margin-bottom: var(--space-2xs);
}

.article-empty {
  color: var(--color-muted);
}

.takeaways {
  grid-column: 9 / span 4;
  grid-row: 1;
  position: sticky;
  top: calc(var(--bar-h) + var(--ticker-h) + var(--space-lg));
  padding: var(--space-lg);
  background: var(--color-paper-2);
}

.takeaways-title {
  font-size: var(--text-lg);
  line-height: 1;
  text-transform: uppercase;
}

.takeaways ul {
  display: grid;
  gap: var(--space-sm);
  margin: var(--space-md) 0 0;
  padding: 0;
  list-style: none;
}

.takeaways li {
  padding-top: var(--space-sm);
  border-top: var(--rule-hair) solid var(--color-rule);
  line-height: 1.45;
}

.article-section {
  margin-top: var(--space-3xl);
}

.article-section > h2 {
  min-width: 0;
  overflow-wrap: break-word;
}

.perf-wrap {
  margin-top: var(--space-lg);
  overflow-x: auto;
}

.perf {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.perf th,
.perf td {
  padding: var(--space-sm) var(--space-md);
  text-align: right;
  border-bottom: var(--rule-hair) solid var(--color-rule);
}

.perf th:first-child,
.perf td:first-child {
  padding-left: 0;
}

.perf th:last-child,
.perf td:last-child {
  padding-right: 0;
}

.perf th:first-child {
  text-align: left;
  font-weight: 600;
}

.perf thead th {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-muted);
  border-bottom-color: var(--color-ink);
}

.perf .is-up {
  color: var(--color-up);
}

.perf .is-down {
  color: var(--color-down);
}

/* The chart draws in a fixed viewBox; past eight columns its axis labels grow too large. */
.perf-chart {
  max-width: 54rem;
  margin-top: var(--space-xl);
}

.article-aftermath {
  padding-top: var(--space-md);
  border-top: var(--rule-hair) solid var(--color-ink);
}

/* Related briefs and sources side by side on a wide screen. */
.article-refs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: var(--gap-columns);
}

.related,
.sources {
  display: grid;
  margin: var(--space-md) 0 0;
  padding: 0;
  list-style: none;
}

.related li,
.sources li {
  padding-block: var(--space-sm);
  border-bottom: var(--rule-hair) solid var(--color-rule);
}

.related a {
  font-family: var(--font-display-2);
  line-height: 1.2;
  text-decoration: none;
}

.related a:hover,
.sources a:hover {
  text-decoration: underline;
}

.sources {
  counter-reset: source;
}

.sources li {
  counter-increment: source;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2xs) var(--space-xs);
}

.sources li::before {
  content: counter(source) ".";
  min-width: 2ch;
  color: var(--color-muted);
  font-variant-numeric: tabular-nums;
}

.sources a {
  font-weight: 600;
  text-decoration: none;
}

.sources-path {
  min-width: 0;
  color: var(--color-muted);
  overflow-wrap: anywhere;
}

@media (max-width: 60rem) {
  .article-body,
  .takeaways {
    grid-column: 1 / -1;
    grid-row: auto;
  }

  .takeaways {
    position: static;
  }

  .article-refs {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
