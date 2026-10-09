<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { marked, Renderer } from 'marked'
import DOMPurify from 'dompurify'
import AppIcon from './AppIcon.vue'
import AssistantTraceExplorer from './AssistantTraceExplorer.vue'

type SearchHit = { note_id: string; title: string; notebook_id: string | null; version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number; snippet: string; updated_at: string; match_source: 'keyword' | 'semantic' | 'both'; score: number }
type UserMessage = { id: string; role: 'user'; content: { text: string }; created_at: string }
type Citation = { note_id: string; citation_id: string; title: string }
type PendingOperation =
  | { operation_id: string; kind: 'selection'; candidates: { index: number; title: string; notebook?: string | null }[] }
  | { operation_id: string; kind: 'confirmation'; changes: { title: string; before: { title: string; body_md: string }; after: { title?: string; body_md?: string } }[] }
  | { operation_id: string; kind: 'input'; action: 'create' | 'update'; missing: ('target_title' | 'body_md' | 'title')[] }
type AssistantContent = { answer: string; citations: Citation[]; semantic_status: 'ready' | 'unavailable' | 'not_requested'; answer_source?: 'knowledge_base' | 'mixed' | 'model_knowledge' | 'unknown'; retrieval_status?: 'not_requested' | 'no_results' | 'retrieved' | 'error' | 'unknown'; pending_operation?: PendingOperation | null; operation_receipts?: { action: string; title: string }[] } | { items: SearchHit[]; semantic_status: 'ready' | 'unavailable' }
type AssistantMessage = { id: string; role: 'assistant'; content: AssistantContent; created_at: string }
type ChatMessage = UserMessage | AssistantMessage
type SentMessages = { id: string; title: string; created_at: string; updated_at: string; messages: [UserMessage, AssistantMessage] }

const props = defineProps<{ conversationId: string; messages: ChatMessage[]; loading: boolean; modelName: string | null; modelConfigured: boolean; traceViewEnabled?: boolean }>()
const emit = defineEmits<{
  (e: 'answered', conversationId: string, result: SentMessages, replaceFromMessageId: string | null): void
  (e: 'conversationChanged', conversationId: string, result: { id: string; title: string; created_at: string; updated_at: string; messages: ChatMessage[] }): void
  (e: 'openNote', noteId: string): void
  (e: 'configureModel'): void
  (e: 'modelChanged', modelName: string): void
}>()
const question = ref('')
const busy = ref(false)
const error = ref('')
const history = ref<HTMLDivElement | null>(null)
const optimisticQuestion = ref('')
const streamedAnswer = ref('')
const streamStatus = ref('')
const replacingFromId = ref<string | null>(null)
const editingMessageId = ref('')
const editedQuestion = ref('')
const pendingDeleteId = ref('')
const copiedMessageId = ref('')
const composerInput = ref<HTMLTextAreaElement | null>(null)
const modelChoice = ref('deepseek-flash')
const changingModel = ref(false)
const optimisticCreatedAt = ref('')
const openTraceMessageId = ref('')
let activeRequest: AbortController | null = null

function toggleTrace(messageId: string) {
  openTraceMessageId.value = openTraceMessageId.value === messageId ? '' : messageId
}

watch(() => props.modelName, value => { modelChoice.value = value || 'deepseek-flash' }, { immediate: true })

function messageTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const clock = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  return date.toDateString() === new Date().toDateString() ? clock : `${date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${clock}`
}

async function changeModel(event: Event) {
  const chosen = (event.target as HTMLSelectElement).value
  if (chosen === props.modelName || changingModel.value) return
  changingModel.value = true
  error.value = ''
  try {
    const response = await fetch('/v1/model-connection', {
      method: 'PATCH', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_name: chosen }),
    })
    if (!response.ok) {
      const payload = await response.json() as { detail?: string }
      throw new Error(payload.detail || `模型切换失败（${response.status}）`)
    }
    const connection = await response.json() as { model_name: string }
    modelChoice.value = connection.model_name
    emit('modelChanged', connection.model_name)
  } catch (cause) {
    modelChoice.value = props.modelName || 'deepseek-flash'
    error.value = cause instanceof Error ? cause.message : '模型切换失败'
  } finally { changingModel.value = false }
}

const isEmpty = computed(() => !props.loading && !visibleMessages.value.length && !optimisticQuestion.value)

function useSuggestion(prompt: string) {
  question.value = prompt
  void nextTick(() => composerInput.value?.focus())
}

const visibleMessages = computed(() => {
  if (!replacingFromId.value) return props.messages
  const index = props.messages.findIndex(message => message.id === replacingFromId.value)
  return index < 0 ? props.messages : props.messages.slice(0, index)
})

