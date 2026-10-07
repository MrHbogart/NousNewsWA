const STATIC_PAGES = ['/about', '/disclaimer', '/privacy', '/contact']

export default defineEventHandler(async (event) => {
  const site = siteUrl()
  const apiBase = useRuntimeConfig().apiBaseUrl.replace(/\/$/, '')
  // Every indexable article (day/week/month, today's 4-hour briefs, aftermaths).
  // A 503 makes crawlers retry, instead of reading a near-empty sitemap while the API is down.
  const articles = await $fetch(`${apiBase}/sitemap/`, { timeout: 10000 })
    .then((data) => data?.results || [])
    .catch(() => {
      throw createError({ statusCode: 503, statusMessage: 'Sitemap temporarily unavailable' })
    })
  const urls = [
    `<url><loc>${escapeXml(site)}/</loc><changefreq>hourly</changefreq></url>`,
    ...STATIC_PAGES.map((path) => `<url><loc>${escapeXml(site + path)}</loc></url>`),
    ...articles.map(
      (row) =>
        `<url><loc>${escapeXml(`${site}/articles/${row.slug}`)}</loc>` +
        (row.updated_at ? `<lastmod>${escapeXml(row.updated_at)}</lastmod>` : '') +
        `</url>`
    ),
  ]
  setHeader(event, 'content-type', 'application/xml; charset=utf-8')
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls.join('')}</urlset>\n`
})
