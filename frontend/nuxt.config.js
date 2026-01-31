import { defineNuxtConfig } from 'nuxt/config'

export default defineNuxtConfig({
  ssr: true,
  devtools: { enabled: false },
  experimental: {
    appManifest: false,
  },
  css: ['~/assets/css/fonts.css', '~/assets/css/tailwind.css', '~/assets/css/app.css'],
  runtimeConfig: {
    apiBaseUrl:
      process.env.NUXT_INTERNAL_API_BASE_URL ||
      process.env.NUXT_API_BASE_URL ||
      'http://127.0.0.1:8081/api',
    public: {
      apiBaseUrl: process.env.NUXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8081/api',
      siteDomain: process.env.NUXT_PUBLIC_SITE_DOMAIN || 'http://127.0.0.1:3001',
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
          content: 'NousNews delivers curated, crawler-driven reporting from the sources that matter.',
        },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
      ],
      link: [],
    },
  },
  postcss: {
    plugins: {
      tailwindcss: {},
      autoprefixer: {},
    },
  },
})
