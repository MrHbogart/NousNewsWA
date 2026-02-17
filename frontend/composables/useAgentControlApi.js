export const useAgentControlApi = () => {
  const config = useRuntimeConfig()
  const baseUrl = (process.server ? config.apiBaseUrl : config.public.apiBaseUrl).replace(/\/$/, '')

  const request = (path, { method = 'GET', token = '', body, query } = {}) => {
    const headers = {}
    if (token) headers.Authorization = `Bearer ${token}`
    return $fetch(`${baseUrl}${path}`, { method, headers, body, query })
  }

  const login = (password) =>
    request('/agent/control/login/', {
      method: 'POST',
      body: { password },
    })

  const getDashboard = (token, params = {}) =>
    request('/agent/control/dashboard/', {
      token,
      query: params,
    })

  const getState = (token) =>
    request('/agent/control/state/', {
      token,
    })

  const getStats = (token, params = {}) =>
    request('/agent/control/stats/', {
      token,
      query: params,
    })

  const getLogs = (token, params = {}) =>
    request('/agent/control/logs/', {
      token,
      query: params,
    })

  const start = (token) =>
    request('/agent/control/start/', {
      method: 'POST',
      token,
    })

  const runOnce = (token) =>
    request('/agent/control/run-once/', {
      method: 'POST',
      token,
    })

  const pause = (token) =>
    request('/agent/control/pause/', {
      method: 'POST',
      token,
    })

  const resume = (token) =>
    request('/agent/control/resume/', {
      method: 'POST',
      token,
    })

  const stop = (token) =>
    request('/agent/control/stop/', {
      method: 'POST',
      token,
    })

  return {
    login,
    getDashboard,
    getState,
    getStats,
    getLogs,
    start,
    runOnce,
    pause,
    resume,
    stop,
  }
}
