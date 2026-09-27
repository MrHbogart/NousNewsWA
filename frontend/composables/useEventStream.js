// Subscribes to a backend Server-Sent Events stream on the client.
// `path` may be a string or a getter; the stream reopens when it changes.
// EventSource reconnects on its own after network drops.
export const useEventStream = (path, handlers) => {
  if (import.meta.server) return

  const config = useRuntimeConfig()
  const baseUrl = config.public.apiBaseUrl.replace(/\/$/, '')
  let source = null

  const open = (currentPath) => {
    source?.close()
    source = null
    if (!currentPath) return
    source = new EventSource(`${baseUrl}${currentPath}`)
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
    source?.close()
    source = null
  })
}
