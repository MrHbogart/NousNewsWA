import { defineNuxtConfig } from 'nuxt/config'

export default defineNuxtConfig({
  ssr: true,
  devtools: { enabled: false },
  future: {
    compatibilityVersion: 3,
  },
  nitro: {
    compatibilityDate: '2026-02-04',
  },
  experimental: {
    appManifest: false,
  },
  css: ['~/assets/css/fonts.css', '~/assets/css/tailwind.css', '~/assets/css/app.css'],
  // Defaults only: Nuxt overrides these at runtime from NUXT_API_BASE_URL
  // (server-side/SSR calls), NUXT_PUBLIC_API_BASE_URL (browser) and
  // NUXT_PUBLIC_SITE_DOMAIN. process.env here would be frozen at build time.
  runtimeConfig: {
    apiBaseUrl: 'http://127.0.0.1:8081/api',
    public: {
      apiBaseUrl: 'http://127.0.0.1:8081/api',
      siteDomain: 'http://127.0.0.1:3001',
    },
  },
  routeRules: {
    '/**': {
      headers: {
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'X-Frame-Options': 'DENY',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
      },
    },
  },
  components: [{ path: '~/components', pathPrefix: false }],
  app: {
    head: {
      title: 'NousNews',
      htmlAttrs: { lang: 'en', dir: 'ltr' },
      meta: [
        {
          name: 'description',
          content: 'NousNews delivers curated, agent-driven reporting from the sources that matter.',
        },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
      ],
      link: [{ rel: 'alternate', type: 'application/rss+xml', title: 'NousNews', href: '/rss.xml' }],
    },
  },
  postcss: {
    plugins: {
      tailwindcss: {},
      autoprefixer: {},
    },
  },
})
