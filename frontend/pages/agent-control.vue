<template>
  <section class="control-page">
    <div class="control-head">
      <NuxtLink to="/" class="control-back">Back to briefs</NuxtLink>
      <button v-if="isAuthenticated" type="button" class="control-link-btn" @click="logout">
        Logout
      </button>
    </div>

    <div class="control-title-wrap">
      <h1 class="control-title">Agent Control</h1>
      <p class="control-subtitle">Secure operator panel for loop state, logs, statistics, and runtime actions.</p>
    </div>

    <div v-if="!isAuthenticated" class="control-card control-login">
      <h2 class="control-card-title">Sign In</h2>
      <p class="control-muted">Use the control password configured in Django admin.</p>

      <form class="control-login-form" @submit.prevent="handleLogin">
        <label for="control-password" class="control-label">Control password</label>
        <input
          id="control-password"
          v-model="password"
          class="control-input"
          type="password"
          autocomplete="current-password"
          required
        >
        <button type="submit" class="control-btn control-btn-primary" :disabled="loginPending">
          {{ loginPending ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>

      <p v-if="errorMessage" class="control-error">{{ errorMessage }}</p>
    </div>

    <div v-else class="control-grid">
      <div class="control-card">
        <div class="control-card-header">
          <h2 class="control-card-title">Runtime State</h2>
          <button type="button" class="control-link-btn" :disabled="refreshPending" @click="refreshDashboard">
            {{ refreshPending ? 'Refreshing…' : 'Refresh' }}
          </button>
        </div>
        <div class="control-stats-grid">
          <div class="control-stat">
            <span class="control-stat-label">Loop state</span>
            <strong class="control-stat-value">{{ runForever.state || 'unknown' }}</strong>
          </div>
          <div class="control-stat">
            <span class="control-stat-label">Current action</span>
            <strong class="control-stat-value">{{ runForever.current_action || 'idle' }}</strong>
          </div>
          <div class="control-stat">
            <span class="control-stat-label">Iterations</span>
            <strong class="control-stat-value">{{ runForever.iterations ?? 0 }}</strong>
          </div>
          <div class="control-stat">
            <span class="control-stat-label">Agent running</span>
            <strong class="control-stat-value">{{ agentState.running ? 'yes' : 'no' }}</strong>
          </div>
          <div class="control-stat">
            <span class="control-stat-label">Last news run</span>
            <strong class="control-stat-value">{{ fmtDate(runForever.last_news_run_at) }}</strong>
          </div>
          <div class="control-stat">
            <span class="control-stat-label">Last heartbeat</span>
            <strong class="control-stat-value">{{ fmtDate(runForever.last_heartbeat_at) }}</strong>
          </div>
        </div>
      </div>

      <div class="control-card">
        <h2 class="control-card-title">Actions</h2>
        <div class="control-actions">
          <button type="button" class="control-btn control-btn-primary" :disabled="runOnceDisabled" @click="runAction('runOnce')">
            {{ actionPending === 'runOnce' ? 'Running…' : 'Run Once' }}
          </button>
          <button type="button" class="control-btn" :disabled="startDisabled" @click="runAction('start')">
            {{ actionPending === 'start' ? 'Starting…' : 'Start Loop' }}
          </button>
          <button type="button" class="control-btn" :disabled="pauseDisabled" @click="runAction('pause')">
            {{ actionPending === 'pause' ? 'Pausing…' : 'Pause' }}
          </button>
          <button type="button" class="control-btn" :disabled="resumeDisabled" @click="runAction('resume')">
            {{ actionPending === 'resume' ? 'Resuming…' : 'Resume' }}
          </button>
          <button type="button" class="control-btn control-btn-danger" :disabled="stopDisabled" @click="runAction('stop')">
            {{ actionPending === 'stop' ? 'Stopping…' : 'Stop' }}
          </button>
        </div>
        <p v-if="actionMessage" class="control-muted control-status">{{ actionMessage }}</p>
        <p v-if="errorMessage" class="control-error">{{ errorMessage }}</p>
      </div>

      <div class="control-card">
        <h2 class="control-card-title">Statistics ({{ stats.window_hours || 24 }}h)</h2>
        <div class="control-stats-grid">
          <div class="control-stat">
            <span class="control-stat-label">Runs</span>
            <strong class="control-stat-value">{{ stats.runs_total ?? 0 }}</strong>
          </div>
          <div class="control-stat">
            <span class="control-stat-label">Logs</span>
            <strong class="control-stat-value">{{ stats.log_total ?? 0 }}</strong>
          </div>
          <div class="control-stat">
            <span class="control-stat-label">Run status</span>
            <strong class="control-stat-value">{{ formatMap(stats.run_status_counts) }}</strong>
          </div>
          <div class="control-stat">
            <span class="control-stat-label">Log levels</span>
            <strong class="control-stat-value">{{ formatMap(stats.log_level_counts) }}</strong>
          </div>
        </div>
      </div>

      <div class="control-card control-logs">
        <div class="control-card-header">
          <h2 class="control-card-title">Recent Logs</h2>
          <span class="control-muted">{{ logs.length }} entries</span>
        </div>

        <div v-if="logs.length === 0" class="control-muted">No logs available.</div>
        <ul v-else class="control-log-list">
          <li v-for="log in logs" :key="log.id" class="control-log-item">
            <div class="control-log-top">
              <span class="control-log-step">{{ log.step }}</span>
              <span class="control-log-level" :class="`level-${log.level}`">{{ log.level }}</span>
              <span class="control-log-time">{{ fmtDate(log.created_at) }}</span>
            </div>
            <p class="control-log-message">{{ log.message }}</p>
            <pre v-if="log.content" class="control-log-content">{{ log.content }}</pre>
            <p v-if="formatMetadata(log.metadata)" class="control-log-meta">{{ formatMetadata(log.metadata) }}</p>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup>
const api = useAgentControlApi()

const TOKEN_KEY = 'agent_control_token'

const token = ref('')
const password = ref('')
const loginPending = ref(false)
const refreshPending = ref(false)
const actionPending = ref('')
const actionMessage = ref('')
const errorMessage = ref('')

const dashboard = ref(null)
let pollTimer = null

const isAuthenticated = computed(() => !!token.value)
const state = computed(() => dashboard.value?.state || {})
const stats = computed(() => dashboard.value?.stats || {})
const logs = computed(() => dashboard.value?.logs || [])
const runForever = computed(() => state.value.run_forever || {})
const agentState = computed(() => state.value.agent || {})
const hasActionPending = computed(() => !!actionPending.value)
// `enabled` is the desired state; the worker container applies it within ~1s.
const loopRunning = computed(() => !!runForever.value?.enabled)
const loopPaused = computed(() => !!runForever.value?.paused)

const runOnceDisabled = computed(
  () => hasActionPending.value || !!agentState.value?.running || !!runForever.value?.run_once_requested
)
const startDisabled = computed(() => hasActionPending.value || loopRunning.value)
const pauseDisabled = computed(() => hasActionPending.value || !loopRunning.value || loopPaused.value)
const resumeDisabled = computed(() => hasActionPending.value || !loopRunning.value || !loopPaused.value)
const stopDisabled = computed(() => hasActionPending.value || !loopRunning.value)

async function handleLogin() {
  errorMessage.value = ''
  actionMessage.value = ''
  loginPending.value = true
  try {
    const res = await api.login(password.value)
    token.value = res?.access_token || ''
    if (!token.value) {
      throw new Error('No token returned by server')
    }
    if (process.client) {
      sessionStorage.setItem(TOKEN_KEY, token.value)
    }
    password.value = ''
    await refreshDashboard()
  } catch (err) {
    errorMessage.value = extractError(err, 'Invalid password or control access is not configured.')
  } finally {
    loginPending.value = false
  }
}

function logout() {
  token.value = ''
  dashboard.value = null
  actionMessage.value = ''
  errorMessage.value = ''
  if (process.client) {
    sessionStorage.removeItem(TOKEN_KEY)
  }
  stopPolling()
}

async function refreshDashboard() {
  if (!token.value) return
  refreshPending.value = true
  errorMessage.value = ''
  try {
    dashboard.value = await api.getDashboard(token.value, { hours: 24, limit: 120 })
  } catch (err) {
    if (isAuthError(err)) {
      logout()
      errorMessage.value = 'Session expired. Please sign in again.'
      return
    }
    errorMessage.value = extractError(err, 'Unable to load dashboard data.')
  } finally {
    refreshPending.value = false
  }
}

async function runAction(actionName) {
  if (!token.value) return
  errorMessage.value = ''
  actionMessage.value = ''
  actionPending.value = actionName
  try {
    const response = await api[actionName](token.value)
    applyActionState(response)
    actionMessage.value = response?.status ? `Action result: ${response.status}` : 'Action executed.'
  } catch (err) {
    const payload = err?.data || err?.response?._data || {}
    const apiStatus = payload?.status
    if (apiStatus) {
      applyActionState(payload)
      actionMessage.value = `Action result: ${apiStatus}`
      await refreshDashboard()
      return
    }
    if (isAuthError(err)) {
      logout()
      errorMessage.value = 'Session expired. Please sign in again.'
      return
    }
    errorMessage.value = extractError(err, 'Action failed.')
  } finally {
    actionPending.value = ''
    await refreshDashboard()
  }
}

function applyActionState(payload) {
  if (!payload || typeof payload !== 'object') return
  const nextState = { ...(dashboard.value?.state || {}) }
  let changed = false

  if (payload.state && typeof payload.state === 'object') {
    nextState.run_forever = payload.state
    changed = true
  }
  if (payload.agent && typeof payload.agent === 'object') {
    nextState.agent = payload.agent
    changed = true
  }
  if (!changed) return

  dashboard.value = {
    ...(dashboard.value || {}),
    state: nextState,
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => {
    refreshDashboard()
  }, 5000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function isAuthError(err) {
  const status = err?.status || err?.response?.status
  return status === 401 || status === 403
}

function extractError(err, fallback) {
  const payload = err?.data || err?.response?._data || {}
  const detail = payload?.detail || payload?.message
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  return fallback
}

function fmtDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatMap(mapLike) {
  if (!mapLike || typeof mapLike !== 'object') return '-'
  const entries = Object.entries(mapLike)
  if (!entries.length) return '-'
  return entries.map(([k, v]) => `${k} ${v}`).join(', ')
}

function formatMetadata(metadata) {
  if (!metadata || typeof metadata !== 'object') return ''
  try {
    const compact = JSON.stringify(metadata)
    return compact.length > 400 ? `${compact.slice(0, 400)}...` : compact
  } catch {
    return ''
  }
}

onMounted(async () => {
  if (!process.client) return
  const saved = sessionStorage.getItem(TOKEN_KEY) || ''
  if (!saved) return
  token.value = saved
  await refreshDashboard()
  if (token.value) {
    startPolling()
  }
})

watch(isAuthenticated, (authed) => {
  if (authed) {
    startPolling()
  } else {
    stopPolling()
  }
})

onBeforeUnmount(() => {
  stopPolling()
})

useHead({
  title: 'NousNews · Agent Control',
  meta: [
    {
      name: 'robots',
      content: 'noindex,nofollow',
    },
  ],
})
</script>

<style scoped>
.control-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  padding-block: var(--space-xl) 0;
}

.control-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
}

.control-back {
  font-size: var(--text-sm);
  font-weight: 600;
  text-decoration: underline;
}

.control-back:hover {
  color: var(--color-accent);
}

.control-title-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}

.control-title {
  font-size: var(--text-display-s);
  line-height: 1;
  text-transform: uppercase;
}

.control-subtitle {
  color: var(--color-muted);
}

/* State and actions side by side, statistics and logs across. */
.control-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-xl) var(--gap-columns);
}

