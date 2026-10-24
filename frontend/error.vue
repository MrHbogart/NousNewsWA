<template>
  <NuxtLayout>
    <section class="prose-page">
      <h1>{{ notFound ? 'This page has gone off the tape' : 'We hit a snag' }}</h1>
      <p>
        {{ notFound ? "It doesn’t exist or has moved. The markets haven’t, though." : 'This page is briefly unavailable. Give it a moment and try again.' }}
      </p>
      <p><a href="/" @click.prevent="clearError({ redirect: '/' })">Back to the latest briefs</a></p>
    </section>
  </NuxtLayout>
</template>

<script setup>
const props = defineProps({ error: { type: Object, required: true } })
const notFound = computed(() => props.error?.statusCode === 404)
useHead({ title: 'NousNews', meta: [{ name: 'robots', content: 'noindex' }] })
</script>
