// Subscribes to a backend Server-Sent Events stream on the client.
// `path` may be a string or a getter; the stream reopens when it changes.
// EventSource reconnects on its own after network drops, but gives up for good
// on an HTTP error (e.g. a 502 while the backend restarts), so reopen it then.
export const useEventStream = (path, handlers) => {
  if (import.meta.server) return

  const config = useRuntimeConfig()
  const baseUrl = config.public.apiBaseUrl.replace(/\/$/, '')
  let source = null
  let retryTimer = null
  let retryDelay = 1000

  const open = (currentPath) => {
    clearTimeout(retryTimer)
    source?.close()
    source = null
    if (!currentPath) return
    source = new EventSource(`${baseUrl}${currentPath}`)
    source.onopen = () => {
      retryDelay = 1000
    }
    source.onerror = () => {
      if (source?.readyState !== EventSource.CLOSED) return
      retryTimer = setTimeout(() => open(currentPath), retryDelay)
      retryDelay = Math.min(retryDelay * 2, 30000)
    }
    for (const [event, handler] of Object.entries(handlers)) {
      source.addEventListener(event, (message) => {
        let data
        try {
          data = JSON.parse(message.data)
        } catch {
          return
        }
        handler(data)
      })
    }
  }

  onMounted(() => {
    watch(() => toValue(path), open, { immediate: true })
  })
  onBeforeUnmount(() => {
    clearTimeout(retryTimer)
    source?.close()
    source = null
  })
}
