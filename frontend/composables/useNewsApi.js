export const useNewsApi = () => {
  const config = useRuntimeConfig()
  const baseUrl = (process.server ? config.apiBaseUrl : config.public.apiBaseUrl).replace(/\/$/, '')

  const getHealth = () => $fetch(`${baseUrl}/health/`)
  const getLastHour = () => $fetch(`${baseUrl}/lasthour/`)
  const getBriefs = (params = {}) => {
    const { page = 0, limit = 10 } = params
    return $fetch(`${baseUrl}/briefs/`, { query: { page, limit } })
  }
  const getArticle = (id) => $fetch(`${baseUrl}/articles/${id}/`)

  return {
    getHealth,
    getLastHour,
    getBriefs,
    getArticle,
  }
}
