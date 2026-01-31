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

    <article v-else class="space-y-5">
      <div class="rounded-2xl border border-ink-900/10 bg-white p-6">
        <p class="text-xs text-ink-500">
          {{ article.source || 'Unknown source' }}
          <span v-if="publishedLabel"> · {{ publishedLabel }}</span>
        </p>
        <h1 class="mt-3 text-3xl text-ink-900 sm:text-4xl">
          {{ article.title || 'Untitled report' }}
        </h1>
        <p class="mt-3 text-sm text-ink-500">
          Crawled at {{ fetchedLabel || 'unknown time' }} · Source URL
          <a
            :href="article.url"
            target="_blank"
            rel="noreferrer"
            class="text-ink-700 hover:text-ink-900"
          >
            {{ article.url }}
          </a>
        </p>
      </div>

      <div class="rounded-2xl border border-ink-900/10 bg-white p-6 text-base text-ink-700">
        <p v-if="article.body" class="whitespace-pre-line">
          {{ article.body }}
        </p>
        <p v-else class="text-ink-400">No article body available yet.</p>
      </div>
    </article>
  </section>
</template>

<script setup>
const route = useRoute()
const api = useNewsApi()
const config = useRuntimeConfig()
const articleId = route.params.id

const { data: article, pending, error } = await useAsyncData(`article-${articleId}`,
  () => api.getArticle(articleId)
)

const publishedLabel = computed(() => formatDate(article.value?.published_at))
const fetchedLabel = computed(() => formatDate(article.value?.fetched_at))

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
  })
}

useHead(() => ({
  title: article.value?.title ? `NousNews · ${article.value.title}` : 'NousNews · Report',
  meta: [
    {
      name: 'description',
      content: article.value?.body
        ? article.value.body.slice(0, 160)
        : 'NousNews report details.',
    },
    { property: 'og:title', content: article.value?.title || 'NousNews report' },
    {
      property: 'og:description',
      content: article.value?.body
        ? article.value.body.slice(0, 160)
        : 'NousNews report details.',
    },
    { property: 'og:type', content: 'article' },
    {
      property: 'og:url',
      content: `${config.public.siteDomain.replace(/\\/$/, '')}/articles/${articleId}`,
    },
  ],
  link: [
    {
      rel: 'canonical',
      href: `${config.public.siteDomain.replace(/\\/$/, '')}/articles/${articleId}`,
    },
  ],
}))
</script>
