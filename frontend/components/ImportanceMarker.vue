<template>
  <span class="im" :class="`level-${level}`" :title="label" :aria-label="label" role="img">
    <span v-for="index in 3" :key="index" class="im-bar" :class="{ 'is-on': index <= level }" aria-hidden="true"></span>
  </span>
</template>

<script setup>
const props = defineProps({ score: { type: [Number, String], default: 1 } })

const level = computed(() => {
  const parsed = Math.round(Number(props.score))
  return Number.isFinite(parsed) ? Math.min(3, Math.max(1, parsed)) : 1
})
const LABELS = { 1: 'Localized impact (1 of 3)', 2: 'Regional or sector impact (2 of 3)', 3: 'Global cross-market impact (3 of 3)' }
const label = computed(() => LABELS[level.value])
</script>

<style scoped>
/* A three-step meter, rising like a signal: filled steps are the score. */
.im {
  display: inline-flex;
  align-items: flex-end;
  gap: var(--space-3xs);
  height: var(--space-md);
}

.im-bar {
  width: var(--space-2xs);
  background: var(--color-rule);
}

.im-bar:nth-child(1) {
  height: 40%;
}

.im-bar:nth-child(2) {
  height: 70%;
}

.im-bar:nth-child(3) {
  height: 100%;
}

.im-bar.is-on {
  background: var(--color-ink);
}

.level-3 .im-bar.is-on {
  background: var(--color-accent);
}
</style>
