<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import AppIcon from './AppIcon.vue'

type LinkDraft = {
  id: string
  title: string
  source_url: string
  snapshot_text: string
  body_md: string
  fetch_status: string
  fetch_error: string | null
  status: string
  notebook_id: string | null
  updated_at?: string
}
type Category = { id: string; name: string }
type LinkAnalysis = { summary: string; key_points: string[]; action_suggestions: string[] }
type AnalysisCard = { id: string; title: string; body: string }

const props = defineProps<{ draft: LinkDraft; modelConfigured: boolean; notebooks: Category[]; tags: Category[] }>()
const emit = defineEmits<{
  (event: 'close'): void
  (event: 'changed', draft: LinkDraft): void
  (event: 'updated', draft: LinkDraft): void
  (event: 'published', note: { id: string; title: string }): void
}>()

const draft = ref<LinkDraft>({ ...props.draft })
const editorMode = ref<'write' | 'preview'>('write')
const analysis = ref<LinkAnalysis | null>(null)
const analyzing = ref(false)
const publishing = ref(false)
const analysisOpen = ref(false)
const publishDialogOpen = ref(false)
const selectedNotebook = ref('')
const selectedTags = ref<string[]>([])
const collapsedCards = ref<Record<string, boolean>>({})
const bodyEditor = ref<HTMLTextAreaElement | null>(null)
const suggestionDropActive = ref(false)
const savedAt = ref(draft.value.updated_at || '')
const saveState = ref<'saved' | 'saving' | 'unsaved' | 'error'>('saved')
const error = ref('')
const notice = ref('')
let savedContent = JSON.stringify({ title: draft.value.title, body_md: draft.value.body_md })
let saveTimer: ReturnType<typeof setTimeout> | undefined
let savePromise: Promise<void> | null = null
let fetchPoll: ReturnType<typeof setInterval> | undefined
let fetchPollBusy = false
const fetching = computed(() => ['pending', 'processing'].includes(draft.value.fetch_status))

const isDirty = computed(() => JSON.stringify({ title: draft.value.title, body_md: draft.value.body_md }) !== savedContent)
const previewHtml = computed(() => DOMPurify.sanitize(marked.parse(draft.value.body_md || '', { async: false, gfm: true, breaks: true }) as string, { FORBID_TAGS: ['iframe'] }))
const cards = computed<AnalysisCard[]>(() => {
  if (!analysis.value) return []
  return [
    { id: 'summary', title: '摘要', body: analysis.value.summary },
    ...analysis.value.key_points.map((body, index) => ({ id: `point-${index}`, title: `关键要点 ${index + 1}`, body })),
    ...analysis.value.action_suggestions.map((body, index) => ({ id: `action-${index}`, title: `行动建议 ${index + 1}`, body })),
  ]
})

async function request<T>(url: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: data === undefined ? {} : { 'Content-Type': 'application/json' },
    body: data === undefined ? undefined : JSON.stringify(data),
  })
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const payload = await response.json() as { detail?: string }
      if (payload.detail) detail = payload.detail
    } catch { /* 使用状态文本。 */ }
    throw new Error(detail)
  }
  return response.status === 204 ? undefined as T : await response.json() as T
}

async function saveDraft() {
  if (savePromise) {
    await savePromise
    if (isDirty.value) return saveDraft()
    return
  }
  if (!isDirty.value) return
  if (saveTimer) clearTimeout(saveTimer)
  if (!draft.value.title.trim()) draft.value.title = '网页草稿'
  const snapshot = { title: draft.value.title.trim(), body_md: draft.value.body_md }
  const patchBody: Record<string, string> = { ...snapshot }
  if (!draft.value.snapshot_text.trim()) patchBody.pasted_text = snapshot.body_md
  saveState.value = 'saving'
  error.value = ''
  savePromise = (async () => {
    try {
      const updated = await request<LinkDraft>(`/v1/link-drafts/${draft.value.id}`, 'PATCH', patchBody)
      if (draft.value.title === snapshot.title && draft.value.body_md === snapshot.body_md) {
        draft.value = updated
        savedContent = JSON.stringify({ title: updated.title, body_md: updated.body_md })
        savedAt.value = updated.updated_at || new Date().toISOString()
        saveState.value = 'saved'
      } else {
        savedContent = JSON.stringify({ title: snapshot.title, body_md: snapshot.body_md })
        saveState.value = 'unsaved'
      }
      emit('updated', updated)
    } catch (cause) {
      saveState.value = 'error'
      error.value = cause instanceof Error ? cause.message : '保存网页草稿失败'
      throw cause
    } finally {
      savePromise = null
      if (isDirty.value) scheduleSave()
    }
  })()
  return savePromise
}

