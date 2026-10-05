<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import autumnArtwork from './assets/workbench-autumn.jpg'
import type { ReportKind, WorkbenchDigest } from './workbench'

type Reminder = { id: string; note_id: string | null; note_title: string | null; text: string; due_at: string; status: 'open' | 'done' }
type RecentNote = { id: string; title: string; updated_at: string }
type ArchivePreview = { id: string; title: string; days_remaining: number; purge_at: string }
const props = defineProps<{
  accountId: string
  daily: WorkbenchDigest | null
  weekly: WorkbenchDigest | null
  reminders: Reminder[]
  recentNote: RecentNote | null
  archive: ArchivePreview[]
  loading: boolean
  loaded: boolean
  error: string
  search: string
  busy: boolean
  completing: string[]
}>()
const emit = defineEmits<{
  'update:search': [value: string]
  search: []
  createNote: []
  openNote: [id: string]
  openReport: [report: WorkbenchDigest]
  openHistory: [kind: ReportKind]
  openReminder: [reminder: Reminder]
  completeReminder: [reminder: Reminder]
  openCalendar: []
  openNotebooks: []
  openAssistant: []
  openArchive: [id?: string]
  retry: []
}>()

const selectedKind = ref<ReportKind>('daily')
const now = ref(new Date())
let clockTimer: ReturnType<typeof setInterval> | undefined
const zone = 'Asia/Shanghai'
const dayKey = (value: string | Date) => new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value))
const todayKey = computed(() => dayKey(now.value))
const dateLabel = computed(() => new Intl.DateTimeFormat('zh-CN', { timeZone: zone, year: 'numeric', month: 'long', day: 'numeric' }).format(now.value))
const weekday = computed(() => new Intl.DateTimeFormat('zh-CN', { timeZone: zone, weekday: 'long' }).format(now.value))
const greetings = ['那些随手记下的想法，正在慢慢连成线。', '给自己一点时间，看看最近留下的灵感。', '从一个小发现开始，慢慢展开今天。', '翻翻最近的记录，也许会遇见新的思路。', '这里收着你的思考，也留着新的可能。']
const greeting = computed(() => {
  const seed = [...todayKey.value + props.accountId].reduce((sum, character) => sum + character.charCodeAt(0), 0)
  return greetings[seed % greetings.length]
})
const preferenceKey = computed(() => 'maple-home-report-kind:' + props.accountId)
watch(preferenceKey, key => {
  selectedKind.value = 'daily'
  try {
    const saved = localStorage.getItem(key)
    if (saved === 'daily' || saved === 'weekly') selectedKind.value = saved
  } catch {}
}, { immediate: true })

