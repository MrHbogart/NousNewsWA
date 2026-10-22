<template>
  <span class="im" :class="`level-${level}`" :title="label" :aria-label="label" role="img">
    <svg v-for="index in level" :key="index" viewBox="0 0 12 10" fill="currentColor" aria-hidden="true">
      <path d="M6 1L11 9H1L6 1Z" />
    </svg>
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
.im {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 6px;
  border-radius: 999px;
  border: 1px solid transparent;
}

.im svg {
  width: 10px;
  height: 9px;
  display: block;
}

.level-1 {
  color: #7b661d;
  background: rgba(188, 142, 43, 0.12);
  border-color: rgba(188, 142, 43, 0.28);
}

.level-2 {
  color: #6f4f17;
  background: rgba(184, 116, 33, 0.14);
  border-color: rgba(184, 116, 33, 0.3);
}

.level-3 {
  color: #8d2f2f;
  background: rgba(179, 75, 75, 0.14);
  border-color: rgba(179, 75, 75, 0.34);
}
</style>
