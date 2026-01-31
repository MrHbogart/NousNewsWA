export const useNewsApi = () => {
  const config = useRuntimeConfig()
  const baseUrl = (process.server ? config.apiBaseUrl : config.public.apiBaseUrl).replace(/\/$/, '')

  const getSummary = (limit = 5) => $fetch(`${baseUrl}/articles/summary/?limit=${limit}`)
  const getHealth = () => $fetch(`${baseUrl}/health/`)
  const getCrawlerStatus = () => $fetch(`${baseUrl}/crawler/status/`)
  const getCrawlerLogs = (params = {}) => $fetch(`${baseUrl}/crawler/logs/`, { params })
  const getCurrentBrief = () => $fetch(`${baseUrl}/briefs/current/`)
  const getBriefHeadlines = (limit = 12) => $fetch(`${baseUrl}/briefs/headlines/?limit=${limit}`)
  const getBrief = (slug) => $fetch(`${baseUrl}/briefs/${slug}/`)
  const getBriefs = () => $fetch(`${baseUrl}/briefs/`)

  return {
    getSummary,
    getHealth,
    getCrawlerStatus,
    getCrawlerLogs,
    getCurrentBrief,
    getBriefHeadlines,
    getBrief,
    getBriefs,
  }
}