function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer)
  if (!isDirty.value) {
    saveState.value = 'saved'
    return
  }
  saveState.value = 'unsaved'
  saveTimer = setTimeout(() => { void saveDraft().catch(() => {}) }, 650)
}

async function refreshFetchStatus() {
  if (!fetching.value || fetchPollBusy) return
  fetchPollBusy = true
  try {
    const latest = await request<LinkDraft>(`/v1/link-drafts/${draft.value.id}`)
    if (latest.fetch_status !== draft.value.fetch_status || latest.snapshot_text !== draft.value.snapshot_text) {
      draft.value = latest
      savedContent = JSON.stringify({ title: latest.title, body_md: latest.body_md })
      savedAt.value = latest.updated_at || new Date().toISOString()
      saveState.value = 'saved'
      emit('changed', { ...latest })
      emit('updated', latest)
    }
    if (!['pending', 'processing'].includes(latest.fetch_status) && fetchPoll) {
      clearInterval(fetchPoll)
      fetchPoll = undefined
    }
  } catch {
    // Keep polling: a temporary API/network failure should not discard the draft.
  } finally { fetchPollBusy = false }
}

watch(() => [draft.value.title, draft.value.body_md], () => {
  emit('changed', { ...draft.value })
  scheduleSave()
})

onMounted(() => {
  if (fetching.value) {
    fetchPoll = setInterval(() => { void refreshFetchStatus() }, 1800)
    void refreshFetchStatus()
  }
})

async function analyze() {
  if (!draft.value.snapshot_text.trim() || analyzing.value || !props.modelConfigured) return
  analyzing.value = true
  error.value = ''
  notice.value = ''
  try {
    analysis.value = await request<LinkAnalysis>(`/v1/link-drafts/${draft.value.id}/analyze`, 'POST')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '建议分析失败，请稍后重试'
  } finally { analyzing.value = false }
}

function suggestionText(card: AnalysisCard) { return `## ${card.title}\n\n${card.body.trim()}` }

function insertSuggestionAt(card: AnalysisCard, start: number, end = start, preserveScroll = false) {
  const editor = bodyEditor.value
  const scrollParent = editor?.closest<HTMLElement>('.link-draft-editor')
  const editorScrollTop = editor?.scrollTop ?? 0
  const editorScrollLeft = editor?.scrollLeft ?? 0
  const parentScrollTop = scrollParent?.scrollTop ?? 0
  const parentScrollLeft = scrollParent?.scrollLeft ?? 0
  const current = draft.value.body_md
  const prefix = start > 0 && current[start - 1] !== '\n' ? '\n\n' : ''
  const suffix = end < current.length && current[end] !== '\n' ? '\n\n' : ''
  const addition = `${prefix}${suggestionText(card)}${suffix}`
  if (current.length - (end - start) + addition.length > 100_000) {
    error.value = '正文已达到长度上限，无法插入这条建议'
    return
  }
  draft.value.body_md = `${current.slice(0, start)}${addition}${current.slice(end)}`
  if (editor) void nextTick(() => {
    if (bodyEditor.value !== editor) return
    const cursor = start + addition.length
    editor.setSelectionRange(cursor, cursor)
    editor.focus({ preventScroll: true })
    if (preserveScroll) {
      editor.scrollTo(editorScrollLeft, editorScrollTop)
      scrollParent?.scrollTo(parentScrollLeft, parentScrollTop)
    }
  })
  error.value = ''
  notice.value = `已将「${card.title}」插入正文`
}

