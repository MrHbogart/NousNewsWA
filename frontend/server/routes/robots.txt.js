export default defineEventHandler((event) => {
  setHeader(event, 'content-type', 'text/plain; charset=utf-8')
  return `User-agent: *\nAllow: /\nDisallow: /agent-control\n\nSitemap: ${siteUrl()}/sitemap.xml\n`
})