function selectKind(kind: ReportKind) {
  selectedKind.value = kind
  try { localStorage.setItem(preferenceKey.value, kind) } catch {}
}
const report = computed(() => selectedKind.value === 'daily' ? props.daily : props.weekly)
const kindLabel = computed(() => selectedKind.value === 'daily' ? '日报' : '周报')
const initialLoading = computed(() => props.loading && !props.loaded)
const initialError = computed(() => Boolean(props.error) && !props.loaded)
const reportTitle = computed(() => {
  const item = report.value
  if (item?.note_id && item.title && !/^(日报|周报)[｜|]/.test(item.title)) return item.title
  if (selectedKind.value === 'weekly') return '一周知识回顾'
  if (!item) return '每日知识回顾'
  const key = dayKey(item.period_end)
  if (key === todayKey.value) return '今日知识回顾'
  if (key === dayKey(new Date(now.value.getTime() - 86400000))) return '昨日知识回顾'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: zone, month: 'long', day: 'numeric' }).format(new Date(item.period_end)) + '知识回顾'
})
const reportPeriod = computed(() => {
  if (!report.value) return ''
  const format = (value: string) => new Intl.DateTimeFormat('zh-CN', { timeZone: zone, year: dayKey(value).slice(0, 4) === todayKey.value.slice(0, 4) ? undefined : 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value))
  if (selectedKind.value === 'weekly') return format(report.value.period_start) + ' — ' + format(report.value.period_end)
  return new Intl.DateTimeFormat('zh-CN', { timeZone: zone, month: 'long', day: 'numeric', weekday: 'long', year: dayKey(report.value.period_end).slice(0, 4) === todayKey.value.slice(0, 4) ? undefined : 'numeric' }).format(new Date(report.value.period_end))
})
const reportDescription = computed(() => {
  if (initialLoading.value) return '正在取回你的回顾…'
  if (initialError.value) return '暂时无法读取回顾，可以稍后重试。'
  const item = report.value
  if (!item) return selectedKind.value === 'daily' ? '每天留下的小发现，会在这里慢慢汇成一份回顾。' : '这一周留下的想法，会在这里慢慢连成线。'
  if (item.status === 'pending') return '这份回顾已进入生成计划，准备好后会出现在这里。'
  if (item.status === 'processing') return '正在把这一段时间的记录，整理成一份回顾。'
  if (item.status === 'failed') return '这次回顾还没有整理完成，可以前往生成记录重试。'
  if (item.note_archived) return '这份回顾已收进归档，仍可以前往查看。'
  if (!item.note_active) return '这份回顾的原笔记已清除，可以查看其他生成记录。'
  return item.excerpt || '这份回顾已经准备好了，留点时间看看最近的思考。'
})
const reportTopics = computed(() => report.value?.status === 'ready' && report.value.note_active ? report.value.topics || [] : [])
const reportAction = computed(() => {
  if (initialError.value) return '重新加载'
  if (!report.value) return '查看生成计划'
  if (report.value.note_archived && report.value.status === 'ready') return '前往归档'
  return report.value.status === 'ready' && report.value.note_active ? '阅读' + kindLabel.value : '查看生成记录'
})
const reportState = computed(() => {
  const item = report.value
  if (!item) return ''
  if (item.status === 'ready') return item.note_archived ? '已归档' : item.note_active ? '' : '原笔记已清除'
  return { pending: '待生成', processing: '生成中', failed: '生成未完成' }[item.status]
})
const todayReminders = computed(() => props.reminders.filter(item => dayKey(item.due_at) <= todayKey.value))
const arrangedReminders = computed(() => todayReminders.value.length ? todayReminders.value : props.reminders)
const reminderTitle = computed(() => props.reminders.length && !todayReminders.value.length ? '接下来的小安排' : '今天的小安排')
const expiringArchive = computed(() => props.archive.filter(item => item.days_remaining <= 3))

