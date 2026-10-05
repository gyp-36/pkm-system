<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

type TraceStep = {
  index: number
  kind: string
  name: string
  status: string
  duration_ms: number | null
  at: string
  summary: Record<string, unknown>
}
type Trace = {
  id: string
  user_id: string
  conversation_id: string | null
  assistant_message_id: string | null
  entrypoint: string
  model_name: string | null
  status: string
  error_type: string | null
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  steps: TraceStep[]
}
type TracePage = { items: Trace[]; total: number; limit: number; offset: number }

const props = defineProps<{ mode: 'list' | 'message'; messageId?: string }>()
const loading = ref(false)
const error = ref('')
const page = ref<TracePage>({ items: [], total: 0, limit: 50, offset: 0 })
const selected = ref<Trace | null>(null)
const entrypoint = ref('')
const status = ref('')
const fromDate = ref('')
const toDate = ref('')

const entrypointNames: Record<string, string> = {
  ask: '即时问答',
  conversation: '对话问答',
  conversation_stream: '流式对话',
  analyze: '笔记分析',
  classify: '分类建议',
}

function formatDate(value: string | null) {
  if (!value) return '进行中'
  return new Date(value).toLocaleString('zh-CN')
}

function safeDuration(value: number | null) {
  return value === null ? '—' : `${value} ms`
}

async function api<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: 'same-origin' })
  if (!response.ok) throw new Error(response.status === 404 ? '未找到调用链或开发者追踪未启用' : `请求失败（${response.status}）`)
  return response.json() as Promise<T>
}

