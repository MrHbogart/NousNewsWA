const REQUEST_TIMEOUT_MS = 10000

export const useNewsApi = () => {
  const config = useRuntimeConfig()
  const baseUrl = (process.server ? config.apiBaseUrl : config.public.apiBaseUrl).replace(/\/$/, '')
  const request = (path, opts = {}) => $fetch(`${baseUrl}${path}`, { timeout: REQUEST_TIMEOUT_MS, ...opts })

  const getHealth = () => request('/health/')
  const getLastHour = () => request('/lasthour/')
  const getBriefs = (params = {}) => {
    const { page = 0, limit = 10 } = params
    return request('/briefs/', { query: { page, limit } })
  }
  const getArticle = (id) => request(`/articles/${id}/`)

  return {
    getHealth,
    getLastHour,
    getBriefs,
    getArticle,
  }
}
