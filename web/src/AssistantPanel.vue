<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

type SearchHit = { note_id: string; title: string; notebook_id: string | null; version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number; snippet: string; updated_at: string; match_source: 'keyword' | 'semantic' | 'both'; score: number }
type UserMessage = { id: string; role: 'user'; content: { text: string }; created_at: string }
type AssistantMessage = { id: string; role: 'assistant'; content: { items: SearchHit[]; semantic_status: 'ready' | 'unavailable' }; created_at: string }
type ChatMessage = UserMessage | AssistantMessage
type SentMessages = { id: string; title: string; created_at: string; updated_at: string; messages: [UserMessage, AssistantMessage] }
type Citation = { note_id: string; note_version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number }

const props = defineProps<{ conversationId: string; messages: ChatMessage[]; loading: boolean; modelName: string | null; modelConfigured: boolean }>()
const emit = defineEmits<{
  (e: 'answered', conversationId: string, result: SentMessages): void
  (e: 'openCitation', citation: Citation): void
}>()
const question = ref('')
const busy = ref(false)
const error = ref('')
const history = ref<HTMLDivElement | null>(null)

async function ask() {
  const asked = question.value.trim()
  if (!asked || busy.value || !props.conversationId) return
  const conversationId = props.conversationId
  busy.value = true
  error.value = ''
  try {
    const response = await fetch(`/v1/assistant/conversations/${conversationId}/messages`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: asked }),
    })
    if (!response.ok) {
      let detail = `请求失败（${response.status}）`
      try { const payload = await response.json() as { detail?: string }; if (payload.detail) detail = payload.detail } catch { /* Keep status. */ }
      throw new Error(detail)
    }
    emit('answered', conversationId, await response.json() as SentMessages)
    question.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '发送失败，请重试'
  } finally {
    busy.value = false
  }
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  void ask()
}

const modelLabel = computed(() => {
  if (!props.modelConfigured || !props.modelName) return '未配置聊天模型'
  return props.modelName === 'deepseek-v4-pro' ? 'DeepSeek V4 Pro' : props.modelName === 'deepseek-flash' ? 'DeepSeek Flash' : props.modelName
})

function openResult(item: SearchHit) {
  emit('openCitation', {
    note_id: item.note_id,
    note_version: item.version,
    source_field: item.source_field,
    start_offset: item.start_offset,
    end_offset: item.end_offset,
  })
}

watch(() => [props.messages.length, props.loading, busy.value], async () => {
  await nextTick()
  if (history.value) history.value.scrollTop = history.value.scrollHeight
})
</script>

<template>
  <div class="chat-shell">
    <div ref="history" class="chat-history">
      <div v-if="loading" class="chat-empty"><span>…</span><h2>正在加载对话</h2></div>
      <div v-else-if="!messages.length" class="chat-empty"><span>✦</span><h2>开始对话</h2><p>我会从你的笔记中检索相关片段</p></div>
      <div v-else class="chat-turns">
        <div v-for="message in messages" :key="message.id" class="chat-message" :class="`message-${message.role}`">
          <div v-if="message.role === 'user'" class="chat-question">{{ message.content.text }}</div>
          <div v-else class="chat-answer">
            <span class="chat-answer-icon">✦</span>
            <div class="chat-answer-content">
              <small v-if="message.content.semantic_status === 'unavailable'" class="chat-status">语义检索暂不可用，以下为关键词检索结果</small>
              <div v-if="message.content.items.length" class="chat-results">
                <button v-for="(item, index) in message.content.items" :key="`${message.id}-${item.note_id}`" class="chat-result" @click="openResult(item)">
                  <span class="chat-result-heading"><strong>{{ item.title }}</strong><span class="chat-result-index">{{ index + 1 }}</span></span>
                  <span class="chat-result-snippet">{{ item.snippet }}</span>
                  <span class="chat-result-meta"><span>{{ item.source_field === 'title' ? '标题' : '正文' }}</span><span>{{ item.match_source === 'both' ? '关键词 + 语义' : item.match_source === 'semantic' ? '语义匹配' : '关键词匹配' }}</span><span>打开原文 ↗</span></span>
                </button>
              </div>
              <p v-else class="chat-no-results">没有找到相关笔记片段。</p>
            </div>
          </div>
        </div>
        <div v-if="busy" class="chat-pending"><span>检索中…</span></div>
      </div>
    </div>
    <div class="chat-bottom">
      <p v-if="error" class="chat-error" role="alert">{{ error }}</p>
      <form class="chat-composer" @submit.prevent="ask">
        <textarea v-model="question" rows="2" aria-label="输入消息" placeholder="输入问题，搜索你的笔记…" @keydown="handleComposerKeydown" />
        <div class="chat-composer-foot"><span class="chat-model-label" :title="modelConfigured ? '当前账号配置的模型；本对话目前使用笔记检索回答' : '本对话使用笔记检索回答'">{{ modelConfigured ? `当前模型 · ${modelLabel}` : '笔记检索' }}</span><button type="submit" class="send-button" :disabled="busy || loading || !conversationId || !question.trim()" aria-label="发送消息">{{ busy ? '…' : '↑' }}</button></div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.chat-shell{display:flex;flex-direction:column;height:calc(100vh - 116px);min-height:480px}
