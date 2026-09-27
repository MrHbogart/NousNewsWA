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
        // Pages are offset-based and live updates prepend items, so a page
        // can overlap what we already have.
        const known = new Set(items.value.map((item) => item.id))
        items.value = [...items.value, ...newItems.filter((item) => !known.has(item.id))]
        page.value += 1
        if (newItems.length < pageSize) hasMore.value = false
      }
    } catch (err) {
      error.value = err
      hasMore.value = false
    } finally {
      isLoading.value = false
    }
  }

  // Seed with a page fetched during SSR so the first client load continues from page 1.
  const seed = (initialItems) => {
    items.value = [...initialItems]
    page.value = 1
    hasMore.value = initialItems.length >= pageSize
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
    if (autoLoad && items.value.length === 0) {
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
    seed,
  }
}