function cleanAnswer(text: string) {
  return text.replace(/\s*\[S\d+\]/g, '').replace(/\s*\[S?\d*$/g, '')
}

function escapeAnswerHtml(text: string) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

const answerRenderer = new Renderer()
// Preserve supplied HTML as text before it reaches a browser DOM parser.
answerRenderer.html = ({ text }) => escapeAnswerHtml(text)
answerRenderer.image = ({ text }) => escapeAnswerHtml(text || '图片')

function renderAnswer(text: string) {
  return DOMPurify.sanitize(marked.parse(cleanAnswer(text), { renderer: answerRenderer, async: false, gfm: true, breaks: true }) as string, { FORBID_TAGS: ['img', 'iframe', 'style', 'svg', 'math', 'object', 'embed'], FORBID_ATTR: ['style'] })
}

function sourcesFor(content: AssistantContent) {
  const sources = 'citations' in content ? content.citations : content.items
  return [...new Map(sources.map(item => [item.note_id, { note_id: item.note_id, title: item.title }])).values()]
}

type StreamEvent = { type: 'status'; text: string } | { type: 'delta'; text: string } | { type: 'complete'; result: SentMessages } | { type: 'error'; detail: string }
let retryRequest: { signature: string; id: string } | null = null

async function readAnswerStream(response: Response, conversationId: string, replaceFromMessageId: string | null): Promise<void> {
  if (!response.body) throw new Error('浏览器未能读取回答流')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false

  const handleFrame = (frame: string) => {
    const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
    if (!data) return
    const event = JSON.parse(data) as StreamEvent
    if (event.type === 'status') streamStatus.value = event.text
    else if (event.type === 'delta') {
      streamedAnswer.value += event.text
      streamStatus.value = ''
    } else if (event.type === 'error') throw new Error(event.detail || '回答生成失败，请重试')
    else if (event.type === 'complete') {
      emit('answered', conversationId, event.result, replaceFromMessageId)
      completed = true
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    buffer = buffer.replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      handleFrame(frame)
      boundary = buffer.indexOf('\n\n')
    }
    if (done) break
  }
  if (!completed) throw new Error('回答流意外结束，请重试')
}

async function ask(overrideQuestion?: string, replaceFromMessageId: string | null = null, confirmationId?: string, selection?: number) {
  const asked = (overrideQuestion ?? question.value).trim()
  if (!asked || busy.value || !props.conversationId) return
  const conversationId = props.conversationId
  if (asked.length > 10000) { error.value = '消息最多 10000 字，请分段处理'; return }
  const signature = JSON.stringify([conversationId, asked, replaceFromMessageId, confirmationId, selection])
  if (!retryRequest || retryRequest.signature !== signature) retryRequest = { signature, id: crypto.randomUUID() }
  busy.value = true
  error.value = ''
  optimisticQuestion.value = asked
  optimisticCreatedAt.value = new Date().toISOString()
  replacingFromId.value = replaceFromMessageId
  streamedAnswer.value = ''
  streamStatus.value = ''
  question.value = ''
  const controller = new AbortController()
  activeRequest = controller
  try {
    const response = await fetch(`/v1/assistant/conversations/${conversationId}/messages/stream`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: asked, replace_from_message_id: replaceFromMessageId, request_id: retryRequest.id, confirmation_id: confirmationId, selection }),
      signal: controller.signal,
    })
    if (!response.ok) {
      let detail = `请求失败（${response.status}）`
      try { const payload = await response.json() as { detail?: string }; if (payload.detail) detail = payload.detail } catch { /* 保留状态信息。 */ }
      throw new Error(detail)
    }
    await readAnswerStream(response, conversationId, replaceFromMessageId)
    retryRequest = null
    optimisticQuestion.value = ''
    streamedAnswer.value = ''
    streamStatus.value = ''
    replacingFromId.value = null
  } catch (cause) {
    if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
      error.value = cause instanceof Error ? cause.message : '发送失败，请重试'
      if (replaceFromMessageId) {
        editingMessageId.value = replaceFromMessageId
        editedQuestion.value = asked
      } else question.value = asked
    }
    optimisticQuestion.value = ''
    streamedAnswer.value = ''
    streamStatus.value = ''
    replacingFromId.value = null
  } finally {
    busy.value = false
    if (activeRequest === controller) activeRequest = null
  }
}

onUnmounted(() => activeRequest?.abort())

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  void ask()
}

