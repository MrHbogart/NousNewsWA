<template>
  <div>
    <div class="site-top">
      <header class="site-bar">
        <div class="container">
          <NuxtLink to="/" class="wordmark" aria-label="NousNews, home">NousNews</NuxtLink>
          <nav class="site-nav" aria-label="Sections">
            <NuxtLink v-for="link in SECTIONS" :key="link.label" :to="link.to" :class="{ 'is-active': isActive(link) }">
              {{ link.label }}
            </NuxtLink>
          </nav>
        </div>
      </header>
      <MarketTicker />
    </div>

    <main class="container">
      <slot />
    </main>

    <!-- The feed scrolls without end, so the front page has no footer to chase. -->
    <footer v-if="route.path !== '/'" class="site-footer">
      <div class="container">
        <NuxtLink to="/" class="wordmark">NousNews</NuxtLink>
        <div>
          <nav aria-label="Site">
            <NuxtLink to="/about">About</NuxtLink>
            <NuxtLink to="/disclaimer">Disclaimer</NuxtLink>
            <NuxtLink to="/privacy">Privacy</NuxtLink>
            <NuxtLink to="/contact">Contact</NuxtLink>
            <a href="/rss.xml">RSS</a>
          </nav>
          <p>NousNews is for information only and is not financial advice.</p>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup>
const route = useRoute()

const SECTIONS = [
  { label: 'Latest', to: '/' },
  { label: 'Daily', to: '/?timeframe=day' },
  { label: 'Weekly', to: '/?timeframe=week' },
  { label: 'Monthly', to: '/?timeframe=month' },
]

function isActive(link) {
  if (route.path !== '/') return false
  const current = route.query.timeframe || ''
  return (link.to.split('timeframe=')[1] || '') === current
}
</script>
