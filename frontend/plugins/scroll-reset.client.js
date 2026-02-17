import { nextTick } from 'vue'

function resetScrollPosition() {
  const main = document.querySelector('.app-main')
  if (main && typeof main.scrollTo === 'function') {
    main.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }
  window.scrollTo({ top: 0, left: 0, behavior: 'auto' })
}

export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.$router.afterEach(async () => {
    await nextTick()
    requestAnimationFrame(() => {
      resetScrollPosition()
      // Ensure scroll reset after async page content settles.
      requestAnimationFrame(() => {
        resetScrollPosition()
      })
    })
  })
})