async function copyMessage(message: ChatMessage) {
  const content = message.role === 'user' ? message.content.text : 'answer' in message.content
    ? cleanAnswer(message.content.answer)
    : sourcesFor(message.content).map(source => source.title).join('\n')
  try {
    await navigator.clipboard.writeText(content)
    copiedMessageId.value = message.id
    window.setTimeout(() => { if (copiedMessageId.value === message.id) copiedMessageId.value = '' }, 1800)
  } catch { error.value = '复制失败，请检查浏览器剪贴板权限' }
}

function startEditing(message: UserMessage) {
  editingMessageId.value = message.id
  editedQuestion.value = message.content.text
  pendingDeleteId.value = ''
  void nextTick(() => document.querySelector<HTMLTextAreaElement>('.chat-edit-textarea')?.focus())
}

function submitEdit() {
  const text = editedQuestion.value.trim()
  if (!text || !editingMessageId.value) return
  const messageId = editingMessageId.value
  editingMessageId.value = ''
  void ask(text, messageId)
}

function handleEditKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { editingMessageId.value = ''; return }
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  submitEdit()
}

function regenerate(message: AssistantMessage) {
  const index = props.messages.findIndex(item => item.id === message.id)
  const user = props.messages.slice(0, index).reverse().find(item => item.role === 'user') as UserMessage | undefined
  if (!user) return
  editingMessageId.value = ''
  void ask(user.content.text, user.id)
}

async function deleteMessage(message: ChatMessage) {
  if (busy.value) return
  if (pendingDeleteId.value !== message.id) {
    pendingDeleteId.value = message.id
    return
  }
  pendingDeleteId.value = ''
  busy.value = true
  error.value = ''
  try {
    const response = await fetch(`/v1/assistant/conversations/${props.conversationId}/messages/${message.id}`, {
      method: 'DELETE', credentials: 'same-origin',
    })
    if (!response.ok) {
      const payload = await response.json() as { detail?: string }
      throw new Error(payload.detail || `删除失败（${response.status}）`)
    }
    emit('conversationChanged', props.conversationId, await response.json())
    editingMessageId.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '删除失败，请重试' }
  finally { busy.value = false }
}

watch(() => [props.messages.length, props.loading, busy.value, streamedAnswer.value, streamStatus.value], async () => {
  await nextTick()
  if (history.value) history.value.scrollTop = history.value.scrollHeight
}, { immediate: true, flush: 'post' })
</script>

