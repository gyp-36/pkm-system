<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'

type Settings = {
  daily_enabled: boolean
  daily_time: string
  weekly_enabled: boolean
  weekly_weekday: number
  weekly_time: string
  timezone: string
  daily_next_at: string | null
  weekly_next_at: string | null
}
type Run = {
  id: string
  kind: 'daily' | 'weekly'
  status: 'pending' | 'processing' | 'ready' | 'failed'
  note_id: string | null
  note_active: boolean
  note_archived: boolean
  period_start: string
  period_end: string
  scheduled_at: string
  error: string | null
}
type RunKind = 'all' | 'daily' | 'weekly'
type RunPage = { items: Run[]; next_offset: number | null }

const props = defineProps<{ initialKind?: RunKind }>()
const emit = defineEmits<{ openNote: [id: string]; openArchive: [] }>()
const settings = ref<Settings | null>(null)
const runs = ref<Run[]>([])
const nextOffset = ref<number | null>(null)
const currentPage = ref(1)
const activeKind = ref<RunKind>(props.initialKind || 'all')
const loading = ref(false)
const saving = ref(false)
const dailySaving = ref(false)
const retrying = ref<string | null>(null)
const message = ref('')
const error = ref('')
const pageSize = 10
const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const filters: { id: RunKind; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'daily', label: '日报' },
  { id: 'weekly', label: '周报' },
]

function format(value: string) {
  return new Date(value).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatPeriod(run: Run) {
  const start = new Date(run.period_start).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' })
  const end = new Date(run.period_end).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' })
  return run.kind === 'daily' ? `${end} 日报` : `${start} — ${end}`
}

function statusText(status: Run['status']) {
  return status === 'pending' ? '待生成' : status === 'processing' ? '生成中' : status === 'ready' ? '已生成' : '失败'
}

async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败')
  }
  return await response.json() as T
}

async function loadSettings() {
  settings.value = await api<Settings>('/v1/digests/settings')
}

async function loadRuns(page = 1) {
  if (loading.value) return
  loading.value = true
  error.value = ''
  const offset = (page - 1) * pageSize
  const query = new URLSearchParams({ limit: String(pageSize), offset: String(offset) })
  if (activeKind.value !== 'all') query.set('kind', activeKind.value)

  try {
    const result = await api<RunPage>(`/v1/digests?${query.toString()}`)
    runs.value = result.items
    nextOffset.value = result.next_offset
    currentPage.value = page
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '生成记录加载失败'
    runs.value = []
    nextOffset.value = null
  } finally {
    loading.value = false
  }
}

async function selectKind(kind: RunKind) {
  if (loading.value || activeKind.value === kind) return
  activeKind.value = kind
  currentPage.value = 1
  runs.value = []
  nextOffset.value = null
  await loadRuns(1)
}