.chat-history{flex:1;min-height:0;overflow-y:auto;padding:25px clamp(24px,5vw,72px)}
.chat-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--accent)}
.chat-empty>span{font-size:34px}.chat-empty h2{margin:16px 0 0;color:var(--ink);font:400 25px 'Songti SC','Noto Serif CJK SC',serif}.chat-empty p{margin:10px 0;color:var(--muted);font-size:12px}
.chat-turns{width:min(800px,100%);margin:0 auto}.chat-message{margin-bottom:25px}.chat-question{width:fit-content;max-width:84%;margin-left:auto;padding:11px 16px;border-radius:14px 14px 3px 14px;background:var(--hero);font-size:13px;line-height:1.7;white-space:pre-wrap}.chat-answer{display:flex;gap:14px;margin-top:10px;font-size:13px;line-height:1.75}.chat-answer-icon{padding-top:2px;color:var(--accent)}.chat-answer-content{flex:1;min-width:0}.chat-status{display:block;margin:0 0 10px;color:var(--muted)}.chat-results{display:grid;gap:9px}.chat-result{display:block;width:100%;padding:13px 15px;border:1px solid var(--line);border-radius:11px;background:var(--card);color:var(--ink);text-align:left;cursor:pointer}.chat-result:hover{border-color:#c8a895;background:#fffdfa}.chat-result-heading,.chat-result-meta{display:flex;align-items:center;gap:10px}.chat-result-heading{justify-content:space-between}.chat-result-heading strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}.chat-result-index{display:grid;place-items:center;flex:none;width:21px;height:21px;border-radius:50%;background:var(--hero);color:var(--accent);font-size:10px}.chat-result-snippet{display:-webkit-box;margin:9px 0 10px;overflow:hidden;color:var(--muted);font-size:12px;line-height:1.7;-webkit-box-orient:vertical;-webkit-line-clamp:4}.chat-result-meta{flex-wrap:wrap;color:#9b887d;font-size:10px}.chat-result-meta span:last-child{margin-left:auto;color:var(--accent)}.chat-no-results{margin:0;color:var(--muted)}.chat-pending{margin:12px 0 0 30px;color:var(--muted);font-size:12px}.chat-bottom{width:min(848px,100%);margin:0 auto;padding:15px 24px 27px}.chat-composer{padding:12px 15px 10px;border:1px solid var(--line);border-radius:15px;background:#fff;box-shadow:0 8px 28px #6a3d3010}.chat-composer textarea{display:block;width:100%;min-height:55px;resize:vertical;border:0;outline:0;color:var(--ink);background:transparent;font-size:14px;line-height:1.6}.chat-composer-foot{display:flex;justify-content:space-between;align-items:center;min-height:32px;color:var(--muted);font-size:11px}.send-button{width:32px;height:32px;border:0;border-radius:9px;background:var(--accent);color:#fff;font-size:20px}.send-button:disabled{opacity:.45;cursor:not-allowed}.chat-error{margin:0 0 10px;color:#a34535;font-size:12px}
.chat-model-label{overflow:hidden;color:#907e73;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:780px){.chat-shell{height:calc(100vh - 113px)}.chat-history{padding:20px}.chat-bottom{padding:12px 17px 19px}}
</style>