function formatDate(value: string) {
  const key = dayKey(value)
  const time = new Intl.DateTimeFormat('zh-CN', { timeZone: zone, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
  if (key === todayKey.value) return '今天 ' + time
  if (key === dayKey(new Date(now.value.getTime() - 86400000))) return '昨天 ' + time
  if (key === dayKey(new Date(now.value.getTime() + 86400000))) return '明天 ' + time
  return new Intl.DateTimeFormat('zh-CN', { timeZone: zone, year: dayKey(value).slice(0, 4) === todayKey.value.slice(0, 4) ? undefined : 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
}
function readReport() {
  if (initialError.value) emit('retry')
  else if (report.value) emit('openReport', report.value)
  else emit('openHistory', selectedKind.value)
}
onMounted(() => { clockTimer = setInterval(() => { now.value = new Date() }, 60000) })
onUnmounted(() => { if (clockTimer) clearInterval(clockTimer) })
</script>

<template>
  <div class="home" :class="{ 'has-archive-notice': expiringArchive.length }">
    <header class="home-utility">
      <span class="home-location">工作台</span>
      <div class="home-tools">
        <form class="home-search" role="search" @submit.prevent="emit('search')">
          <button type="submit" aria-label="搜索笔记" :disabled="busy"><AppIcon name="search" /></button>
          <input type="search" :value="search" placeholder="搜索笔记" aria-label="搜索笔记内容" @input="emit('update:search', ($event.target as HTMLInputElement).value)" />
        </form>
        <button type="button" class="accent-button home-new" :disabled="busy" @click="emit('createNote')"><AppIcon name="plus" />新建笔记</button>
      </div>
    </header>
    <section class="home-welcome" aria-labelledby="home-title">
      <div class="home-welcome-copy">
        <p class="home-date"><time :datetime="todayKey">{{ dateLabel }}</time><span aria-hidden="true">·</span>{{ weekday }}</p>
        <h1 id="home-title">欢迎回来，今天也有新发现 <span class="home-leaf" aria-hidden="true">🍁</span></h1>
        <p class="home-greeting">{{ greeting }}</p>
      </div>
      <img class="home-artwork" :src="autumnArtwork" width="900" height="600" alt="" aria-hidden="true" />
    </section>
    <p v-if="error" class="home-error" role="alert"><span>{{ error }}</span><button type="button" class="quiet-button" :disabled="loading" @click="emit('retry')">重试</button></p>
    <div class="home-main-grid" :aria-busy="loading">
      <section class="home-recap" aria-labelledby="recap-title">
        <header class="home-recap-head">
          <span class="home-recap-eyebrow"><AppIcon name="note" />为你整理好的回顾</span>
          <div class="home-report-switch" role="group" aria-label="选择回顾类型">
            <button type="button" :aria-pressed="selectedKind === 'daily'" aria-controls="home-report-content" @click="selectKind('daily')">日报</button>
            <button type="button" :aria-pressed="selectedKind === 'weekly'" aria-controls="home-report-content" @click="selectKind('weekly')">周报</button>
          </div>
        </header>
        <div id="home-report-content" class="home-report-content">
          <div class="home-report-copy">
            <h2 id="recap-title" :title="reportTitle">{{ reportTitle }}</h2>
            <p v-if="reportPeriod" class="home-report-period">{{ reportPeriod }}</p>
            <p class="home-report-description">{{ reportDescription }}</p>
          </div>
          <div class="home-paper-art" aria-hidden="true"><span class="home-paper-back"></span><span class="home-paper-front"><i></i><i></i><i></i><i></i></span><span class="home-paper-leaf">🍂</span></div>
        </div>
        <div v-if="reportTopics.length" class="home-report-topics"><p>值得回看的线索</p><ul><li v-for="topic in reportTopics" :key="topic" :title="topic">{{ topic }}</li></ul></div>
        <footer class="home-recap-foot">
          <button type="button" class="accent-button home-read" :disabled="initialLoading" @click="readReport">{{ initialLoading ? '正在加载…' : reportAction }}<AppIcon name="arrow" /></button>
          <span v-if="reportState" class="home-report-state" role="status">{{ reportState }}</span>
          <time v-else-if="report" :datetime="report.updated_at">{{ formatDate(report.updated_at) }} 生成</time>
        </footer>
        <span class="home-sr-only" role="status" aria-live="polite">{{ kindLabel }}：{{ reportTitle }}，{{ reportPeriod }}</span>
      </section>
      <section class="home-arrangements" aria-labelledby="arrangements-title">
        <header><h2 id="arrangements-title">{{ reminderTitle }}</h2><span v-if="arrangedReminders.length">{{ arrangedReminders.length }} 件</span></header>
        <p class="home-arrangements-subtitle">按自己的节奏，一件件来。</p>
        <ul v-if="arrangedReminders.length" class="home-reminders">
          <li v-for="item in arrangedReminders.slice(0, 2)" :key="item.id">
            <button type="button" class="home-complete" :aria-label="'完成提醒：' + item.text" :disabled="completing.includes(item.id)" @click="emit('completeReminder', item)"><AppIcon :name="completing.includes(item.id) ? 'loader' : 'check'" /></button>
            <button type="button" class="home-reminder-open" :title="item.text" @click="emit('openReminder', item)"><strong>{{ item.text }}</strong><time :datetime="item.due_at">{{ formatDate(item.due_at) }}</time></button>
          </li>
        </ul>
        <p v-else class="home-arrangements-empty">{{ initialLoading ? '正在取回你的安排…' : initialError ? '暂时无法读取安排' : '今天暂无安排，留点时间给自己。' }}</p>
        <button type="button" class="home-text-action" @click="emit('openCalendar')">查看日程<AppIcon name="arrow" /></button>
      </section>
    </div>
    <section class="home-continue" aria-labelledby="home-continue-title">
      <h2 id="home-continue-title">接着上次的灵感</h2>
      <div class="home-continue-grid">
        <button type="button" class="home-entry home-recent" @click="recentNote ? emit('openNote', recentNote.id) : emit('createNote')">
          <AppIcon name="note" /><span class="home-entry-copy"><small>{{ recentNote ? '最近记录' : '开始记录' }}</small><strong :title="recentNote?.title || '给想法一页位置'">{{ recentNote ? recentNote.title || '无标题笔记' : '给想法一页位置' }}</strong><time v-if="recentNote" :datetime="recentNote.updated_at">{{ formatDate(recentNote.updated_at) }}</time><span v-else>记下你的第一个想法</span></span><AppIcon class="home-entry-arrow" name="arrow" />
        </button>
        <button type="button" class="home-entry" @click="emit('openNotebooks')"><AppIcon name="book" /><span class="home-entry-copy"><strong>笔记本</strong><span>看看收藏的想法</span></span><AppIcon class="home-entry-arrow" name="arrow" /></button>
        <button type="button" class="home-entry" @click="emit('openAssistant')"><AppIcon name="spark" /><span class="home-entry-copy"><strong>AI 对话</strong><span>一起理清新思路</span></span><AppIcon class="home-entry-arrow" name="arrow" /></button>
      </div>
    </section>
    <aside v-if="expiringArchive.length" class="home-archive-notice" aria-label="归档清除提醒">
      <AppIcon name="archive" /><span>归档中有笔记将在 3 天内自动清除</span>
      <button type="button" @click="emit('openArchive', expiringArchive[0]?.id)">查看归档<AppIcon name="arrow" /></button>
    </aside>
    <footer class="home-footer"><span><span aria-hidden="true">♧</span>给想法一页位置。</span><button type="button" class="home-text-action" @click="emit('openArchive')">归档<AppIcon name="arrow" /></button></footer>
  </div>
</template>

<style scoped>
.home { display: flex; flex-direction: column; width: 100%; max-width: 1316px; height: 100dvh; min-height: 0; margin: 0 auto; padding: 16px 40px 12px; }
.home-utility { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.home-location { font: 400 19px/1.5 'Songti SC', 'Noto Serif CJK SC', serif; }
.home-tools { display: flex; align-items: center; gap: 14px; }
.home-search { display: flex; align-items: center; width: 260px; min-height: 44px; border: 1px solid var(--line); border-radius: 9px; background: var(--card); }
.home-search button { display: grid; place-items: center; width: 44px; height: 44px; flex: none; padding: 0; border: 0; border-radius: 8px; background: transparent; color: var(--muted); }
.home-search svg { width: 18px; height: 18px; }
.home-search input { width: 100%; min-width: 0; height: 42px; padding: 0 12px 0 0; border: 0; border-radius: 7px; background: transparent; color: var(--ink); font-size: 14px; }
.home-new { min-height: 44px; padding: 0 20px; font-size: 14px; }
.home-welcome { display: grid; grid-template-columns: minmax(0, 1fr) 230px; grid-template-rows: minmax(0, 1fr); align-items: center; gap: 20px; flex: none; height: clamp(106px, 18vh, 152px); min-height: 0; margin: 12px 0 10px; }
.home-date { display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 10px; color: var(--muted); font-size: 15px; line-height: 1.6; font-variant-numeric: tabular-nums; }
.home-welcome h1 { margin: 0; color: var(--ink); font: 400 clamp(29px, 2.4vw, 38px)/1.4 'Songti SC', 'Noto Serif CJK SC', serif; overflow-wrap: anywhere; }
.home-leaf { display: inline-block; font-size: .78em; }
.home-greeting { margin: 10px 0 0; color: var(--muted); font: 400 17px/1.6 'Songti SC', 'Noto Serif CJK SC', serif; }
.home-artwork { display: block; width: 100%; height: 100%; max-height: 100%; object-fit: contain; mix-blend-mode: multiply; mask-image: linear-gradient(to right, transparent, #000 8%, #000 92%, transparent), linear-gradient(to bottom, transparent, #000 12%, #000 88%, transparent); mask-composite: intersect; }
.home-main-grid { display: grid; flex: 1; min-height: 0; grid-template-columns: minmax(0, 1.66fr) minmax(0, 1fr); gap: 24px; }
.home-recap, .home-arrangements { min-width: 0; min-height: 0; padding: 18px 24px; border: 1px solid var(--line); border-radius: 14px; }
.home-recap { display: flex; flex-direction: column; background: var(--hero); }
.home-recap-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px; }
.home-recap-eyebrow { display: inline-flex; align-items: center; gap: 12px; color: var(--accent); font-size: 13px; }
.home-recap-eyebrow svg { width: 22px; height: 22px; flex: none; }
.home-report-switch { display: inline-flex; gap: 3px; padding: 3px; border: 1px solid var(--line); border-radius: 9px; background: var(--selected); }
.home-report-switch button { min-width: 72px; min-height: 44px; padding: 0 14px; border: 0; border-radius: 6px; background: transparent; color: var(--muted); font-size: 14px; transition: color .18s ease, background-color .18s ease; }
.home-report-switch button[aria-pressed='true'] { background: var(--card); color: var(--accent); box-shadow: 0 1px 4px #563a2410; font-weight: 600; }
.home-report-switch button:hover { color: var(--accent); }
.home-report-content { position: relative; display: flex; flex: 1 0 auto; gap: 16px; min-height: 0; padding: 8px 0; }
.home-report-copy { position: relative; z-index: 1; min-width: 0; flex: 1; }
.home-report-copy h2 { margin: 0; font: 400 26px/1.3 'Songti SC', 'Noto Serif CJK SC', serif; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.home-report-period { margin: 4px 0 0; color: var(--muted); font-size: 13px; line-height: 1.5; font-variant-numeric: tabular-nums; }
.home-report-description { max-width: 480px; margin: 8px 0 0; color: var(--muted); font: 400 15px/1.55 'Songti SC', 'Noto Serif CJK SC', serif; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.home-paper-art { position: relative; width: 105px; height: 90px; flex: none; align-self: center; margin-top: 4px; opacity: .8; }
.home-paper-back, .home-paper-front { position: absolute; top: 14px; left: 10px; width: 92px; height: 75px; border: 1px solid #d3b89f; background: #fffaf0; border-radius: 2px; }
.home-paper-back { transform: rotate(10deg); background: #eddac7; }
.home-paper-front { display: grid; align-content: center; gap: 8px; padding: 16px; transform: rotate(-9deg); box-shadow: 0 4px 5px #67452a0a; }
.home-paper-front i { height: 1px; background: #dbc4ad; }
.home-paper-front i:last-child { width: 70%; }
.home-paper-leaf { position: absolute; top: -5px; right: -1px; font-size: 39px; transform: rotate(14deg); }
.home-report-topics { display: flex; align-items: center; gap: 12px; border-top: 1px solid #e2d1c3; padding-top: 10px; }
.home-report-topics p { flex: none; margin: 0; color: var(--muted); font-size: 13px; }
.home-report-topics ul { display: flex; flex: 1; min-width: 0; flex-wrap: nowrap; gap: 8px; margin: 0; padding: 0; list-style: none; }
.home-report-topics li { max-width: 34%; min-width: 0; padding: 4px 10px; border-radius: 24px; background: var(--selected); color: var(--muted); font-size: 12px; line-height: 1.5; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.home-recap-foot { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 10px; }
.home-read { min-width: 148px; min-height: 44px; gap: 14px; font-size: 15px; font-weight: 400; border-radius: 8px; }
.home-read svg { width: 18px; height: 18px; }
.home-recap-foot time, .home-report-state { color: var(--muted); font-size: 12px; line-height: 1.6; font-variant-numeric: tabular-nums; }
.home-arrangements { display: flex; flex-direction: column; background: var(--card); }
.home-arrangements header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.home-arrangements h2 { margin: 0; font: 400 24px/1.4 'Songti SC', 'Noto Serif CJK SC', serif; }
.home-arrangements header > span { flex: none; color: var(--muted); font-size: 13px; }
.home-arrangements-subtitle { margin: 6px 0 10px; color: var(--muted); font-size: 14px; line-height: 1.5; }
.home-reminders { margin: 0; padding: 0; list-style: none; }
.home-reminders li { display: flex; align-items: flex-start; gap: 5px; min-height: 66px; padding: 7px 0; border-bottom: 1px solid var(--line); }
.home-reminders li:last-child { border-bottom: 0; }
.home-complete { position: relative; display: grid; place-items: center; width: 44px; height: 44px; flex: none; margin-left: -10px; padding: 0; border: 0; border-radius: 8px; background: transparent; color: var(--accent); }
.home-complete::before { position: absolute; width: 21px; height: 21px; border: 1.5px solid var(--muted); border-radius: 50%; content: ''; }
.home-complete svg { position: relative; width: 15px; height: 15px; opacity: 0; }
.home-complete:hover svg, .home-complete:focus-visible svg, .home-complete:disabled svg { opacity: 1; }
.home-complete:disabled svg { animation: home-spin 1s linear infinite; }
.home-reminder-open { display: flex; flex-direction: column; align-items: flex-start; gap: 5px; width: 100%; min-width: 0; min-height: 44px; padding: 7px 0 0; border: 0; border-radius: 4px; background: transparent; color: var(--ink); text-align: left; }
.home-reminder-open strong { max-width: 100%; font-size: 15px; font-weight: 400; line-height: 1.6; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.home-reminder-open time { color: var(--muted); font-size: 12px; line-height: 1.6; font-variant-numeric: tabular-nums; }
.home-reminder-open:hover strong { color: var(--accent); }
.home-arrangements-empty { flex: 1; margin: 28px 0; color: var(--muted); font-size: 15px; line-height: 1.8; }
.home-text-action { display: inline-flex; align-items: center; align-self: flex-start; gap: 14px; min-height: 44px; margin-top: auto; padding: 0; border: 0; border-radius: 4px; background: transparent; color: var(--accent); font-size: 14px; }
.home-text-action svg { width: 18px; height: 18px; }
.home-text-action:hover { text-decoration: underline; text-underline-offset: 4px; }
.home-continue { flex: none; margin-top: 14px; }
.home-continue > h2 { margin: 0 0 8px; font: 400 22px/1.3 'Songti SC', 'Noto Serif CJK SC', serif; }
.home-continue-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) repeat(2, minmax(0, 1fr)); gap: 20px; }
.home-entry { display: flex; align-items: center; gap: 18px; width: 100%; min-width: 0; height: 80px; min-height: 80px; padding: 14px 18px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); color: var(--ink); text-align: left; transition: border-color .18s ease; }
.home-entry > svg { width: 26px; height: 26px; flex: none; align-self: flex-start; margin-top: 3px; color: var(--accent); }
.home-entry-copy { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.home-entry-copy strong { font: 400 18px/1.4 'Songti SC', 'Noto Serif CJK SC', serif; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.home-entry-copy small, .home-entry-copy > span, .home-entry-copy time { color: var(--muted); font-size: 12px; line-height: 1.6; }
.home-entry-copy time { font-variant-numeric: tabular-nums; }
.home-entry .home-entry-arrow { width: 18px; height: 18px; margin: 0 0 0 auto; align-self: center; }
.home-entry:hover { border-color: var(--accent); }
.home-footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-top: 10px; padding-top: 3px; border-top: 1px solid var(--line); }
.home-footer > span { display: flex; align-items: center; gap: 12px; color: var(--muted); font-size: 12px; }
.home-footer > span > span { color: var(--accent); font-size: 24px; }
.home-footer .home-text-action { margin: 0; color: var(--muted); font-size: 12px; }
.home-archive-notice { display: flex; align-items: center; flex-wrap: wrap; flex: none; gap: 4px 12px; margin-top: 10px; padding: 0 12px; border: 1px solid var(--line); border-radius: 10px; color: var(--muted); font-size: 12px; line-height: 1.7; }
.home-archive-notice > svg { width: 17px; height: 17px; color: var(--accent); }
.home-archive-notice button { display: inline-flex; align-items: center; gap: 10px; margin-left: auto; min-height: 44px; max-width: 100%; padding: 4px 8px; border: 0; border-radius: 5px; background: transparent; color: var(--accent); text-align: left; font-size: 12px; overflow-wrap: anywhere; }
.home-error { display: flex; align-items: center; gap: 12px; margin: 0 0 16px; color: var(--accent); font-size: 13px; }
.home-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@keyframes home-spin { to { transform: rotate(360deg); } }
@media (max-width: 1200px) {
  .home { padding-right: 32px; padding-left: 32px; }
  .home-welcome { grid-template-columns: minmax(0, 1fr) 210px; }
  .home-main-grid { gap: 18px; }
  .home-recap, .home-arrangements { padding: 18px 20px; }
  .home-paper-art { width: 90px; transform: scale(.8); transform-origin: right center; margin-left: -16px; }
  .home-entry { padding: 14px 16px; gap: 12px; }
  .home-continue-grid { gap: 16px; }
}
@media (max-width: 960px) {
  .home { height: auto; }
  .home-welcome { height: auto; min-height: 132px; }
  .home-main-grid { flex: none; }
  .home-welcome { grid-template-columns: minmax(0, 1fr) 210px; margin-bottom: 24px; }
  .home-welcome h1 { font-size: 32px; }
  .home-greeting { font-size: 16px; }
  .home-main-grid { grid-template-columns: 1fr; }
  .home-recap { min-height: 270px; }
  .home-arrangements { min-height: 0; }
  .home-reminders { margin-top: 10px; }
  .home-continue-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .home-recent { grid-column: 1 / -1; }
}
@media (max-width: 640px) {
  .home { padding: 20px 16px; }
  .home-utility { align-items: flex-start; flex-direction: column; gap: 18px; }
  .home-tools { width: 100%; flex-wrap: wrap; gap: 10px; }
  .home-search { width: auto; flex: 1; min-width: 150px; }
  .home-search input { font-size: 16px; }
  .home-new { padding: 0 12px; font-size: 13px; }
  .home-welcome { display: block; min-height: 0; margin: 24px 0 20px; }
  .home-artwork { display: none; }
  .home-date { margin-bottom: 12px; font-size: 13px; }
  .home-welcome h1 { font-size: 29px; line-height: 1.5; }
  .home-greeting { font-size: 16px; }
  .home-recap, .home-arrangements { padding: 22px 20px; border-radius: 13px; }
  .home-recap-head { gap: 12px; }
  .home-recap-eyebrow { gap: 8px; font-size: 12px; }
  .home-report-switch button { min-width: 52px; padding: 0 10px; }
  .home-report-content { padding-top: 14px; }
  .home-report-copy h2 { font-size: 27px; }
  .home-report-description { font-size: 17px; }
  .home-paper-art { display: none; }
  .home-report-topics { align-items: flex-start; flex-direction: column; gap: 8px; }
  .home-report-topics ul { width: 100%; }
  .home-report-topics li { font-size: 12px; }
  .home-arrangements h2 { font-size: 25px; }
  .home-reminder-open strong { font-size: 16px; }
  .home-continue-grid { grid-template-columns: 1fr; }
  .home-entry { height: auto; padding: 16px; min-height: 82px; }
  .home-entry-copy > span { font-size: 14px; }
  .home-footer { gap: 12px; }
}
.home-recent .home-entry-copy { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 4px 10px; flex: 1; }
.home-recent .home-entry-copy strong { grid-column: 1 / -1; grid-row: 2; }
.home-recent .home-entry-copy time, .home-recent .home-entry-copy > span { grid-column: 2; grid-row: 1; font-size: 11px; white-space: nowrap; }
.home.has-archive-notice .home-welcome { height: 106px; margin-top: 10px; margin-bottom: 12px; }
.home.has-archive-notice .home-report-description { -webkit-line-clamp: 1; }
.home.has-archive-notice .home-recap, .home.has-archive-notice .home-arrangements { padding-top: 14px; padding-bottom: 14px; }
.home-archive-notice button svg { width: 15px; height: 15px; }
@media (max-height: 660px) and (min-width: 961px) {
  .home { padding-top: 8px; padding-bottom: 6px; }
  .home-welcome, .home.has-archive-notice .home-welcome { height: 90px; margin: 6px 0; grid-template-columns: minmax(0, 1fr) 140px; }
  .home-welcome h1 { font-size: 27px; }
  .home-date { margin-bottom: 3px; font-size: 12px; }
  .home-greeting { margin-top: 3px; font-size: 14px; }
  .home-recap, .home-arrangements { padding-top: 14px; padding-bottom: 14px; }
  .home-report-description { -webkit-line-clamp: 1; }
  .home-report-topics p, .home-paper-art { display: none; }
  .home-entry { height: 60px; min-height: 60px; padding-top: 8px; padding-bottom: 8px; }
  .home-continue { margin-top: 8px; }
  .home-continue > h2 { font-size: 18px; margin-bottom: 4px; }
  .home-footer { padding-top: 0; margin-top: 4px; }
  .home-footer .home-text-action { min-height: 32px; }
  .home-archive-notice { margin-top: 6px; }
  .home-archive-notice button { min-height: 32px; }
  .home-report-content { padding: 6px 0; }
  .home-report-copy h2 { font-size: 22px; }
  .home-report-description { margin-top: 5px; font-size: 14px; }
  .home-report-period { margin-top: 3px; font-size: 12px; }
  .home-report-topics { padding-top: 6px; }
  .home-report-topics li { padding-top: 2px; padding-bottom: 2px; }
  .home-recap-foot { margin-top: 6px; }
  .home-arrangements h2 { font-size: 22px; }
  .home-arrangements-subtitle { margin: 4px 0; font-size: 13px; }
  .home-reminders li { min-height: 56px; padding: 2px 0; }
  .home-reminder-open { gap: 2px; padding-top: 4px; }
  .home-reminder-open strong { font-size: 14px; }
  .home-arrangements-empty { margin: 14px 0; }
}
@media (max-width: 960px) {
  .home.has-archive-notice .home-welcome { height: auto; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
</style>
