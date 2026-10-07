<template>
  <article class="prose-page">
    <h1>Contact</h1>
    <p>Spotted an error in a brief, have a source to suggest, or have a question about the site? We'd like to hear from you.</p>
    <p v-if="email">
      Email: <a :href="`mailto:${email}`">{{ email }}</a>
    </p>
    <p v-else class="prose-meta">The contact address is being set up. Please check back soon.</p>
  </article>
</template>

<script setup>
const email = useRuntimeConfig().public.contactEmail
useSeoMeta({
  title: 'Contact · NousNews',
  description: 'How to reach the NousNews team.',
})
</script>
