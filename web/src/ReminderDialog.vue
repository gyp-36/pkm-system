<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'

type NoteChoice = { id: string; title: string }
const props = defineProps<{ initialDate: string; fixedNoteId?: string | null; fixedNoteTitle?: string | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const text = ref('')
const dueAt = ref('')
const noteId = ref<string | null>(props.fixedNoteId || null)
const noteTitle = ref(props.fixedNoteTitle || '')
const query = ref('')
const choices = ref<NoteChoice[]>([])
const searching = ref(false)
const saving = ref(false)
const error = ref('')
const textInput = ref<HTMLInputElement | null>(null)
let searchVersion = 0

function defaultTime(day: string) {
  const now = new Date()
  const currentDay = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  const currentTime = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(now)
  const [currentHour, currentMinute] = currentTime.split(':').map(Number)
  const minutes = currentHour * 60 + currentMinute + 30
  const sameDay = day === currentDay
  const selectedMinutes = sameDay ? Math.min(minutes, 24 * 60 - 1) : 9 * 60
  const hour = String(Math.floor(selectedMinutes / 60)).padStart(2, '0')
  const minute = String(selectedMinutes % 60).padStart(2, '0')
  return `${day}T${hour}:${minute}`
}
dueAt.value = defaultTime(props.initialDate)

watch(query, async value => {
  const version = ++searchVersion
  if (!value.trim() || props.fixedNoteId) { choices.value = []; return }
  searching.value = true
  try {
    const response = await fetch(`/v1/notes?limit=20&q_scope=title&q=${encodeURIComponent(value.trim())}`)
    if (!response.ok) throw new Error('笔记搜索失败')
    const data = await response.json() as { items: NoteChoice[] }
    if (version === searchVersion) choices.value = data.items
  } catch (cause) { if (version === searchVersion) error.value = cause instanceof Error ? cause.message : '笔记搜索失败' }
  finally { if (version === searchVersion) searching.value = false }
})

function chooseNote(note: NoteChoice | null) {
  noteId.value = note?.id || null
  noteTitle.value = note?.title || ''
  choices.value = []
  query.value = ''
}

async function save() {
  error.value = ''
  if (!text.value.trim() || !dueAt.value) { error.value = '请填写事项和到期时间'; return }
  const due = new Date(`${dueAt.value}:00+08:00`)
  if (Number.isNaN(due.getTime())) { error.value = '到期时间无效'; return }
  saving.value = true
  try {
    const response = await fetch('/v1/reminders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text.value.trim(), due_at: due.toISOString(), note_id: noteId.value }) })
    if (!response.ok) {
      const data = await response.json().catch(() => ({})) as { detail?: string }
      throw new Error(typeof data.detail === 'string' ? data.detail : '保存提醒失败')
    }
    emit('saved')
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '保存提醒失败' }
  finally { saving.value = false }
}
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape') emit('close') }
onMounted(() => { window.addEventListener('keydown', onKeydown); textInput.value?.focus() })
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="reminder-dialog-backdrop" @click.self="emit('close')">
      <section class="reminder-dialog" role="dialog" aria-modal="true" aria-labelledby="reminder-dialog-title">
        <header><div><h2 id="reminder-dialog-title">新建提醒</h2><p>在选定时间提醒自己处理事项。</p></div><button class="icon-button" type="button" aria-label="关闭提醒弹窗" @click="emit('close')"><AppIcon name="close" /></button></header>
        <form @submit.prevent="save">
          <label>提醒事项<input ref="textInput" v-model="text" maxlength="200" required placeholder="例如：回看研究笔记" /></label>
          <label>到期时间（北京时间）<input v-model="dueAt" type="datetime-local" required /></label>
          <div class="reminder-dialog-note">
            <strong>关联笔记</strong>
            <span v-if="fixedNoteId" class="reminder-picked-note">{{ fixedNoteTitle || '当前笔记' }}</span>
            <template v-else>
              <span v-if="noteId" class="reminder-picked-note">{{ noteTitle || '已选笔记' }} <button type="button" aria-label="移除关联笔记" @click="chooseNote(null)">×</button></span>
              <input v-model="query" type="search" placeholder="搜索已有笔记；留空则创建独立提醒" aria-label="搜索关联笔记" />
              <small v-if="searching">搜索中…</small>
              <div v-if="choices.length" class="reminder-note-choices"><button v-for="note in choices" :key="note.id" type="button" @click="chooseNote(note)">{{ note.title || '无标题笔记' }}</button></div>
            </template>
          </div>
          <p v-if="error" class="reminder-dialog-error" role="alert">{{ error }}</p>
          <footer><button class="quiet-button" type="button" @click="emit('close')">取消</button><button class="accent-button" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存提醒' }}</button></footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.reminder-dialog-backdrop{position:fixed;inset:0;z-index:80;display:grid;place-items:center;padding:20px;background:#251b17a3}
.reminder-dialog{width:min(100%,520px);max-height:calc(100vh - 40px);overflow:auto;padding:28px;border:1px solid var(--line);border-radius:18px;background:var(--card);box-shadow:0 24px 70px #26191340;color:var(--ink)}
.reminder-dialog header,.reminder-dialog footer{display:flex;align-items:center;justify-content:space-between;gap:12px}
.reminder-dialog h2{margin:0;font:400 26px 'Songti SC',serif}.reminder-dialog p{margin:7px 0 0;color:var(--muted);font-size:12px}
.reminder-dialog form{display:grid;gap:18px;margin-top:25px}.reminder-dialog label,.reminder-dialog-note{display:grid;gap:8px;font-size:12px;font-weight:600}
.reminder-dialog input{box-sizing:border-box;width:100%;height:43px;padding:0 12px;border:1px solid var(--line);border-radius:9px;background:#fff;color:var(--ink);font:inherit;font-weight:400}
.reminder-dialog-note{position:relative}.reminder-dialog-note>strong{font-size:12px}.reminder-picked-note{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--hero);font-weight:400}.reminder-picked-note button{border:0;background:transparent;color:var(--accent);cursor:pointer}
.reminder-note-choices{max-height:190px;overflow:auto;border:1px solid var(--line);border-radius:9px}.reminder-note-choices button{display:block;width:100%;padding:10px 12px;border:0;border-bottom:1px solid var(--line);background:#fff;color:var(--ink);text-align:left;cursor:pointer}.reminder-note-choices button:hover{background:var(--hero)}
.reminder-dialog .reminder-dialog-error{color:#a95042}.reminder-dialog footer{justify-content:flex-end;margin-top:5px}
</style>
