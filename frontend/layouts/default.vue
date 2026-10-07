<template>
  <div class="app-viewport">
    <!-- Fixed background -->
    <div class="app-background"></div>
    
    <!-- Fixed header -->
    <header class="app-header" :class="{ 'is-scrolled': isHeaderScrolled }">
      <div class="app-shell">
        <NuxtLink to="/" class="app-brand">NousNews</NuxtLink>
      </div>
    </header>

    <!-- Scrollable content area -->
    <main class="app-main" @scroll="onScroll">
      <div class="app-shell">
        <slot />
      </div>
      <footer class="app-footer">
        <div class="app-shell">
          <nav aria-label="Site">
            <NuxtLink to="/about">About</NuxtLink>
            <NuxtLink to="/disclaimer">Disclaimer</NuxtLink>
            <NuxtLink to="/privacy">Privacy</NuxtLink>
            <NuxtLink to="/contact">Contact</NuxtLink>
            <a href="/rss.xml">RSS</a>
          </nav>
          <p>NousNews is for information only and is not financial advice.</p>
        </div>
      </footer>
    </main>
  </div>
</template>

<script setup>
const isHeaderScrolled = ref(false)

function onScroll(e) {
  isHeaderScrolled.value = e.target.scrollTop > 0
}
</script>

<style scoped>
.app-viewport {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  position: relative;
}

.app-background {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: radial-gradient(circle at top, #ffffff 0%, #eef2ff 45%, #f6f7fb 100%);
  z-index: -1;
}

.app-header {
  position: relative;
  z-index: 100;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.75);
  backdrop-filter: blur(16px);
  transition: background 280ms ease, border-color 280ms ease;
}

.app-header.is-scrolled {
  background: rgba(255, 255, 255, 0.95);
  border-bottom-color: var(--line);
}

.app-shell {
  margin: 0 auto;
  width: min(820px, 100%);
  padding: 0 22px;
}

.app-header .app-shell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
}

.app-brand {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: inherit;
  text-decoration: none;
}

.app-footer {
  border-top: 1px solid var(--line);
  padding: 24px 0 40px;
  font-size: 13px;
  color: var(--ink-soft);
}

.app-footer nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
}

.app-footer a {
  color: inherit;
}

.app-footer a:hover {
  color: var(--ink);
}

.app-footer p {
  margin: 12px 0 0;
}

.app-meta {
  font-size: 12px;
  color: var(--ink-soft);
}

.app-main {
  flex: 1;
  overflow-y: scroll;
  overflow-x: hidden;
  scroll-behavior: smooth;
  scrollbar-width: thin;
  scrollbar-color: rgba(15, 20, 30, 0.2) transparent;
}

.app-main::-webkit-scrollbar {
  width: 8px;
}

.app-main::-webkit-scrollbar-track {
  background: transparent;
}

.app-main::-webkit-scrollbar-thumb {
  background: rgba(15, 20, 30, 0.2);
  border-radius: 4px;
}

.app-main::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 20, 30, 0.3);
}
</style>
