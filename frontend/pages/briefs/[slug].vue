<template>
  <section class="space-y-6">
    <NuxtLink to="/" class="inline-flex items-center gap-2 text-xs text-ink-500 transition hover:text-ink-900">
      <span class="h-px w-10 bg-ink-900/20" />
      Back to brief
    </NuxtLink>

    <div
      v-if="pending"
      class="rounded-2xl border border-ink-900/10 bg-white p-6 text-ink-500"
    >
      Loading brief...
    </div>

    <div
      v-else-if="error"
      class="rounded-2xl border border-ember-500/40 bg-white p-6 text-ember-600"
    >
      This brief could not be loaded. Verify the hour slug and API base URL.
    </div>

    <article v-else class="space-y-5">
      <div class="rounded-2xl border border-ink-900/10 bg-white p-6">
        <p class="text-xs text-ink-500">
          Hourly market brief · {{ hourLabel }}
        </p>
        <h1 class="mt-3 text-3xl text-ink-900 sm:text-4xl">
          {{ brief.title || 'Market brief' }}
        </h1>
        <p class="mt-3 text-sm text-ink-500">
          Updated {{ updatedLabel }}
        </p>
      </div>

      <div class="rounded-2xl border border-ink-900/10 bg-white p-6 text-base text-ink-700">
        <p class="whitespace-pre-line">
          {{ brief.summary || 'No brief summary available yet.' }}
        </p>
      </div>

      <div v-if="references.length" class="rounded-2xl border border-ink-900/10 bg-white p-6">
        <p class="text-xs uppercase tracking-[0.12em] text-ink-500">Sources</p>
        <ul class="mt-3 space-y-2 text-sm text-ink-700">
          <li v-for="ref in references" :key="ref">
            <a :href="ref" target="_blank" rel="noreferrer" class="hover:text-ink-900">
              {{ ref }}
            </a>
          </li>
        </ul>
      </div>
    </article>
  </section>
</template>

<script setup>
const route = useRoute()
const api = useNewsApi()
const config = useRuntimeConfig()
const slug = route.params.slug

const { data: brief, pending, error } = await useAsyncData(`brief-${slug}`,
  () => api.getBrief(slug)
)

const hourLabel = computed(() => formatHour(brief.value?.hour_start))
const updatedLabel = computed(() => formatDate(brief.value?.updated_at))
const references = computed(() => (Array.isArray(brief.value?.references) ? brief.value.references : []))

function formatHour(value) {
  if (!value) return 'unknown hour'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'unknown hour'
  return date.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDate(value) {
  if (!value) return 'unknown time'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'unknown time'
  return date.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

useHead(() => {
  const title = brief.value?.title ? `NousNews · ${brief.value.title}` : 'NousNews · Hourly brief'
  const description = brief.value?.summary
    ? brief.value.summary.slice(0, 160)
    : 'NousNews hourly market brief.'
  const canonical = `${config.public.siteDomain.replace(/\\/$/, '')}/briefs/${slug}`
  return {
    title,
    meta: [
      { name: 'description', content: description },
      { property: 'og:title', content: brief.value?.title || 'NousNews hourly brief' },
      { property: 'og:description', content: description },
      { property: 'og:type', content: 'article' },
      { property: 'og:url', content: canonical },
    ],
    link: [
      { rel: 'canonical', href: canonical },
    ],
  }
})
</script>