<template>
  <div class="chat-shell" :class="{ 'is-empty': isEmpty }">
    <div ref="history" class="chat-history">
      <div v-if="loading" class="chat-loading"><span class="chat-wait-dots" aria-label="正在加载对话"><i></i><i></i><i></i></span></div>
      <div v-else-if="isEmpty" class="chat-empty"><span class="chat-empty-mark">✦</span><p class="chat-empty-eyebrow">你的个人知识库</p><h2>今天想从笔记中了解什么？</h2><p class="chat-empty-description">查找、整理或总结你写过的内容</p><div class="chat-starters"><button type="button" @click="useSuggestion('帮我总结最近的工作记录')">总结最近的工作记录 <span>↗</span></button><button type="button" @click="useSuggestion('整理笔记中某个主题的主要观点')">整理一个主题的观点 <span>↗</span></button><button type="button" @click="useSuggestion('查找笔记中提到的待办事项')">查找笔记中的待办 <span>↗</span></button></div></div>
      <div v-else class="chat-turns">
        <div v-for="message in visibleMessages" :key="message.id" class="chat-message" :class="`message-${message.role}`">
          <template v-if="message.role === 'user'">
            <form v-if="editingMessageId === message.id" class="chat-question chat-question-edit" @submit.prevent="submitEdit">
              <textarea v-model="editedQuestion" class="chat-edit-textarea" rows="1" aria-label="编辑问题" @keydown="handleEditKeydown" />
              <div class="chat-edit-actions"><button type="button" aria-label="取消编辑" title="取消" @click="editingMessageId = ''"><AppIcon name="close" /></button><button type="submit" :disabled="!editedQuestion.trim() || busy" aria-label="保存并重新提问" title="保存并重新提问"><AppIcon name="check" /></button></div>
            </form>
            <div v-else class="chat-question">{{ message.content.text }}</div>
          </template>
          <div v-else class="chat-answer">
            <span class="chat-answer-icon">✦</span>
            <div v-if="'answer' in message.content" class="chat-answer-content">
              <small v-if="message.content.semantic_status === 'unavailable'" class="chat-status">语义检索暂不可用，本轮已尝试关键词检索</small>
              <small v-if="message.content.operation_receipts?.length" class="chat-status">本轮操作已保存</small>
              <small v-else-if="message.content.pending_operation?.kind === 'input'" class="chat-status">等待补充内容，尚未保存</small>
              <small v-else-if="message.content.pending_operation" class="chat-status">待确认目标或差异，尚未保存</small>
              <small v-else-if="message.content.retrieval_status === 'no_results'" class="chat-status">本轮检索未找到合适依据</small>
              <small v-else-if="message.content.retrieval_status === 'error'" class="chat-status">本轮检索失败，请稍后重试</small>
              <small v-else-if="message.content.answer_source === 'mixed'" class="chat-status">回答结合了笔记证据与通用知识补充</small>
              <small v-else-if="message.content.retrieval_status === 'retrieved' && message.content.answer_source === 'unknown'" class="chat-status">当前资料不足以核实这份回答</small>
              <small v-else-if="message.content.retrieval_status === 'retrieved' && message.content.answer_source === 'model_knowledge'" class="chat-status">本轮已查看相关笔记，回答采用通用知识</small>
              <small v-else-if="message.content.retrieval_status === 'not_requested'" class="chat-status">本轮未检索笔记</small>
              <div class="chat-answer-text" v-html="renderAnswer(message.content.answer)"></div>
              <div v-if="message.content.pending_operation && message.id === visibleMessages.at(-1)?.id" class="chat-operation">
                <template v-if="message.content.pending_operation.kind === 'selection'">
                  <button v-for="candidate in message.content.pending_operation.candidates" :key="candidate.index" type="button" :disabled="busy" @click="ask(`选择${candidate.index}`, null, message.content.pending_operation!.operation_id, candidate.index)">{{ candidate.index }}. {{ candidate.title }} · {{ candidate.notebook || '默认位置' }}</button>
                </template>
                <template v-else-if="message.content.pending_operation.kind === 'confirmation'">
                  <div v-for="change in message.content.pending_operation.changes" :key="change.title">
                    <strong>{{ change.title }}</strong><p>修改前</p><pre>{{ change.after.title !== undefined ? change.before.title : change.before.body_md }}</pre><p>修改后</p><pre>{{ change.after.title !== undefined ? change.after.title : change.after.body_md }}</pre>
                  </div>
                  <button type="button" :disabled="busy" @click="ask('确认保存上述差异', null, message.content.pending_operation!.operation_id)">确认保存这些差异</button>
                  <button type="button" :disabled="busy" @click="ask('取消此前操作，不做任何改动')">取消</button>
                </template>
                <template v-else>
                  <p>{{ message.content.pending_operation.missing.includes('target_title') ? '在下方回复笔记标题即可继续。' : '在下方补充要保存的正文即可继续。' }}</p>
                  <button type="button" :disabled="busy" @click="ask('取消此前操作，不做任何改动')">取消</button>
                </template>
              </div>
              <div v-if="sourcesFor(message.content).length" class="chat-citations"><span class="chat-sources-label">来源笔记</span>
                <button v-for="item in sourcesFor(message.content)" :key="`${message.id}-${item.note_id}`" class="chat-citation" @click="emit('openNote', item.note_id)"><strong>{{ item.title }}</strong><span>打开笔记 ↗</span></button>
              </div>
            </div>
            <div v-else class="chat-answer-content">
              <small v-if="message.content.semantic_status === 'unavailable'" class="chat-status">语义检索暂不可用，以下仅显示关键词检索结果</small>
              <p v-if="message.content.items.length" class="chat-no-results">已找到相关笔记，可打开来源查看原文。</p>
              <p v-else class="chat-no-results">没有找到相关笔记。</p>
              <div v-if="sourcesFor(message.content).length" class="chat-citations"><span class="chat-sources-label">来源笔记</span>
                <button v-for="item in sourcesFor(message.content)" :key="`${message.id}-${item.note_id}`" class="chat-citation" @click="emit('openNote', item.note_id)"><strong>{{ item.title }}</strong><span>打开笔记 ↗</span></button>
              </div>
            </div>
          </div>
          <div class="chat-message-actions" :class="{ 'chat-actions-user': message.role === 'user' }">
            <time class="chat-message-time" :datetime="message.created_at" :title="new Date(message.created_at).toLocaleString('zh-CN')">{{ messageTime(message.created_at) }}</time>
            <button type="button" :disabled="busy" :aria-label="copiedMessageId === message.id ? '已复制' : '复制消息'" :title="copiedMessageId === message.id ? '已复制' : '复制'" @click="copyMessage(message)"><AppIcon :name="copiedMessageId === message.id ? 'check' : 'copy'" /></button>
            <button v-if="message.role === 'user'" type="button" :disabled="busy" aria-label="编辑问题" title="编辑" @click="startEditing(message)"><AppIcon name="edit" /></button>
            <button v-if="message.role === 'assistant'" type="button" :disabled="busy" aria-label="重新提问" title="重新提问" @click="regenerate(message)"><AppIcon name="refresh" /></button>
            <button v-if="message.role === 'assistant' && traceViewEnabled" type="button" :disabled="busy" aria-label="查看 Agent 执行过程" :aria-expanded="openTraceMessageId === message.id" title="查看执行过程" @click="toggleTrace(message.id)"><AppIcon name="clock" /></button>
            <button type="button" :disabled="busy" class="chat-delete-action" :aria-label="pendingDeleteId === message.id ? '确认删除此条及后续消息' : '删除消息'" :title="pendingDeleteId === message.id ? '确认删除此条及后续消息' : '删除'" @click="deleteMessage(message)"><AppIcon v-if="pendingDeleteId !== message.id" name="trash" /><span v-else>确认删除此条及后续</span></button>
          </div>
          <AssistantTraceExplorer v-if="message.role === 'assistant' && traceViewEnabled && openTraceMessageId === message.id" mode="message" :message-id="message.id" />
        </div>
        <div v-if="optimisticQuestion" class="chat-message chat-streaming-turn">
          <div class="chat-question">{{ optimisticQuestion }}</div>
          <div class="chat-message-actions chat-actions-user"><time class="chat-message-time" :datetime="optimisticCreatedAt">{{ messageTime(optimisticCreatedAt) }}</time></div>
          <div class="chat-answer">
            <span class="chat-answer-icon">✦</span>
            <div class="chat-answer-content">
              <div v-if="streamedAnswer" class="chat-answer-text" v-html="renderAnswer(streamedAnswer)"></div><span v-if="streamedAnswer" class="chat-stream-cursor" aria-hidden="true"></span>
              <span v-else class="chat-wait-dots" role="status" aria-label="正在生成回答"><i></i><i></i><i></i></span>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="chat-bottom">
      <p v-if="error" class="chat-error" role="alert">{{ error }}</p>
      <p v-if="!modelConfigured" class="chat-config-notice">AI 对话需要已连接的聊天模型。请先配置模型连接。</p>
      <form class="chat-composer" @submit.prevent="ask()">
        <textarea ref="composerInput" v-model="question" rows="2" aria-label="输入消息" placeholder="给笔记助手发送消息…" @keydown="handleComposerKeydown" />
        <div class="chat-composer-foot"><span class="chat-key-hint">Enter 发送 · Shift + Enter 换行</span><label v-if="modelConfigured" class="chat-model-picker"><span class="chat-model-dot"></span><select v-model="modelChoice" :disabled="busy || loading || changingModel" aria-label="选择聊天模型" @change="changeModel"><option value="deepseek-flash">DeepSeek Flash</option><option value="deepseek-v4-pro">DeepSeek V4 Pro</option></select><AppIcon name="chevron" /></label><button v-else class="chat-model-config-link" type="button" @click="emit('configureModel')">配置模型</button><button type="submit" class="send-button" :disabled="busy || loading || changingModel || !conversationId || !question.trim() || !modelConfigured" aria-label="发送消息">↑</button></div>
      </form>
      <p class="chat-footnote">重要内容请结合来源核对</p>
    </div>
  </div>
