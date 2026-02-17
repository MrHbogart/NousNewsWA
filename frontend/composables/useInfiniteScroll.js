export const useInfiniteScroll = (fetchFunction, options = {}) => {
  const {
    threshold = 500,
    pageSize = 10,
    autoLoad = true,
  } = options

  const items = ref([])
  const isLoading = ref(false)
  const hasMore = ref(true)
  const page = ref(0)
  const error = ref(null)
  const sentinel = ref(null)

  const loadMore = async () => {
    if (isLoading.value || !hasMore.value) return

    isLoading.value = true
    error.value = null

    try {
      const newItems = await fetchFunction(page.value, pageSize)

      if (!newItems || newItems.length === 0) {
        hasMore.value = false
      } else {
        items.value = [...items.value, ...newItems]
        page.value += 1
      }
    } catch (err) {
      error.value = err
      hasMore.value = false
    } finally {
      isLoading.value = false
    }
  }

  const reset = () => {
    items.value = []
    page.value = 0
    hasMore.value = true
    error.value = null
    isLoading.value = false
  }

  onMounted(() => {
    if (!autoLoad) return
    // Initial load so the page shows historical cards without user scroll
    if (autoLoad) {
      // don't await to avoid blocking mount
      loadMore().catch(() => {})
    }

    // Create intersection observer for sentinel element when it becomes available
    const createObserver = () => {
      if (!sentinel.value) return null
      const observer = new IntersectionObserver(
        (entries) => {
          const [entry] = entries
          if (entry.isIntersecting && hasMore.value && !isLoading.value) {
            loadMore()
          }
        },
        { rootMargin: `${threshold}px` }
      )

      observer.observe(sentinel.value)
      return observer
    }

    let observer = null
    if (sentinel.value) {
      observer = createObserver()
    } else {
      const stopWatch = watch(
        sentinel,
        (val) => {
          if (val) {
            observer = createObserver()
            stopWatch()
          }
        },
        { immediate: false }
      )
    }

    onBeforeUnmount(() => {
      if (observer) observer.disconnect()
    })
  })

  return {
    items,
    isLoading,
    hasMore,
    error,
    sentinel,
    loadMore,
    reset,
  }
}
