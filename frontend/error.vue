<template>
  <NuxtLayout>
    <section class="prose-page">
      <h1>{{ notFound ? 'Page not found' : 'Something went wrong' }}</h1>
      <p>
        {{ notFound ? "This page doesn't exist or has moved." : 'This page is temporarily unavailable. Please try again shortly.' }}
      </p>
      <p><a href="/" @click.prevent="clearError({ redirect: '/' })">Back to today's market briefs</a></p>
    </section>
  </NuxtLayout>
</template>

<script setup>
const props = defineProps({ error: { type: Object, required: true } })
const notFound = computed(() => props.error?.statusCode === 404)
useHead({ title: 'NousNews', meta: [{ name: 'robots', content: 'noindex' }] })
</script>
