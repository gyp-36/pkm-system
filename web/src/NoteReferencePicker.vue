<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'

type NoteChoice = { id: string; title: string; excerpt: string; content_kind?: string }
type NotePage = { items: NoteChoice[]; next_cursor: string | null }

const props = defineProps<{ currentNoteId: string }>()
const emit = defineEmits<{
  (event: 'close'): void
  (event: 'select', note: NoteChoice): void
}>()

const searchInput = ref<HTMLInputElement | null>(null)
const query = ref('')
const appliedQuery = ref('')
const notes = ref<NoteChoice[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const error = ref('')
let requestSequence = 0

async function loadNotes(append = false) {
  if (loading.value && append) return
  const sequence = ++requestSequence
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({ limit: '20' })
  if (appliedQuery.value) {
    params.set('q', appliedQuery.value)
    params.set('q_scope', 'title')
  }
  if (append && nextCursor.value) params.set('cursor', nextCursor.value)
  try {
    const response = await fetch(`/v1/notes?${params}`, { credentials: 'same-origin' })
    if (!response.ok) throw new Error(`加载笔记失败（${response.status}）`)
    const page = await response.json() as NotePage
    if (sequence !== requestSequence) return
    const choices = page.items.filter(note => note.id !== props.currentNoteId)
    notes.value = append ? [...notes.value, ...choices] : choices
    nextCursor.value = page.next_cursor
  } catch (cause) {
    if (sequence === requestSequence) error.value = cause instanceof Error ? cause.message : '加载笔记失败'
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

function searchNotes() {
  appliedQuery.value = query.value.trim()
  nextCursor.value = null
  notes.value = []
  void loadNotes()
}

onMounted(async () => {
  void loadNotes()
  await nextTick()
  searchInput.value?.focus()
})
</script>

<template>
  <div class="note-reference-backdrop" @click.self="emit('close')">
    <section class="note-reference-picker" role="dialog" aria-modal="true" aria-labelledby="note-reference-title" @keydown.esc.stop.prevent="emit('close')">
      <header class="note-reference-head">
        <div><h2 id="note-reference-title">引用其他笔记</h2><p>选择一篇笔记，在当前光标处插入可跳转的链接。</p></div>
        <button type="button" class="icon-button" aria-label="关闭笔记选择" @click="emit('close')"><AppIcon name="close" /></button>
      </header>
      <form class="note-reference-search" @submit.prevent="searchNotes">
        <input ref="searchInput" v-model="query" maxlength="150" aria-label="按标题搜索笔记" placeholder="按标题搜索笔记" />
        <button type="submit" class="quiet-button">搜索</button>
      </form>
      <div class="note-reference-body">
        <p v-if="error" class="note-reference-status" role="alert">{{ error }} <button type="button" class="text-link" @click="loadNotes()">重试</button></p>
        <div v-if="notes.length" class="note-reference-list">
          <button v-for="note in notes" :key="note.id" type="button" class="note-reference-item" :aria-label="`引用笔记：${note.title || '无标题笔记'}`" @click="emit('select', note)">
            <AppIcon name="note" />
            <span><strong>{{ note.title || '无标题笔记' }}</strong><small v-if="note.excerpt">{{ note.excerpt }}</small></span>
          </button>
        </div>
        <p v-else-if="!loading && !error" class="note-reference-status">{{ appliedQuery ? '没有匹配的笔记' : '没有可引用的其他笔记' }}</p>
        <p v-if="loading" class="note-reference-status">正在加载笔记…</p>
        <button v-if="nextCursor && !loading" type="button" class="note-reference-more" @click="loadNotes(true)">加载更多</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.note-reference-backdrop{position:fixed;z-index:40;inset:0;display:grid;place-items:center;padding:20px;background:#2d201b66}
.note-reference-picker{display:flex;width:min(620px,100%);height:min(580px,calc(100dvh - 40px));flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:16px;background:var(--page);box-shadow:0 24px 70px #2d201b33}
.note-reference-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:21px 24px 17px;border-bottom:1px solid var(--line)}
.note-reference-head h2{margin:0;font:400 24px 'Songti SC','Noto Serif CJK SC',serif}
.note-reference-head p{margin:7px 0 0;color:var(--muted);font-size:12px}
.note-reference-search{display:flex;gap:8px;padding:16px 24px;border-bottom:1px solid var(--line)}
.note-reference-search input{flex:1;min-width:0;height:37px;padding:0 11px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink);font-size:12px}
.note-reference-body{min-height:0;flex:1;overflow:auto;padding:16px 24px}
.note-reference-list{display:flex;flex-direction:column;gap:5px}
.note-reference-item{display:flex;align-items:flex-start;gap:11px;width:100%;min-height:55px;padding:11px;border:1px solid transparent;border-radius:9px;background:transparent;color:var(--ink);text-align:left}
.note-reference-item:hover,.note-reference-item:focus-visible{border-color:var(--line);background:#fffaf6}
.note-reference-item>svg{width:18px;height:18px;flex:none;margin-top:2px;color:var(--accent)}
.note-reference-item span{display:flex;min-width:0;flex-direction:column;gap:4px}
.note-reference-item strong,.note-reference-item small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.note-reference-item strong{font-size:13px;font-weight:600}
.note-reference-item small{color:var(--muted);font-size:11px}
.note-reference-status{margin:24px 0;color:var(--muted);font-size:12px;text-align:center}
.note-reference-more{display:block;min-height:35px;margin:20px auto 0;padding:0 16px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--accent);font-size:12px}
@media(max-width:480px){.note-reference-backdrop{padding:10px}.note-reference-picker{height:calc(100dvh - 20px)}.note-reference-head,.note-reference-search,.note-reference-body{padding-right:14px;padding-left:14px}}
</style>
