<template>
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>

<script setup>
// Site-wide social/share defaults; pages override title/description/url.
const siteUrl = useRuntimeConfig().public.siteDomain.replace(/\/$/, '')
useSeoMeta({
  ogSiteName: 'NousNews',
  ogImage: `${siteUrl}/og-image.png`,
  ogImageWidth: 1200,
  ogImageHeight: 630,
  twitterCard: 'summary_large_image',
  twitterImage: `${siteUrl}/og-image.png`,
})
</script>
