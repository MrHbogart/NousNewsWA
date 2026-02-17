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
          {{ loginPending ? 'Signing in...' : 'Sign in' }}
        </button>
      </form>

      <p v-if="errorMessage" class="control-error">{{ errorMessage }}</p>
    </div>

    <div v-else class="control-grid">
      <div class="control-card">
        <div class="control-card-header">
          <h2 class="control-card-title">Runtime State</h2>
          <button type="button" class="control-link-btn" :disabled="refreshPending" @click="refreshDashboard">
            {{ refreshPending ? 'Refreshing...' : 'Refresh' }}
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
            {{ actionPending === 'runOnce' ? 'Running...' : 'Run Once' }}
          </button>
          <button type="button" class="control-btn" :disabled="startDisabled" @click="runAction('start')">
            {{ actionPending === 'start' ? 'Starting...' : 'Start Loop' }}
          </button>
          <button type="button" class="control-btn" :disabled="pauseDisabled" @click="runAction('pause')">
            {{ actionPending === 'pause' ? 'Pausing...' : 'Pause' }}
          </button>
          <button type="button" class="control-btn" :disabled="resumeDisabled" @click="runAction('resume')">
            {{ actionPending === 'resume' ? 'Resuming...' : 'Resume' }}
          </button>
          <button type="button" class="control-btn control-btn-danger" :disabled="stopDisabled" @click="runAction('stop')">
            {{ actionPending === 'stop' ? 'Stopping...' : 'Stop' }}
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
const loopRunning = computed(() => !!runForever.value?.running)
const loopPaused = computed(() => !!runForever.value?.paused)

const runOnceDisabled = computed(() => hasActionPending.value || !!agentState.value?.running)
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
      localStorage.setItem(TOKEN_KEY, token.value)
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
    localStorage.removeItem(TOKEN_KEY)
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
  return entries.map(([k, v]) => `${k}:${v}`).join(' · ')
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
  const saved = localStorage.getItem(TOKEN_KEY) || ''
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
  padding: 30px 0 54px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.control-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.control-back {
  color: var(--ink-soft);
  text-decoration: none;
  font-size: 12px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.control-back:hover {
  color: var(--ink);
}

.control-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.control-title {
  margin: 0;
  font-size: 30px;
  line-height: 1.2;
  color: var(--ink);
}

.control-subtitle {
  margin: 0;
  color: var(--ink-soft);
  font-size: 14px;
}

.control-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 14px;
}

.control-card {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--glass);
  box-shadow: var(--shadow-soft);
  padding: 16px;
}

.control-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.control-card-title {
  margin: 0;
  font-size: 16px;
  color: var(--ink);
}

.control-muted {
  color: var(--ink-soft);
  font-size: 12px;
}

.control-login-form {
  margin-top: 12px;
  display: grid;
  gap: 10px;
  max-width: 420px;
}

.control-label {
  font-size: 12px;
  color: var(--ink-soft);
}

.control-input {
  width: 100%;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 14px;
}

.control-input:focus-visible {
  outline: 2px solid rgba(29, 78, 216, 0.2);
  border-color: rgba(29, 78, 216, 0.3);
}

.control-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.control-btn {
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  cursor: pointer;
}

.control-btn:hover:not(:disabled) {
  border-color: rgba(15, 20, 30, 0.18);
}

.control-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.control-btn-primary {
  border-color: rgba(29, 78, 216, 0.25);
  color: #11367f;
  background: rgba(29, 78, 216, 0.08);
}

.control-btn-danger {
  border-color: rgba(180, 70, 70, 0.2);
  color: #7f2929;
  background: rgba(180, 70, 70, 0.06);
}

.control-link-btn {
  border: 0;
  background: transparent;
  color: var(--ink-soft);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}

.control-link-btn:hover:not(:disabled) {
  color: var(--ink);
}

.control-stats-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.control-stat {
  padding: 8px 10px;
  border: 1px solid rgba(15, 20, 30, 0.07);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.55);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.control-stat-label {
  font-size: 11px;
  color: var(--ink-soft);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.control-stat-value {
  font-size: 13px;
  line-height: 1.3;
  color: var(--ink);
}

.control-logs {
  padding-bottom: 8px;
}

.control-log-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
  max-height: 480px;
  overflow: auto;
}

.control-log-item {
  border: 1px solid rgba(15, 20, 30, 0.08);
  border-radius: 8px;
  padding: 8px 10px;
  background: rgba(255, 255, 255, 0.7);
}

.control-log-top {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.control-log-step {
  color: var(--ink);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.control-log-level {
  border-radius: 99px;
  padding: 1px 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 10px;
}

.control-log-level.level-info {
  color: #0f3f93;
  background: rgba(29, 78, 216, 0.1);
}

.control-log-level.level-warn {
  color: #8b5a06;
  background: rgba(191, 128, 0, 0.12);
}

.control-log-level.level-error {
  color: #8b2525;
  background: rgba(170, 44, 44, 0.12);
}

.control-log-time {
  color: var(--ink-soft);
  margin-left: auto;
}

.control-log-message {
  margin: 5px 0 0;
  font-size: 12px;
  color: var(--ink-soft);
}

.control-log-content {
  margin: 6px 0 0;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid rgba(15, 20, 30, 0.08);
  background: rgba(255, 255, 255, 0.9);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 11px;
  line-height: 1.4;
  color: #1b1f24;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.control-log-meta {
  margin: 6px 0 0;
  font-size: 11px;
  color: #5a616a;
}

.control-error {
  margin: 10px 0 0;
  color: #8b2525;
  font-size: 12px;
}

.control-status {
  margin: 10px 0 0;
}

@media (max-width: 640px) {
  .control-page {
    padding-top: 24px;
  }

  .control-title {
    font-size: 24px;
  }

  .control-stats-grid {
    grid-template-columns: 1fr;
  }

  .control-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
}
</style>