function insertSuggestion(card: AnalysisCard) {
  const editor = bodyEditor.value
  if (editorMode.value !== 'write' || !editor) {
    insertSuggestionAt(card, draft.value.body_md.length)
    return
  }
  insertSuggestionAt(card, editor.selectionStart, editor.selectionEnd)
}

function startSuggestionDrag(event: DragEvent, card: AnalysisCard) {
  if (!event.dataTransfer) return
  event.dataTransfer.setData('application/x-pkm-suggestion', card.id)
  event.dataTransfer.setData('text/plain', suggestionText(card))
  event.dataTransfer.effectAllowed = 'copy'
}

function isSuggestionDrag(event: DragEvent) {
  return Array.from(event.dataTransfer?.types || []).includes('application/x-pkm-suggestion')
}

function allowSuggestionDrop(event: DragEvent) {
  if (!isSuggestionDrag(event)) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  suggestionDropActive.value = true
}

function caretOffsetAtPoint(editor: HTMLTextAreaElement, x: number, y: number) {
  const style = getComputedStyle(editor)
  const bounds = editor.getBoundingClientRect()
  const mirror = document.createElement('div')
  const textNode = document.createTextNode(`${editor.value}\u200b`)
  Object.assign(mirror.style, {
    position: 'fixed',
    left: `${bounds.left + editor.clientLeft}px`,
    top: `${bounds.top + editor.clientTop - editor.scrollTop}px`,
    width: `${editor.clientWidth}px`,
    boxSizing: 'border-box',
    padding: style.padding,
    font: style.font,
    lineHeight: style.lineHeight,
    letterSpacing: style.letterSpacing,
    textAlign: style.textAlign,
    textIndent: style.textIndent,
    tabSize: style.tabSize,
    whiteSpace: 'pre-wrap',
    overflowWrap: 'break-word',
    wordBreak: style.wordBreak,
    visibility: 'hidden',
    pointerEvents: 'none',
  })
  mirror.append(textNode)
  document.body.append(mirror)
  const range = document.createRange()
  const length = editor.value.length
  const lineHeight = Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.95
  const rectAt = (offset: number) => {
    range.setStart(textNode, offset)
    range.setEnd(textNode, offset)
    return range.getBoundingClientRect()
  }
  try {
    let low = 0
    let high = length
    while (low < high) {
      const middle = Math.floor((low + high) / 2)
      if (rectAt(middle).top + lineHeight / 2 < y) low = middle + 1
      else high = middle
    }
    const later = low
    const earlier = Math.max(0, later - 1)
    const laterTop = rectAt(later).top
    const earlierTop = rectAt(earlier).top
    const lineTop = Math.abs(laterTop + lineHeight / 2 - y) < Math.abs(earlierTop + lineHeight / 2 - y) ? laterTop : earlierTop
    low = 0
    high = length
    while (low < high) {
      const middle = Math.floor((low + high) / 2)
      if (rectAt(middle).top < lineTop - 0.5) low = middle + 1
      else high = middle
    }
    const lineStart = low
    low = lineStart
    high = length
    while (low < high) {
      const middle = Math.ceil((low + high) / 2)
      if (rectAt(middle).top > lineTop + 0.5) high = middle - 1
      else low = middle
    }
    const lineEnd = low
    low = lineStart
    high = lineEnd
    while (low < high) {
      const middle = Math.floor((low + high) / 2)
      if (rectAt(middle).left < x) low = middle + 1
      else high = middle
    }
    return low > lineStart && Math.abs(rectAt(low - 1).left - x) < Math.abs(rectAt(low).left - x) ? low - 1 : low
  } finally {
    range.detach()
    mirror.remove()
  }
}

function dropSuggestion(event: DragEvent) {
  suggestionDropActive.value = false
  const cardId = event.dataTransfer?.getData('application/x-pkm-suggestion')
  const card = cards.value.find(item => item.id === cardId)
  const editor = bodyEditor.value
  if (!card || !editor) return
  event.preventDefault()
  insertSuggestionAt(card, caretOffsetAtPoint(editor, event.clientX, event.clientY), undefined, true)
}