async function loadList(offset = 0) {
  loading.value = true
  error.value = ''
  selected.value = null
  try {
    const params = new URLSearchParams({ limit: '50', offset: String(offset) })
    if (entrypoint.value) params.set('entrypoint', entrypoint.value)
    if (status.value) params.set('status', status.value)
    if (fromDate.value) params.set('started_from', new Date(`${fromDate.value}T00:00:00`).toISOString())
    if (toDate.value) params.set('started_to', new Date(`${toDate.value}T23:59:59.999`).toISOString())
    page.value = await api<TracePage>(`/v1/dev/assistant-traces?${params}`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '调用链加载失败'
  } finally {
    loading.value = false
  }
}

async function openTrace(id: string) {
  loading.value = true
  error.value = ''
  try {
    selected.value = await api<Trace>(`/v1/dev/assistant-traces/${id}`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '调用链加载失败'
  } finally {
    loading.value = false
  }
}

async function loadMessageTrace() {
  if (!props.messageId) return
  loading.value = true
  error.value = ''
  selected.value = null
  try {
    selected.value = await api<Trace>(`/v1/dev/assistant-traces/by-message/${props.messageId}`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '调用链加载失败'
  } finally {
    loading.value = false
  }
}

watch(() => props.messageId, () => {
  if (props.mode === 'message') void loadMessageTrace()
})
onMounted(() => {
  if (props.mode === 'message') void loadMessageTrace()
  else void loadList()
})
</script>

<template>
  <section class="trace-explorer" :class="{ 'trace-inline': mode === 'message' }">
    <template v-if="mode === 'list' && !selected">
      <header class="trace-heading">
        <div><h2>Agent 调用链</h2><p>本地开发环境的脱敏执行记录，保留 30 天。</p></div>
        <button type="button" class="trace-refresh" :disabled="loading" @click="loadList()">刷新</button>
      </header>
      <form class="trace-filters" @submit.prevent="loadList()">
        <label>入口<select v-model="entrypoint"><option value="">全部</option><option v-for="(name, key) in entrypointNames" :key="key" :value="key">{{ name }}</option></select></label>
        <label>状态<select v-model="status"><option value="">全部</option><option value="success">成功</option><option value="error">失败</option><option value="cancelled">取消</option><option value="running">运行中</option></select></label>
        <label>开始日期<input v-model="fromDate" type="date" /></label>
        <label>结束日期<input v-model="toDate" type="date" /></label>
        <button type="submit" :disabled="loading">筛选</button>
      </form>
      <p v-if="error" class="trace-error" role="alert">{{ error }}</p>
      <p v-else-if="loading" class="trace-empty">正在读取调用记录…</p>
      <div v-else-if="page.items.length" class="trace-list">
        <button v-for="item in page.items" :key="item.id" type="button" class="trace-row" @click="openTrace(item.id)">
          <span class="trace-status-dot" :class="`status-${item.status}`"></span>
          <span class="trace-row-main"><strong>{{ entrypointNames[item.entrypoint] || item.entrypoint }}</strong><small>{{ item.model_name || '模型未识别' }} · {{ formatDate(item.started_at) }}</small></span>
          <span class="trace-row-meta">{{ safeDuration(item.duration_ms) }}<small>{{ item.user_id.slice(0, 8) }}</small></span>
        </button>
        <footer class="trace-pagination"><span>{{ page.total }} 条记录</span><button type="button" :disabled="page.offset === 0 || loading" @click="loadList(Math.max(0, page.offset - page.limit))">上一页</button><button type="button" :disabled="page.offset + page.limit >= page.total || loading" @click="loadList(page.offset + page.limit)">下一页</button></footer>
      </div>
      <p v-else class="trace-empty">没有符合条件的调用记录。</p>
    </template>

    <template v-else>
      <header v-if="mode === 'list'" class="trace-detail-heading"><button type="button" @click="loadList(page.offset)">← 返回记录</button><h3>调用详情</h3></header>
      <p v-if="loading" class="trace-empty">正在读取调用链…</p>
      <p v-else-if="error" class="trace-error" role="alert">{{ error }}</p>
      <template v-else-if="selected">
        <header class="trace-summary">
          <span class="trace-status-dot" :class="`status-${selected.status}`"></span>
          <strong>{{ entrypointNames[selected.entrypoint] || selected.entrypoint }}</strong>
          <span>{{ selected.status === 'success' ? '成功' : selected.status === 'running' ? '运行中' : selected.status === 'cancelled' ? '已取消' : '失败' }}</span>
          <span>{{ safeDuration(selected.duration_ms) }}</span>
        </header>
        <dl class="trace-meta"><div><dt>模型</dt><dd>{{ selected.model_name || '—' }}</dd></div><div><dt>开始</dt><dd>{{ formatDate(selected.started_at) }}</dd></div><div><dt>账号</dt><dd>{{ selected.user_id }}</dd></div><div v-if="selected.error_type"><dt>错误类型</dt><dd>{{ selected.error_type }}</dd></div></dl>
        <ol v-if="selected.steps.length" class="trace-steps">
          <li v-for="step in selected.steps" :key="step.index" :class="`step-${step.status}`">
            <span class="trace-step-index">{{ step.index }}</span>
            <div class="trace-step-body"><div class="trace-step-title"><strong>{{ step.name }}</strong><span>{{ step.kind }}</span><time>{{ safeDuration(step.duration_ms) }}</time></div><pre v-if="Object.keys(step.summary || {}).length">{{ JSON.stringify(step.summary, null, 2) }}</pre><small>{{ formatDate(step.at) }}</small></div>
          </li>
        </ol>
        <p v-else class="trace-empty">此调用没有记录到可展示的步骤。</p>
      </template>
    </template>
  </section>
</template>

<style scoped>
.trace-explorer{display:flex;flex-direction:column;gap:16px;color:var(--ink,#34312e)}
.trace-inline{margin:14px 0;padding:16px;border:1px solid var(--line,#e3e0dc);border-radius:12px;background:var(--surface,#fff)}
.trace-heading,.trace-detail-heading,.trace-summary,.trace-step-title,.trace-pagination{display:flex;align-items:center;gap:12px}
.trace-heading{justify-content:space-between}.trace-heading h2,.trace-detail-heading h3{margin:0;font-size:18px}.trace-heading p{margin:5px 0 0;color:var(--muted,#777);font-size:12px}
.trace-refresh,.trace-detail-heading button,.trace-pagination button,.trace-filters button{border:1px solid var(--line,#dedbd7);border-radius:8px;background:transparent;padding:7px 10px;color:inherit;cursor:pointer}
.trace-filters{display:flex;align-items:end;gap:10px;flex-wrap:wrap}.trace-filters label{display:grid;gap:4px;color:var(--muted,#777);font-size:11px}.trace-filters select,.trace-filters input{min-height:34px;border:1px solid var(--line,#dedbd7);border-radius:7px;background:var(--surface,#fff);padding:5px 8px;color:inherit}
.trace-list{display:grid;border-top:1px solid var(--line,#e5e2de)}.trace-row{display:flex;align-items:center;gap:12px;text-align:left;border:0;border-bottom:1px solid var(--line,#e5e2de);background:transparent;padding:12px 4px;color:inherit;cursor:pointer}.trace-row:hover{background:var(--surface-hover,#f8f7f5)}.trace-row-main{display:grid;gap:4px;flex:1}.trace-row-main small,.trace-row-meta small{color:var(--muted,#777);font-size:11px}.trace-row-meta{display:grid;gap:4px;text-align:right;font-size:12px}.trace-pagination{justify-content:flex-end;padding-top:8px;color:var(--muted,#777);font-size:12px}.trace-pagination span{margin-right:auto}
.trace-status-dot{width:9px;height:9px;flex:none;border-radius:50%;background:#b7a36a}.status-success{background:#5a9a6d}.status-error,.step-error{background:#c45c52}.status-cancelled{background:#98938c}.status-running{background:#c69a47}
.trace-summary{padding:10px 12px;border-radius:9px;background:var(--surface-soft,#f5f3f0);font-size:12px}.trace-summary span:nth-child(2){margin-right:auto;color:var(--muted,#777)}.trace-meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:0}.trace-meta div{min-width:0}.trace-meta dt{color:var(--muted,#777);font-size:10px}.trace-meta dd{margin:3px 0 0;overflow-wrap:anywhere;font-size:12px}
.trace-steps{list-style:none;margin:4px 0;padding:0;display:grid;gap:12px}.trace-steps li{display:flex;gap:10px}.trace-step-index{display:grid;place-items:center;width:23px;height:23px;flex:none;border:1px solid var(--line,#dedbd7);border-radius:50%;font-size:11px}.trace-step-body{min-width:0;flex:1;padding-bottom:10px;border-bottom:1px solid var(--line,#e5e2de)}.trace-step-title{flex-wrap:wrap}.trace-step-title strong{font-size:13px}.trace-step-title span,.trace-step-title time,.trace-step-body small{color:var(--muted,#777);font-size:10px}.trace-step-title time{margin-left:auto}.trace-step-body pre{max-height:200px;overflow:auto;margin:8px 0;padding:9px;border-radius:7px;background:var(--surface-soft,#f5f3f0);white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.5 ui-monospace,monospace}.trace-empty,.trace-error{padding:14px 0;color:var(--muted,#777);font-size:12px}.trace-error{color:#b7433e}
</style>