async function save() {
  if (!settings.value) return
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    settings.value = await api<Settings>('/v1/digests/settings', 'PATCH', {
      weekly_enabled: settings.value.weekly_enabled,
      weekly_weekday: settings.value.weekly_weekday,
      weekly_time: settings.value.weekly_time,
    })
    message.value = '周报计划已保存'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function saveDaily() {
  if (!settings.value) return
  dailySaving.value = true
  error.value = ''
  message.value = ''
  try {
    settings.value = await api<Settings>('/v1/digests/settings', 'PATCH', {
      daily_enabled: settings.value.daily_enabled,
      daily_time: settings.value.daily_time,
    })
    message.value = '日报计划已保存'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '保存失败'
  } finally {
    dailySaving.value = false
  }
}

async function retry(run: Run) {
  retrying.value = run.id
  error.value = ''
  message.value = ''
  try {
    await api(`/v1/digests/${run.id}/retry`, 'POST')
    message.value = '已提交重试'
    await loadRuns(currentPage.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '重试失败'
  } finally {
    retrying.value = null
  }
}

onMounted(() => {
  void Promise.all([loadSettings(), loadRuns()]).catch((cause) => {
    error.value = cause instanceof Error ? cause.message : '页面加载失败'
  })
})
</script>

<template>
  <main class="content-width weekly-content">
    <header class="page-head weekly-page-head"><h1>周报</h1></header>

    <section class="weekly-plans" aria-labelledby="weekly-plans-title">
      <h2 id="weekly-plans-title" class="weekly-section-title">生成计划</h2>
      <div class="weekly-plan-grid">
        <article class="weekly-plan-card">
          <header class="weekly-plan-head">
            <span class="weekly-plan-icon"><AppIcon name="calendar" /></span>
            <h3>日报</h3>
          </header>
          <form v-if="settings" class="weekly-settings" @submit.prevent="saveDaily">
            <label class="weekly-toggle">
              <input v-model="settings.daily_enabled" type="checkbox" />
              <span>启用自动生成</span>
            </label>
            <label class="weekly-field">生成时间<input v-model="settings.daily_time" type="time" required /></label>
            <footer class="weekly-card-foot">
              <p class="weekly-next"><span>下次生成</span><strong>{{ settings.daily_enabled && settings.daily_next_at ? format(settings.daily_next_at) : '未开启' }}</strong></p>
              <button class="accent-button" type="submit" :disabled="dailySaving">{{ dailySaving ? '保存中…' : '保存计划' }}</button>
            </footer>
          </form>
          <p v-else class="weekly-plan-loading">加载中…</p>
        </article>

        <article class="weekly-plan-card">
          <header class="weekly-plan-head">
            <span class="weekly-plan-icon"><AppIcon name="note" /></span>
            <h3>周报</h3>
          </header>
          <form v-if="settings" class="weekly-settings weekly-settings-weekly" @submit.prevent="save">
            <label class="weekly-toggle">
              <input v-model="settings.weekly_enabled" type="checkbox" />
              <span>启用自动生成</span>
            </label>
            <label class="weekly-field">每周生成日
              <select v-model.number="settings.weekly_weekday">
                <option v-for="(day, index) in weekdays" :key="index" :value="index">{{ day }}</option>
              </select>
            </label>
            <label class="weekly-field">生成时间<input v-model="settings.weekly_time" type="time" required /></label>
            <footer class="weekly-card-foot">
              <p class="weekly-next"><span>下次生成</span><strong>{{ settings.weekly_enabled && settings.weekly_next_at ? format(settings.weekly_next_at) : '未开启' }}</strong></p>
              <button class="accent-button" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存计划' }}</button>
            </footer>
          </form>
          <p v-else class="weekly-plan-loading">加载中…</p>
        </article>
      </div>
    </section>

    <p v-if="message" class="weekly-message" role="status">{{ message }}</p>
    <p v-if="error" class="weekly-error" role="alert">{{ error }}</p>

    <section class="weekly-history" aria-labelledby="weekly-history-title">
      <header class="weekly-history-head">
        <h2 id="weekly-history-title">生成记录</h2>
        <div class="weekly-history-tools">
          <div class="weekly-filters" role="group" aria-label="按类型筛选生成记录">
            <button
              v-for="filter in filters"
              :key="filter.id"
              type="button"
              :aria-pressed="activeKind === filter.id"
              :disabled="loading"
              @click="selectKind(filter.id)"
            >{{ filter.label }}</button>
          </div>
          <button class="quiet-button weekly-refresh" type="button" :disabled="loading" @click="loadRuns(currentPage)">
            <AppIcon name="refresh" />刷新
          </button>
        </div>
      </header>

      <div v-if="runs.length" class="weekly-list" :aria-busy="loading">
        <article v-for="run in runs" :key="run.id" class="weekly-item">
          <div class="weekly-item-main">
            <strong>{{ formatPeriod(run) }}</strong>
            <div class="weekly-item-meta">
              <span class="weekly-kind">{{ run.kind === 'daily' ? '日报' : '周报' }}</span>
              <span>生成时间：{{ format(run.scheduled_at) }}</span>
              <span v-if="run.error" class="weekly-item-error">{{ run.error }}</span>
            </div>
          </div>
          <span class="weekly-status" :class="run.status">{{ statusText(run.status) }}</span>
          <div class="weekly-item-actions">
            <button v-if="run.status === 'ready' && run.note_id && run.note_active" class="quiet-button" type="button" @click="emit('openNote', run.note_id)">打开笔记</button>
            <button v-else-if="run.status === 'ready' && run.note_archived" class="quiet-button" type="button" @click="emit('openArchive')">前往归档</button>
            <span v-else-if="run.status === 'ready' && !run.note_active" class="weekly-status">原笔记已删除</span>
            <button v-else-if="run.status === 'failed'" class="quiet-button" type="button" :disabled="retrying === run.id" @click="retry(run)">{{ retrying === run.id ? '重试中…' : '重试' }}</button>
          </div>
        </article>
      </div>
      <div v-else class="weekly-empty" role="status">{{ loading ? '加载中…' : error ? '加载失败，请刷新重试' : '暂无生成记录' }}</div>

      <nav class="weekly-pagination" aria-label="生成记录分页">
        <button class="quiet-button" type="button" :disabled="loading || currentPage <= 1" @click="loadRuns(currentPage - 1)">上一页</button>
        <span>第 {{ currentPage }} 页</span>
        <button class="quiet-button" type="button" :disabled="loading || nextOffset === null" @click="loadRuns(currentPage + 1)">下一页</button>
      </nav>
    </section>
  </main>
</template>

<style scoped>
.weekly-content { width: min(100%, 1020px); margin: 0 auto; padding: 30px 28px 56px; }
.weekly-page-head { margin: 0 0 24px; }
.weekly-section-title { margin: 0 0 12px; font-size: 15px; font-weight: 600; }
.weekly-plan-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.weekly-plan-card, .weekly-history { min-width: 0; border: 1px solid var(--line); border-radius: 15px; background: var(--card); }
.weekly-plan-card { display: flex; flex-direction: column; padding: 19px 20px 16px; }
.weekly-plan-head { display: flex; align-items: center; gap: 11px; min-width: 0; margin-bottom: 15px; }
.weekly-plan-icon { display: grid; flex: none; place-items: center; width: 36px; height: 36px; border-radius: 10px; background: var(--hero); color: var(--accent); }
.weekly-plan-icon :deep(svg) { width: 19px; height: 19px; }
.weekly-plan-head h3 { min-width: 0; margin: 0; font: 400 19px 'Songti SC', 'Noto Serif CJK SC', serif; }
.weekly-settings { display: grid; grid-template-columns: minmax(0, 1fr) minmax(120px, .8fr); align-items: end; gap: 13px 12px; min-width: 0; }
.weekly-settings-weekly { grid-template-columns: minmax(0, 1.1fr) minmax(100px, .8fr) minmax(100px, .8fr); }
.weekly-toggle { display: flex; min-width: 0; min-height: 44px; align-items: center; gap: 9px; color: var(--ink); font-size: 13px; }
.weekly-toggle input { width: 17px; height: 17px; flex: none; accent-color: var(--accent); }
.weekly-field { display: grid; min-width: 0; gap: 6px; color: var(--muted); font-size: 11px; }
.weekly-field input, .weekly-field select { width: 100%; min-width: 0; height: 44px; padding: 0 9px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); color: var(--ink); font-size: 13px; }
.weekly-card-foot { display: flex; grid-column: 1 / -1; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; margin-top: 1px; padding-top: 12px; border-top: 1px solid var(--line); }
.weekly-next { display: grid; min-width: 0; gap: 3px; margin: 0; }
.weekly-next span { color: var(--muted); font-size: 10px; }
.weekly-next strong { overflow-wrap: anywhere; font-size: 12px; font-weight: 500; font-variant-numeric: tabular-nums; }
.weekly-card-foot .accent-button { min-width: 104px; min-height: 42px; }
.weekly-plan-loading { min-height: 118px; margin: 0; padding-top: 20px; color: var(--muted); font-size: 12px; }
.weekly-message, .weekly-error { margin: 12px 0 0; font-size: 12px; }
.weekly-message { color: #557f60; }
.weekly-error { color: #a95042; }
.weekly-history { margin-top: 24px; overflow: hidden; }
.weekly-history-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-width: 0; padding: 14px 19px; border-bottom: 1px solid var(--line); }
.weekly-history-head h2 { flex: none; margin: 0; font: 400 21px/1.35 'Songti SC', 'Noto Serif CJK SC', serif; }
.weekly-history-tools { display: flex; min-width: 0; align-items: center; gap: 7px; }
.weekly-filters { display: flex; min-width: 0; align-items: center; gap: 3px; padding: 3px; border: 1px solid var(--line); border-radius: 9px; background: var(--page); }
.weekly-filters button { min-width: 52px; min-height: 44px; padding: 0 10px; border: 0; border-radius: 6px; background: transparent; color: var(--muted); font-size: 12px; white-space: nowrap; }
.weekly-filters button[aria-pressed='true'] { background: var(--card); color: var(--accent); box-shadow: 0 1px 3px #4b32251c; }
.weekly-refresh { display: inline-flex; min-height: 44px; align-items: center; gap: 6px; white-space: nowrap; }
.weekly-refresh :deep(svg) { width: 15px; height: 15px; }
.weekly-list { padding: 0 19px; }
.weekly-item { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(86px, auto); align-items: center; gap: 16px; min-width: 0; padding: 14px 0; border-bottom: 1px solid var(--line); }
.weekly-item:last-child { border-bottom: 0; }
.weekly-item-main { display: grid; min-width: 0; gap: 5px; }
.weekly-item-main > strong { overflow-wrap: anywhere; font-size: 13px; font-weight: 550; line-height: 1.5; }
.weekly-item-meta { display: flex; min-width: 0; flex-wrap: wrap; gap: 4px 12px; color: var(--muted); font-size: 11px; line-height: 1.55; }
.weekly-item-meta > span { overflow-wrap: anywhere; }
.weekly-item-meta .weekly-kind { color: var(--accent); }
.weekly-item .weekly-item-error { flex-basis: 100%; color: #a95042; }
.weekly-status { display: inline-flex; min-height: 27px; flex: none; align-items: center; gap: 6px; padding: 0 9px; border-radius: 999px; background: #f5efdf; color: #8b5b27; font-size: 11px; white-space: nowrap; }
.weekly-status::before { width: 6px; height: 6px; border-radius: 50%; background: currentColor; content: ''; }
.weekly-status.ready { background: #eaf2ec; color: #356b50; }
.weekly-status.failed { background: #f8ece8; color: #9e493d; }
.weekly-status.processing { background: var(--hero); color: var(--accent); }
.weekly-status.pending { background: #f5efdf; color: #8b5b27; }
.weekly-item-actions { display: flex; min-width: 0; justify-content: flex-end; }
.weekly-item-actions .quiet-button { min-height: 44px; white-space: nowrap; }
.weekly-empty { padding: 29px 20px; color: var(--muted); text-align: center; font-size: 13px; }
.weekly-pagination { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 10px 16px 13px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.weekly-pagination .quiet-button { min-width: 72px; min-height: 44px; border: 1px solid var(--line); border-radius: 8px; }
.weekly-filters button:focus-visible, .weekly-pagination button:focus-visible { outline-offset: 1px; }
@media (max-width: 820px) {
  .weekly-plan-grid { grid-template-columns: minmax(0, 1fr); }
  .weekly-settings-weekly { grid-template-columns: minmax(0, 1fr) minmax(112px, .7fr) minmax(112px, .7fr); }
}
@media (max-width: 600px) {
  .weekly-content { padding: 22px 18px 40px; }
  .weekly-page-head { margin-bottom: 19px; }
  .weekly-plan-card { padding: 17px; }
  .weekly-settings, .weekly-settings-weekly { grid-template-columns: minmax(0, 1fr) minmax(115px, .8fr); }
  .weekly-settings .weekly-toggle { grid-column: 1 / -1; }
  .weekly-card-foot { align-items: stretch; flex-direction: column; }
  .weekly-card-foot .accent-button { width: 100%; }
  .weekly-history-head { align-items: flex-start; flex-direction: column; padding: 14px; }
  .weekly-history-tools { width: 100%; justify-content: space-between; }
  .weekly-filters { flex: 1; }
  .weekly-filters button { flex: 1; }
  .weekly-refresh { padding: 0 7px; }
  .weekly-list { padding: 0 14px; }
  .weekly-item { grid-template-columns: minmax(0, 1fr) auto; gap: 8px 12px; padding: 13px 0; }
  .weekly-item-main { grid-column: 1 / -1; }
  .weekly-item-actions { justify-self: end; }
  .weekly-pagination { gap: 8px; }
}
</style>