.control-card {
  min-width: 0;
  padding-top: var(--space-sm);
  border-top: var(--rule-bar) solid var(--color-ink);
}

.control-logs,
.control-card:nth-child(3) {
  grid-column: 1 / -1;
}

.control-login {
  max-width: 28rem;
}

.control-card-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.control-card-title {
  min-width: 0;
  overflow-wrap: break-word;
  font-size: var(--text-lg);
  line-height: 1;
  text-transform: uppercase;
}

.control-card > .control-card-title {
  margin-bottom: var(--space-sm);
}

.control-muted {
  font-size: var(--text-sm);
  color: var(--color-muted);
}

.control-login-form {
  display: grid;
  gap: var(--space-xs);
  margin-top: var(--space-md);
}

.control-label {
  font-size: var(--text-sm);
  font-weight: 600;
}

.control-input {
  width: 100%;
  min-height: var(--control-h-app);
  padding-inline: var(--space-sm);
  border: var(--rule-hair) solid var(--color-muted);
  border-radius: var(--radius-card);
  background: var(--color-paper);
  color: var(--color-ink);
  font-size: var(--text-md);
}

.control-input:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: -2px;
}

.control-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
}

.control-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--control-h-app);
  padding-inline: var(--space-md);
  border: var(--rule-hair) solid var(--color-ink);
  border-radius: var(--radius-card);
  background: transparent;
  color: var(--color-ink);
  font-size: var(--text-sm);
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color var(--dur-micro) var(--ease-out);
}

