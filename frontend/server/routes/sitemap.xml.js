export default defineEventHandler(async (event) => {
  const site = siteUrl()
  const briefs = await fetchLatestBriefs()
  const urls = [
    `<url><loc>${escapeXml(site)}/</loc><changefreq>hourly</changefreq></url>`,
    ...briefs.map(
      (brief) =>
        `<url><loc>${escapeXml(`${site}/articles/${brief.slug}`)}</loc>` +
        `<lastmod>${escapeXml(brief.updated_at || '')}</lastmod></url>`
    ),
  ]
  setHeader(event, 'content-type', 'application/xml; charset=utf-8')
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${urls.join('')}</urlset>\n`
})
