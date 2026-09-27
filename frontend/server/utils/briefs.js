// Shared by the sitemap/RSS/robots routes (auto-imported by Nitro).
export const siteUrl = () => useRuntimeConfig().public.siteDomain.replace(/\/$/, '')

export const escapeXml = (value = '') =>
  String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')

export const fetchLatestBriefs = async () => {
  const apiBase = useRuntimeConfig().apiBaseUrl.replace(/\/$/, '')
  try {
    const data = await $fetch(`${apiBase}/briefs/`, { query: { page: 0, limit: 100 }, timeout: 10000 })
    return data?.results || []
  } catch {
    return []
  }
}