</template>

<style scoped>
.chat-shell{display:flex;flex-direction:column;height:calc(100vh - 116px);min-height:480px}
.chat-history{flex:1;min-height:0;overflow-y:auto;padding:25px clamp(24px,5vw,72px)}
.chat-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--accent)}
.chat-empty>span{font-size:34px}.chat-empty h2{margin:16px 0 0;color:var(--ink);font:400 25px 'Songti SC','Noto Serif CJK SC',serif}.chat-empty p{margin:10px 0;color:var(--muted);font-size:12px}
.chat-turns{width:min(800px,100%);margin:0 auto}.chat-message{margin-bottom:25px}.chat-question{width:fit-content;max-width:84%;margin-left:auto;padding:11px 16px;border-radius:14px 14px 3px 14px;background:var(--hero);font-size:13px;line-height:1.7;white-space:pre-wrap}.chat-answer{display:flex;gap:14px;margin-top:10px;font-size:13px;line-height:1.75}.chat-answer-icon{padding-top:2px;color:var(--accent)}.chat-answer-content{flex:1;min-width:0}.chat-status{display:block;margin:0 0 10px;color:var(--muted)}.chat-results{display:grid;gap:9px}.chat-result{display:block;width:100%;padding:13px 15px;border:1px solid var(--line);border-radius:11px;background:var(--card);color:var(--ink);text-align:left;cursor:pointer}.chat-result:hover{border-color:#c8a895;background:#fffdfa}.chat-result-heading,.chat-result-meta{display:flex;align-items:center;gap:10px}.chat-result-heading{justify-content:space-between}.chat-result-heading strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}.chat-result-index{display:grid;place-items:center;flex:none;width:21px;height:21px;border-radius:50%;background:var(--hero);color:var(--accent);font-size:10px}.chat-result-snippet{display:-webkit-box;margin:9px 0 10px;overflow:hidden;color:var(--muted);font-size:12px;line-height:1.7;-webkit-box-orient:vertical;-webkit-line-clamp:4}.chat-result-meta{flex-wrap:wrap;color:#9b887d;font-size:10px}.chat-result-meta span:last-child{margin-left:auto;color:var(--accent)}.chat-no-results{margin:0;color:var(--muted)}.chat-bottom{width:min(848px,100%);margin:0 auto;padding:15px 24px 27px}.chat-composer{padding:12px 15px 10px;border:1px solid var(--line);border-radius:15px;background:#fff;box-shadow:0 8px 28px #6a3d3010}.chat-composer textarea{display:block;width:100%;min-height:55px;resize:vertical;border:0;outline:0;color:var(--ink);background:transparent;font-size:14px;line-height:1.6}.chat-composer-foot{display:flex;justify-content:space-between;align-items:center;min-height:32px;color:var(--muted);font-size:11px}.send-button{width:32px;height:32px;border:0;border-radius:9px;background:var(--accent);color:#fff;font-size:20px}.send-button:disabled{opacity:.45;cursor:not-allowed}.chat-error{margin:0 0 10px;color:#a34535;font-size:12px}
.chat-stream-status{margin:0;color:var(--muted);font-size:12px}.chat-stream-cursor{display:inline-block;width:7px;height:1em;margin-left:2px;vertical-align:-2px;background:var(--accent);animation:chat-blink 1s steps(2,start) infinite}@keyframes chat-blink{to{visibility:hidden}}
.chat-answer-text{margin:0 0 12px;overflow-wrap:anywhere}.chat-answer-text :deep(p){margin:0 0 10px}.chat-answer-text :deep(ul),.chat-answer-text :deep(ol){margin:0 0 12px;padding-left:22px}.chat-answer-text :deep(li){margin:3px 0}.chat-answer-text :deep(h1),.chat-answer-text :deep(h2),.chat-answer-text :deep(h3){margin:16px 0 8px;line-height:1.4}.chat-answer-text :deep(h1){font-size:20px}.chat-answer-text :deep(h2){font-size:17px}.chat-answer-text :deep(h3){font-size:15px}.chat-answer-text :deep(code){padding:1px 4px;border-radius:4px;background:var(--hero);font-size:.9em}.chat-answer-text :deep(pre){overflow:auto;padding:10px;border-radius:8px;background:var(--hero)}.chat-answer-text :deep(pre code){padding:0}.chat-answer-text :deep(blockquote){margin:10px 0;padding:2px 12px;border-left:3px solid var(--accent);color:var(--muted)}.chat-answer-text :deep(table){display:block;max-width:100%;overflow:auto;border-collapse:collapse}.chat-answer-text :deep(th),.chat-answer-text :deep(td){padding:5px 9px;border:1px solid var(--line)}.chat-citations{display:grid;gap:7px;margin-top:12px}.chat-sources-label{color:var(--muted);font-size:11px}.chat-citation{display:flex;justify-content:space-between;align-items:center;gap:12px;width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--ink);text-align:left;cursor:pointer}.chat-citation:hover{border-color:#c8a895;background:#fffdfa}.chat-citation strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}.chat-citation span{flex:none;color:var(--accent);font-size:11px}.chat-message-actions{display:flex;gap:12px;margin:6px 0 0 29px}.chat-actions-user{justify-content:flex-end;margin-right:2px}.chat-message-actions button,.chat-edit-actions button{padding:2px 0;border:0;background:transparent;color:var(--muted);font-size:11px;cursor:pointer}.chat-message-actions button:hover,.chat-edit-actions button:hover{color:var(--accent)}.chat-message-actions button:disabled{opacity:.5;cursor:default}.chat-message-actions .chat-delete-action{color:#a45c4d}.chat-edit{width:min(480px,100%);margin-left:auto;padding:10px;border:1px solid var(--line);border-radius:12px;background:#fff}.chat-edit-textarea{display:block;width:100%;resize:vertical;border:0;outline:0;color:var(--ink);font:inherit;line-height:1.6}.chat-edit-actions{display:flex;justify-content:flex-end;gap:16px;margin-top:8px}.chat-edit-actions button[type=submit]{color:var(--accent)}.chat-config-notice{margin:0 0 9px;color:var(--muted);font-size:12px}.chat-config-button{margin:8px 0 0;padding:5px 0;border:0;background:transparent;color:var(--accent);font-size:12px;cursor:pointer}.chat-model-label{overflow:hidden;color:#907e73;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:780px){.chat-shell{height:calc(100vh - 113px)}.chat-history{padding:20px}.chat-bottom{padding:12px 17px 19px}}

/* 参考 DeepSeek 布局，打造更安静、以阅读为主的对话界面。 */
.chat-shell{height:calc(100dvh - 76px);min-height:0;background:#fcfaf7}
.chat-history{padding:34px clamp(22px,4vw,54px) 20px;scroll-behavior:auto}
.chat-turns{width:min(760px,100%);padding-bottom:30px}
.chat-message{margin-bottom:30px}
.chat-question{max-width:min(82%,580px);padding:12px 17px;border:1px solid #e9e2dc;border-radius:18px 18px 5px 18px;background:#f3efeb;color:#382f2b;font-size:14px;line-height:1.75}
.chat-answer{gap:13px;margin-top:13px;font-size:14px;line-height:1.85}
.chat-answer-icon{display:grid;place-items:center;flex:none;width:26px;height:26px;margin-top:2px;padding:0;border-radius:8px;background:#efe4de;color:var(--accent);font-size:14px;line-height:1}
.chat-answer-text{margin:0;color:#382f2b;line-height:1.85}
.chat-answer-text :deep(p){margin:0 0 14px}
.chat-answer-text :deep(p:last-child){margin-bottom:0}
.chat-answer-text :deep(h1),.chat-answer-text :deep(h2),.chat-answer-text :deep(h3){font-weight:600}
.chat-status{margin:0 0 8px;color:#9a8880;font-size:11px}
.chat-message-actions{gap:5px;margin:7px 0 0 38px;opacity:.78;transition:opacity .18s}
.chat-message:hover .chat-message-actions,.chat-message:focus-within .chat-message-actions{opacity:1}
.chat-actions-user{margin-right:0}
.chat-message-actions button{min-height:26px;padding:2px 7px;border-radius:6px;font-size:11px;transition:background .18s,color .18s}
.chat-message-actions button:hover{background:#efe8e2}
.chat-citations{gap:6px;margin-top:18px}
.chat-sources-label{margin-bottom:1px;color:#9b8a80;font-size:11px;font-weight:600}
.chat-citation{min-height:37px;padding:8px 10px;border-color:#ebe3dd;border-radius:8px;background:#fffdfa;font-size:12px;transition:background .18s,border-color .18s,transform .18s}
.chat-citation:hover{transform:translateY(-1px)}
.chat-bottom{width:min(808px,100%);padding:8px 24px 18px;background:linear-gradient(180deg,#fcfaf700,#fcfaf7 14px)}
.chat-composer{padding:15px 17px 11px;border-color:#e5dcd5;border-radius:19px;background:#fffdfa;box-shadow:0 5px 25px #61453412;transition:border-color .18s,box-shadow .18s}
.chat-composer:focus-within{border-color:#bda495;box-shadow:0 7px 28px #6145341b}
.chat-composer textarea{min-height:68px;max-height:220px;font-size:14px;line-height:1.7}
.chat-composer textarea::placeholder{color:#aa9a90}
.chat-composer-foot{gap:10px;min-height:34px}
.chat-model-label{display:inline-flex;align-items:center;gap:7px;padding:5px 9px;border:1px solid #eee5df;border-radius:7px;background:#faf5f1;color:#836c61;font-size:10px}
.chat-model-dot{width:6px;height:6px;flex:none;border-radius:50%;background:#af755b}
.chat-key-hint{margin-left:auto;color:#aa9c93;font-size:10px;white-space:nowrap}
.send-button{width:34px;height:34px;border-radius:10px;font-size:21px;line-height:1;transition:background .18s,transform .18s}
.send-button:not(:disabled):hover{background:#7e4838;transform:translateY(-1px)}
.send-button:not(:disabled):active{transform:translateY(1px)}
.chat-footnote{margin:9px 0 0;color:#aa9c93;text-align:center;font-size:10px}
.chat-loading{display:grid;place-items:center;min-height:100%;}
.chat-wait-dots{display:inline-flex;align-items:center;gap:5px;min-height:24px;padding:0 2px}
.chat-wait-dots i{width:5px;height:5px;border-radius:50%;background:#a98470;animation:chat-dot-pulse 1.25s ease-in-out infinite}
.chat-wait-dots i:nth-child(2){animation-delay:.16s}.chat-wait-dots i:nth-child(3){animation-delay:.32s}
@keyframes chat-dot-pulse{0%,70%,100%{opacity:.3;transform:translateY(0)}35%{opacity:1;transform:translateY(-4px)}}
.chat-stream-cursor{width:5px;height:1em;border-radius:2px;vertical-align:-2px}
.chat-shell.is-empty{justify-content:center}
.chat-shell.is-empty .chat-history{flex:0 0 auto;min-height:0;overflow:visible;padding:0 24px}
.chat-shell.is-empty .chat-bottom{padding-top:27px;padding-bottom:0}
.chat-empty{height:auto;max-width:760px;margin:0 auto;color:var(--ink);text-align:center}
.chat-empty-mark{display:grid;place-items:center;width:45px;height:45px;margin:0 auto 22px;border-radius:14px;background:#efe3dc;color:var(--accent);font-size:23px}
.chat-empty-eyebrow{margin:0 0 9px!important;color:#9a8173!important;font-size:11px!important;font-weight:600;letter-spacing:.1em}
.chat-empty h2{margin:0;font:400 clamp(25px,3vw,35px)/1.3 'Songti SC','Noto Serif CJK SC',serif;letter-spacing:-.03em;text-wrap:balance}
.chat-empty-description{margin:12px 0 0!important;color:#99877d!important;font-size:13px!important}
.chat-starters{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;margin-top:29px}
.chat-starters button{display:inline-flex;align-items:center;gap:12px;min-height:36px;padding:0 11px;border:1px solid #e8ded7;border-radius:9px;background:#fffdfa;color:#74645b;font-size:11px;transition:background .18s,border-color .18s,transform .18s}
.chat-starters button:hover{transform:translateY(-1px);border-color:#ceb7a9;background:#f8f0eb;color:var(--accent)}
.chat-starters button span{color:#b5a39a}
@media(max-width:780px){.chat-shell{height:calc(100dvh - 70px)}.chat-history{padding:24px 20px 16px}.chat-bottom{padding:8px 17px 15px}.chat-key-hint{display:none}.chat-message-actions{opacity:1}.chat-shell.is-empty .chat-history{padding:0 18px}.chat-starters{gap:7px;margin-top:20px}}
@media(max-width:520px){.chat-question{max-width:92%}.chat-answer{gap:10px}.chat-empty h2{font-size:24px}.chat-starters{flex-direction:column;align-items:stretch;width:100%}.chat-starters button{justify-content:space-between}.chat-footnote{font-size:9px}}

.chat-message-actions{align-items:center;gap:3px;margin-top:6px}
.chat-message-time{margin-right:5px;color:#a89990;font-size:10px;font-variant-numeric:tabular-nums;white-space:nowrap}
.chat-message-actions button{display:inline-flex;align-items:center;justify-content:center;min-width:29px;min-height:29px;padding:5px;border-radius:7px}
.chat-message-actions button svg{width:15px;height:15px}
.chat-message-actions .chat-delete-action span{padding:0 4px;font-size:10px;white-space:nowrap}
.chat-question-edit{width:min(82%,580px);max-width:82%;padding:10px 12px 7px}
.chat-edit-textarea{width:100%;min-height:26px;max-height:180px;padding:0;border:0;outline:0;resize:none;background:transparent;color:var(--ink);font:inherit;font-size:14px;line-height:1.75;field-sizing:content}
.chat-edit-textarea:focus-visible{outline:0}
.chat-edit-actions{display:flex;justify-content:flex-end;gap:3px;margin-top:3px}
.chat-edit-actions button{display:grid;place-items:center;width:27px;height:27px;padding:4px;border-radius:6px;color:#8e776c}
.chat-edit-actions button[type=submit]{color:var(--accent)}
.chat-edit-actions button svg{width:15px;height:15px}
.chat-key-hint{margin-left:0}
.chat-model-picker{display:inline-flex;align-items:center;gap:5px;min-height:30px;margin-left:auto;padding:0 8px;border:1px solid #eee5df;border-radius:8px;background:#faf5f1;color:#836c61}
.chat-model-picker select{min-width:0;max-width:145px;border:0;outline:0;appearance:none;background:transparent;color:inherit;font-size:11px;cursor:pointer}
.chat-model-picker select:disabled{cursor:default}
.chat-model-picker svg{width:12px;height:12px;pointer-events:none}
.chat-model-config-link{min-height:30px;margin-left:auto;padding:0 8px;border:1px solid #eee5df;border-radius:8px;background:#faf5f1;color:var(--accent);font-size:11px}
@media(max-width:520px){.chat-question-edit{width:92%;max-width:92%}.chat-model-picker select{max-width:115px}}
</style>