.control-btn:hover:not(:disabled) {
  background: var(--color-paper-2);
}

.control-btn:active:not(:disabled) {
  background: var(--color-paper-3);
}

.control-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.control-btn-primary {
  background: var(--color-ink);
  color: var(--color-paper);
}

.control-btn-primary:hover:not(:disabled) {
  background: var(--color-ink-2);
}

.control-btn-primary:active:not(:disabled) {
  background: var(--color-ink);
}

.control-btn-danger {
  border-color: var(--color-error);
  color: var(--color-error);
}

.control-link-btn {
  min-height: var(--control-h-app);
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-ink);
  font-size: var(--text-sm);
  font-weight: 600;
  text-decoration: underline;
  white-space: nowrap;
  cursor: pointer;
}

.control-link-btn:hover:not(:disabled) {
  color: var(--color-accent);
}

.control-link-btn:active:not(:disabled) {
  color: var(--color-ink-2);
}

.control-link-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.control-stats-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: var(--gap-columns);
}

.control-stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-sm);
  padding-block: var(--space-xs);
  border-bottom: var(--rule-hair) solid var(--color-rule);
}

.control-stat-label {
  font-size: var(--text-sm);
  color: var(--color-muted);
}

.control-stat-value {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  text-align: right;
  min-width: 0;
  overflow-wrap: anywhere;
}

