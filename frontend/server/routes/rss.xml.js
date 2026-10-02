export default defineEventHandler(async (event) => {
  const site = siteUrl()
  const briefs = await fetchLatestBriefs()
  const items = briefs.map((brief) => {
    const link = `${site}/articles/${brief.slug}`
    const date = brief.published_at || brief.period_end
    return (
      `<item><title>${escapeXml(brief.title)}</title><link>${escapeXml(link)}</link>` +
      `<guid isPermaLink="false">${escapeXml(brief.id)}</guid>` +
      `<description>${escapeXml(brief.summary)}</description>` +
      (date ? `<pubDate>${new Date(date).toUTCString()}</pubDate>` : '') +
      `</item>`
    )
  })
  setHeader(event, 'content-type', 'application/rss+xml; charset=utf-8')
  return (
    `<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>` +
    `<title>NousNews</title><link>${escapeXml(site)}/</link>` +
    `<description>Agent-curated financial market briefs.</description>` +
    `${items.join('')}</channel></rss>\n`
  )
})