function toggleTag(id: string) {
  selectedTags.value = selectedTags.value.includes(id)
    ? selectedTags.value.filter(item => item !== id)
    : [...selectedTags.value, id]
}

async function publish() {
  publishing.value = true
  error.value = ''
  try {
    if (isDirty.value) await saveDraft()
    const note = await request<{ id: string; title: string }>(`/v1/link-drafts/${draft.value.id}/publish`, 'POST', {
      notebook_id: selectedNotebook.value || null,
      tag_ids: selectedTags.value,
    })
    emit('published', note)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '发布失败，请稍后重试'
  } finally { publishing.value = false }
}

onUnmounted(() => {
  if (saveTimer) clearTimeout(saveTimer)
  if (fetchPoll) clearInterval(fetchPoll)
})
</script>

<template>
  <section class="link-workspace" :class="{ 'analysis-open': analysisOpen }" aria-label="网页草稿工作区">
    <header class="link-workspace-head">
      <div class="link-workspace-titlebar">
        <button class="icon-button" type="button" aria-label="返回" title="返回" @click="emit('close')"><AppIcon name="arrow-left" /></button>
        <div class="link-workspace-heading"><span>网页草稿</span><strong>{{ draft.title || '无标题网页' }}</strong></div>
        <span class="link-workspace-save" :class="`state-${saveState}`" aria-live="polite">{{ saveState === 'saving' ? '保存中' : saveState === 'error' ? '保存失败' : saveState === 'unsaved' ? '待保存' : '已保存' }}<time v-if="savedAt && saveState === 'saved'"> · {{ new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(savedAt)) }}</time></span>
      </div>
      <div class="link-workspace-actions">
        <button type="button" class="editor-action-button analysis-toggle" :aria-expanded="analysisOpen" @click="analysisOpen = !analysisOpen"><AppIcon name="spark" /><span>建议分析</span></button>
        <button type="button" class="editor-action-button save-draft-button" :disabled="saveState === 'saving'" @click="void saveDraft().catch(() => {})"><AppIcon name="save" /><span>保存草稿</span></button>
        <button type="button" class="accent-button publish-note-button" :disabled="publishing || saveState === 'saving' || fetching" @click="publishDialogOpen = true"><AppIcon name="book" /><span>{{ fetching ? '正在获取网页…' : '加入笔记' }}</span></button>
      </div>
    </header>

    <div class="link-workspace-grid">
      <main class="link-draft-editor">
        <div class="link-source-row">
          <span class="link-fetch-state" :class="draft.fetch_status === 'ready' ? 'ready' : fetching ? 'pending' : 'failed'">{{ draft.fetch_status === 'ready' ? '网页正文已抓取' : draft.fetch_status === 'processing' ? 'Agent 正在获取网页' : draft.fetch_status === 'pending' ? '等待 Agent 获取网页' : '未能抓取网页正文' }}</span>
          <a :href="draft.source_url" target="_blank" rel="noopener noreferrer">{{ draft.source_url }} <AppIcon name="arrow" /></a>
        </div>
        <p v-if="draft.fetch_error" class="link-fetch-error">{{ draft.fetch_error }}。可在下方粘贴或补充正文。</p>
        <input v-model="draft.title" :disabled="fetching" class="link-draft-title-input" maxlength="240" placeholder="网页标题" aria-label="网页草稿标题" />
        <div class="link-draft-toolbar">
          <span>正文</span>
          <div role="group" aria-label="正文模式">
            <button type="button" :class="{ active: editorMode === 'write' }" @click="editorMode = 'write'">编辑</button>
            <button type="button" :class="{ active: editorMode === 'preview' }" @click="editorMode = 'preview'">预览</button>
          </div>
        </div>
        <p v-if="fetching" class="link-fetch-loading" role="status">{{ draft.fetch_status === 'processing' ? 'Agent 正在安全校验链接并提取网页正文…' : '已提交到后台 Agent 队列，正在等待抓取…' }}</p>
        <textarea v-if="editorMode === 'write'" ref="bodyEditor" v-model="draft.body_md" :disabled="fetching" class="link-draft-body-input" :class="{ 'suggestion-drop-active': suggestionDropActive }" maxlength="100000" :placeholder="fetching ? 'Agent 正在获取网页正文…' : '网页正文抓取失败时，可在此粘贴或补充内容。'" aria-label="网页草稿正文" @dragover="allowSuggestionDrop" @dragleave="suggestionDropActive = false" @drop="dropSuggestion" />
        <article v-else class="link-draft-body-preview markdown-preview" v-html="previewHtml" />
        <p v-if="error" class="link-workspace-error" role="alert">{{ error }}</p>
        <p v-else-if="notice" class="link-workspace-notice" role="status">{{ notice }}</p>
      </main>

      <aside v-if="analysisOpen" class="link-analysis-panel" aria-label="建议分析助手">
        <header><span class="link-analysis-icon"><AppIcon name="spark" /></span><div><strong>建议分析助手</strong><small>基于网页原文生成建议</small></div><button type="button" class="link-analysis-close" aria-label="关闭建议分析助手" @click="analysisOpen = false"><AppIcon name="close" /></button></header>
        <p v-if="!modelConfigured" class="link-analysis-empty">请先在设置中连接模型，再生成建议。草稿仍可正常编辑和发布。</p>
        <p v-else-if="!draft.snapshot_text.trim()" class="link-analysis-empty">暂时没有可分析的网页正文。粘贴或补充正文并保存后即可分析。</p>
        <div v-else-if="!analysis" class="link-analysis-intro"><p>生成摘要、关键要点和行动建议。你可以逐项选择加入正文。</p><button type="button" class="accent-button" :disabled="analyzing" @click="void analyze()"><AppIcon name="spark" />{{ analyzing ? '正在分析…' : '生成分析' }}</button></div>
        <div v-else class="link-analysis-results">
          <div v-for="card in cards" :key="card.id" class="link-analysis-card" draggable="true" @dragstart="startSuggestionDrag($event, card)">
            <div class="link-analysis-card-heading"><button type="button" class="link-analysis-collapse" :aria-expanded="!collapsedCards[card.id]" @click="collapsedCards[card.id] = !collapsedCards[card.id]"><AppIcon name="chevron" :class="{ collapsed: collapsedCards[card.id] }" /><small>{{ card.title }}</small></button><button type="button" class="link-analysis-insert" :aria-label="`插入${card.title}`" :title="`插入${card.title}`" @click="insertSuggestion(card)"><AppIcon name="plus" /></button></div>
            <p v-if="!collapsedCards[card.id]">{{ card.body }}</p>
          </div>
          <button type="button" class="link-analysis-regenerate" :disabled="analyzing" @click="void analyze()">{{ analyzing ? '正在分析…' : '重新生成' }}</button>
        </div>
      </aside>
    </div>

    <div v-if="publishDialogOpen" class="link-publish-backdrop" @click.self="publishDialogOpen = false">
      <section class="link-publish-dialog" role="dialog" aria-modal="true" aria-labelledby="link-publish-title">
        <button type="button" class="link-publish-close" aria-label="关闭" @click="publishDialogOpen = false"><AppIcon name="close" /></button>
        <h2 id="link-publish-title">加入笔记</h2>
        <p>选择笔记本和标签；不选择时将保持未分类、无标签。</p>
        <label class="link-publish-field">笔记本<select v-model="selectedNotebook"><option value="">不选择笔记本</option><option v-for="item in notebooks" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
        <fieldset class="link-publish-tags"><legend>标签</legend><label v-for="item in tags" :key="item.id"><input type="checkbox" :checked="selectedTags.includes(item.id)" @change="toggleTag(item.id)" />{{ item.name }}</label><small v-if="!tags.length">暂无标签</small></fieldset>
        <div class="link-publish-actions"><button type="button" class="editor-action-button" @click="publishDialogOpen = false">取消</button><button type="button" class="accent-button" :disabled="publishing || fetching" @click="void publish()">{{ publishing ? '加入中…' : '确认加入' }}</button></div>
        <p v-if="error" class="link-workspace-error" role="alert">{{ error }}</p>
      </section>
    </div>
  </section>
</template>