.control-log-list {
  max-height: 32rem;
  margin: 0;
  padding: 0;
  overflow: auto;
  list-style: none;
  border-top: var(--rule-hair) solid var(--color-ink);
}

.control-log-item {
  padding-block: var(--space-sm);
  border-bottom: var(--rule-hair) solid var(--color-rule);
}

.control-log-top {
  display: flex;
  align-items: baseline;
  gap: var(--space-sm);
  font-size: var(--text-sm);
}

.control-log-step {
  font-weight: 600;
}

.control-log-level {
  color: var(--color-muted);
}

.control-log-level.level-warn {
  color: var(--color-ink);
  font-weight: 600;
}

.control-log-level.level-error {
  color: var(--color-error);
  font-weight: 600;
}

.control-log-time {
  margin-left: auto;
  color: var(--color-muted);
  font-variant-numeric: tabular-nums;
}

.control-log-message {
  margin-top: var(--space-2xs);
}

.control-log-content {
  max-height: 14rem;
  margin: var(--space-xs) 0 0;
  padding: var(--space-xs) var(--space-sm);
  overflow: auto;
  background: var(--color-paper-2);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.control-log-meta {
  margin-top: var(--space-2xs);
  font-size: var(--text-sm);
  color: var(--color-muted);
  overflow-wrap: anywhere;
}

.control-error {
  margin-top: var(--space-sm);
  font-size: var(--text-sm);
  color: var(--color-error);
}

.control-status {
  margin-top: var(--space-sm);
}

@media (max-width: 60rem) {
  .control-grid,
  .control-stats-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .control-btn {
    transition: none;
  }
}
</style>
