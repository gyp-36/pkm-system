<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import AssistantPanel from './AssistantPanel.vue'
import AppIcon from './AppIcon.vue'
import ModelConnectionSettings from './ModelConnectionSettings.vue'
import loginArtwork from './assets/login-still-life.jpg'

type Account = { id: string; email: string }
type Category = { id: string; name: string; note_count?: number }
type NoteSummary = { id: string; title: string; excerpt: string; notebook_id: string | null; tag_ids: string[]; version: number; index_status: string; updated_at: string; created_at: string }
type Note = NoteSummary & { body_md: string }
type Position = { note_id: string; version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number }
type Citation = { note_id: string; note_version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number }
type SearchHit = { note_id: string; title: string; notebook_id: string | null; version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number; snippet: string; updated_at: string; match_source: 'keyword' | 'semantic' | 'both'; score: number }
type UserMessage = { id: string; role: 'user'; content: { text: string }; created_at: string }
type AssistantMessage = { id: string; role: 'assistant'; content: { items: SearchHit[]; semantic_status: 'ready' | 'unavailable' }; created_at: string }
type ChatMessage = UserMessage | AssistantMessage
type Conversation = { id: string; title: string; created_at: string; updated_at: string; messages: ChatMessage[]; loaded: boolean; loading: boolean }
type ConversationSummary = Pick<Conversation, 'id' | 'title' | 'created_at' | 'updated_at'>
type SentMessages = ConversationSummary & { messages: [UserMessage, AssistantMessage] }
type View = 'notes' | 'notebooks' | 'assistant' | 'calendar' | 'reminders'
type Reminder = { id: string; text: string; done: boolean }
type CalendarEvent = { id: string; date: string; text: string }

const account = ref<Account | null>(null)
const authMode = ref<'login' | 'register'>('login')
const email = ref('')
const password = ref('')
const showPassword = ref(false)
const busy = ref(false)
const booting = ref(true)
const error = ref('')
const notice = ref('')
const notebooks = ref<Category[]>([])
const tags = ref<Category[]>([])
const notes = ref<NoteSummary[]>([])
const sidebarNotesByNotebook = ref<Record<string, NoteSummary[]>>({})
const unclassifiedNotes = ref<NoteSummary[]>([])
const expandedNotebookIds = ref<string[]>([])
const draggedNoteId = ref('')
const dragOverNotebookId = ref('')
const movingNoteId = ref('')
const nextCursor = ref<string | null>(null)
const draft = ref<Note | null>(null)
const savedDraft = ref('')
const editorMode = ref<'write' | 'preview'>('write')
const saveState = ref<'saved' | 'saving' | 'unsaved' | 'error'>('saved')
const moreActionsOpen = ref(false)
const editorTagsOpen = ref(false)
const bodyInput = ref<HTMLTextAreaElement | null>(null)
const titleInput = ref<HTMLInputElement | null>(null)
const searchQuery = ref('')
const searchMode = ref<'all' | 'title' | 'tag'>('all')
const results = ref<NoteSummary[]>([])
const searched = ref(false)
const searchNextCursor = ref<string | null>(null)
const filterNotebook = ref('')
const filterTag = ref('')
const updatedDesc = ref(true)
const view = ref<View>('notes')
const listOpen = ref(true)
const editorOpen = ref(false)
const cardLayout = ref<'grid' | 'list'>('grid')
const conversations = ref<Conversation[]>([])
const activeConversationId = ref('')
let conversationLoadVersion = 0
const conversationSearchOpen = ref(false)
const conversationQuery = ref('')
const modelConfigured = ref(false)
const currentModelName = ref<string | null>(null)
const editingConversationId = ref('')
const editingConversationTitle = ref('')
const pendingConversationDelete = ref('')
const calendarDate = ref(new Date())
const selectedDay = ref(new Date().getDate())
const calendarEvents = ref<CalendarEvent[]>([])
const eventInput = ref('')
const reminders = ref<Reminder[]>([])
const reminderInput = ref('')
const categorySearchOpen = ref<'notebooks' | 'tags' | ''>('')
const notebookCreateMenuOpen = ref(false)
const notebookCreateMenuPosition = ref({ top: 0, left: 0 })
const notebookCreateFirstOption = ref<HTMLButtonElement | null>(null)
const notebooksSectionOpen = ref(true)
const tagsSectionOpen = ref(true)
const categorySearch = ref({ notebooks: '', tags: '' })
const categorySearchInput = ref<HTMLInputElement | null>(null)
const newCategoryKind = ref<'notebooks' | 'tags' | ''>('')
const newCategoryName = ref('')
const editingCategory = ref('')
const editingCategoryName = ref('')
const pendingCategoryDelete = ref('')
const pendingNoteDelete = ref(false)
const filteredNotebooks = computed(() => notebooks.value.filter(item => item.name.toLocaleLowerCase().includes(categorySearch.value.notebooks.trim().toLocaleLowerCase())))
const filteredTags = computed(() => tags.value.filter(item => item.name.toLocaleLowerCase().includes(categorySearch.value.tags.trim().toLocaleLowerCase())))
const tagNames = computed<Record<string, string>>(() => Object.fromEntries(tags.value.map(item => [item.id, item.name])))
const visibleNotes = computed(() => searched.value ? results.value : notes.value)
const profileMenuOpen = ref(false)
const profileDialog = ref(false)
const activeSettingsSection = ref<'profile' | 'model'>('profile')
const settingsSearch = ref('')
const visibleSettingsItems = computed(() => [
  { id: 'profile' as const, name: '个人信息', group: '个人' },
  { id: 'model' as const, name: '模型配置', group: '集成' },
].filter(item => `${item.name} ${item.group}`.toLocaleLowerCase().includes(settingsSearch.value.trim().toLocaleLowerCase())))
const calendarDays = computed(() => {
  const year = calendarDate.value.getFullYear(), month = calendarDate.value.getMonth()
  const start = new Date(year, month, 1).getDay()
  const count = new Date(year, month + 1, 0).getDate()
  return [...Array(start).fill(null), ...Array.from({ length: count }, (_, i) => i + 1)] as (number | null)[]
})
const activeConversation = computed(() => conversations.value.find(item => item.id === activeConversationId.value))
const filteredConversations = computed(() => conversations.value.filter(item => item.title.toLocaleLowerCase().includes(conversationQuery.value.trim().toLocaleLowerCase())))
const selectedDateKey = computed(() => `${calendarDate.value.getFullYear()}-${calendarDate.value.getMonth() + 1}-${selectedDay.value}`)
const selectedEvents = computed(() => calendarEvents.value.filter(item => item.date === selectedDateKey.value))
let statusTimer: ReturnType<typeof setInterval> | undefined
let autoSaveTimer: ReturnType<typeof setTimeout> | undefined

const previewHtml = computed(() => DOMPurify.sanitize(marked.parse(draft.value?.body_md || '') as string, { FORBID_TAGS: ['img', 'iframe'] }))
const isDirty = computed(() => draft.value !== null && JSON.stringify(draft.value) !== savedDraft.value)

async function request<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await fetch(path, { method, credentials: 'same-origin', headers: data === undefined ? {} : { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data) })
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const value = (await response.json()) as { detail?: string | { msg?: string }[] }
      if (typeof value.detail === 'string') detail = value.detail
      else if (Array.isArray(value.detail)) detail = value.detail.map(item => item.msg).join('；')
    } catch { /* Retain the status message. */ }
    if (response.status === 401 && path !== '/v1/auth/login') account.value = null
    throw new Error(detail)
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

function showError(cause: unknown) { error.value = cause instanceof Error ? cause.message : '操作失败，请稍后重试'; notice.value = '' }
function confirmLeave() { return !isDirty.value || window.confirm('当前笔记有未保存的修改，确定离开吗？') }
function formatDate(value: string) { return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }

async function loadCategories() {
  ;[notebooks.value, tags.value] = await Promise.all([request<Category[]>('/v1/notebooks'), request<Category[]>('/v1/tags')])
  const nonemptyIds = new Set(notebooks.value.filter(item => (item.note_count ?? 0) > 0).map(item => item.id))
  expandedNotebookIds.value = expandedNotebookIds.value.filter(id => nonemptyIds.has(id))
}

async function fetchSidebarNotes(filter: Record<string, string>): Promise<NoteSummary[]> {
  const items: NoteSummary[] = []
  let cursor: string | null = null
  do {
    const params = new URLSearchParams({ ...filter, limit: '100' })
    if (cursor) params.set('cursor', cursor)
    const page = await request<{ items: NoteSummary[]; next_cursor: string | null }>(`/v1/notes?${params}`)
    items.push(...page.items)
    cursor = page.next_cursor
  } while (cursor)
  return items
}

let sidebarLoadVersion = 0
async function loadSidebarNotes() {
  const version = ++sidebarLoadVersion
  const notebookIds = [...expandedNotebookIds.value]
  const [unclassified, ...groups] = await Promise.all([
    fetchSidebarNotes({ unclassified: 'true' }),
    ...notebookIds.map(id => fetchSidebarNotes({ notebook_id: id })),
  ])
  if (version !== sidebarLoadVersion) return
  unclassifiedNotes.value = unclassified
  const next = { ...sidebarNotesByNotebook.value }
  notebookIds.forEach((id, index) => { next[id] = groups[index] })
  sidebarNotesByNotebook.value = next
}

async function loadModelConnection() {
  const connection = await request<{ configured: boolean; model_name: string | null }>('/v1/model-connection')
  modelConfigured.value = connection.configured
  currentModelName.value = connection.model_name
}

async function loadNotes(append = false) {
  const params = new URLSearchParams({ limit: '30', updated_desc: String(updatedDesc.value) })
  if (filterNotebook.value) params.set('notebook_id', filterNotebook.value)
  if (filterTag.value) params.set('tag_id', filterTag.value)
  if (append && nextCursor.value) params.set('cursor', nextCursor.value)
  const page = await request<{ items: NoteSummary[]; next_cursor: string | null }>(`/v1/notes?${params}`)
  notes.value = append ? [...notes.value, ...page.items] : page.items
  nextCursor.value = page.next_cursor
}

async function submitAuth() {
  busy.value = true; error.value = ''
  try {
    account.value = await request<Account>(`/v1/auth/${authMode.value}`, 'POST', { email: email.value, password: password.value })
    password.value = ''
    await Promise.all([loadCategories(), loadNotes(), loadSidebarNotes(), loadConversations()])
    void loadModelConnection().catch(() => { modelConfigured.value = false })
  } catch (cause) { showError(cause) }
  finally { busy.value = false }
}

async function logout() {
  if (!confirmLeave()) return
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  try {
    await request<void>('/v1/auth/logout', 'POST')
    account.value = null; draft.value = null; notes.value = []; unclassifiedNotes.value = []; sidebarNotesByNotebook.value = {}; expandedNotebookIds.value = []; conversations.value = []; activeConversationId.value = ''; reminders.value = []; calendarEvents.value = []
    clearSearch(); searchMode.value = 'all'
    profileMenuOpen.value = false; profileDialog.value = false; modelConfigured.value = false
  } catch (cause) { showError(cause) }
}

function createDraft() {
  if (!confirmLeave()) return
  if (view.value === 'assistant') view.value = 'notes'
  editorOpen.value = true
  pendingNoteDelete.value = false
  draft.value = { id: '', title: '', excerpt: '', body_md: '', notebook_id: view.value === 'notebooks' ? filterNotebook.value || null : null, tag_ids: [], version: 0, index_status: 'pending', created_at: '', updated_at: '' }
  savedDraft.value = JSON.stringify(draft.value)
  saveState.value = 'saved'; moreActionsOpen.value = false; editorTagsOpen.value = false
  editorMode.value = 'write'
  void nextTick(() => titleInput.value?.focus())
}

async function openNote(id: string, position?: Position) {
  if (draft.value?.id !== id && !confirmLeave()) return
  if (view.value !== 'notebooks') view.value = 'notes'
  editorOpen.value = true
  pendingNoteDelete.value = false
  error.value = ''
  try {
    draft.value = await request<Note>(`/v1/notes/${id}`)
    savedDraft.value = JSON.stringify(draft.value)
    saveState.value = 'saved'; moreActionsOpen.value = false; editorTagsOpen.value = false
    if (position) {
      if (position.version !== draft.value.version) { notice.value = '笔记已更新，请重新搜索以定位最新原文'; return }
      editorMode.value = 'write'
      await nextTick()
      if (position.source_field === 'body' && bodyInput.value) {
        // API offsets count Unicode code points; textarea offsets count UTF-16 code units.
        const start = Array.from(draft.value.body_md).slice(0, position.start_offset).join('').length
        const end = Array.from(draft.value.body_md).slice(0, position.end_offset).join('').length
        bodyInput.value.focus(); bodyInput.value.setSelectionRange(start, end)
        bodyInput.value.scrollTop = Math.max(0, draft.value.body_md.slice(0, start).split('\n').length - 4) * 25
      } else titleInput.value?.focus()
    }
  } catch (cause) { showError(cause) }
}

async function saveNote() {
  if (!draft.value || !isDirty.value || saveState.value === 'saving') return
  const startId = draft.value.id
  const snapshot = { title: draft.value.title, body_md: draft.value.body_md, notebook_id: draft.value.notebook_id, tag_ids: [...draft.value.tag_ids] }
  saveState.value = 'saving'; error.value = ''
  try {
    const persisted = startId
      ? await request<Note>(`/v1/notes/${startId}`, 'PATCH', { ...snapshot, version: draft.value.version })
      : await request<Note>('/v1/notes', 'POST', snapshot)
    if (!draft.value || (startId ? draft.value.id !== startId : draft.value.id !== '')) return
    const latest = draft.value
    const changedDuringSave = latest.title !== snapshot.title || latest.body_md !== snapshot.body_md
    savedDraft.value = JSON.stringify(persisted)
    draft.value = changedDuringSave
      ? { ...latest, id: persisted.id, version: persisted.version, index_status: persisted.index_status, created_at: persisted.created_at, updated_at: persisted.updated_at }
      : persisted
    saveState.value = changedDuringSave ? 'unsaved' : 'saved'
    void Promise.all([loadNotes(), loadCategories(), loadSidebarNotes(), ...(searched.value ? [runSearch()] : [])]).catch(showError)
    if (changedDuringSave) scheduleAutoSave()
  } catch (cause) { saveState.value = 'error'; showError(cause) }
}

function scheduleAutoSave() {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  if (!draft.value || !isDirty.value) return
  saveState.value = 'unsaved'
  autoSaveTimer = setTimeout(() => void saveNote(), 700)
}

function applyEditorCommand(command: string) {
  const input = bodyInput.value
  if (!input || !draft.value) return
  if (command === 'undo' || command === 'redo') {
    input.focus()
    document.execCommand(command)
    return
  }
  const value = draft.value.body_md
  const start = input.selectionStart
  const end = input.selectionEnd
  const selected = value.slice(start, end)
  let replacement = selected
  let selectionStart = start
  let selectionEnd = start
  const wrap = (before: string, after = before, fallback = '文本') => {
    const content = selected || fallback
    replacement = `${before}${content}${after}`
    selectionStart = start + before.length
    selectionEnd = selectionStart + content.length
  }
  if (command === 'bold') wrap('**', '**', '粗体文字')
  else if (command === 'italic') wrap('*', '*', '斜体文字')
  else if (command === 'underline') wrap('<u>', '</u>', '下划线文字')
  else if (command === 'link') wrap('[', '](链接地址)', '链接文字')
  else if (command === 'image') wrap('![', '](图片地址)', '图片描述')
  else if (command === 'code') wrap('```\n', '\n```', '代码')
  else if (command === 'quote' || command === 'list' || command === 'checklist' || command === 'heading') {
    const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1
    const lineEndIndex = value.indexOf('\n', end)
    const lineEnd = lineEndIndex === -1 ? value.length : lineEndIndex
    const prefix = command === 'quote' ? '> ' : command === 'list' ? '- ' : command === 'checklist' ? '- [ ] ' : '## '
    const lines = value.slice(lineStart, lineEnd).split('\n')
    replacement = lines.map(line => `${prefix}${line.replace(/^(> |[-*+] |[-*+] \[ \] |#{1,6} )/, '')}`).join('\n')
    selectionStart = lineStart
    selectionEnd = lineStart + replacement.length
  }
  draft.value.body_md = value.slice(0, start) + replacement + value.slice(end)
  nextTick(() => {
    input.focus()
    input.setSelectionRange(selectionStart, selectionEnd)
  })
}

async function deleteNote() {
  if (!draft.value?.id) return
  if (!pendingNoteDelete.value) { pendingNoteDelete.value = true; return }
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  busy.value = true
  try {
    await request<void>(`/v1/notes/${draft.value.id}?version=${draft.value.version}`, 'DELETE')
    draft.value = null; savedDraft.value = ''; editorOpen.value = false; notice.value = '笔记已删除'
    pendingNoteDelete.value = false
    await Promise.all([loadNotes(), loadCategories(), loadSidebarNotes(), ...(searched.value ? [runSearch()] : [])])
  } catch (cause) { showError(cause) }
  finally { busy.value = false }
}

function exportCurrentNote() {
  if (!draft.value?.id) return
  if (isDirty.value && !window.confirm('当前笔记有未保存修改。导出将包含上次保存的版本，继续吗？')) return
  window.location.assign(`/v1/notes/${draft.value.id}/export`)
}

function exportAllNotes() {
  window.location.assign('/v1/notes/export')
}

function startCreateCategory(kind: 'notebooks' | 'tags') {
  notebookCreateMenuOpen.value = false
  newCategoryKind.value = kind
  if (kind === 'notebooks') notebooksSectionOpen.value = true
  else tagsSectionOpen.value = true
  newCategoryName.value = ''
  pendingCategoryDelete.value = ''
  nextTick(() => document.querySelector<HTMLInputElement>('.category-create-input')?.focus())
}
function toggleNotebookCreateMenu(event: MouseEvent) {
  notebookCreateMenuOpen.value = !notebookCreateMenuOpen.value
  if (notebookCreateMenuOpen.value) {
    const trigger = event.currentTarget as HTMLElement
    const bounds = trigger.getBoundingClientRect()
    notebookCreateMenuPosition.value = {
      top: Math.min(bounds.top, window.innerHeight - 100),
      left: Math.max(8, Math.min(bounds.right + 10, window.innerWidth - 188)),
    }
    notebooksSectionOpen.value = true
    void nextTick(() => notebookCreateFirstOption.value?.focus())
  }
}
function toggleNotebooksSection() {
  notebooksSectionOpen.value = !notebooksSectionOpen.value
  if (!notebooksSectionOpen.value) notebookCreateMenuOpen.value = false
}
function createNoteFromNotebookMenu() {
  notebookCreateMenuOpen.value = false
  createDraft()
}
async function createCategory(kind: 'notebooks' | 'tags') {
  const name = newCategoryName.value.trim()
  if (!name) { newCategoryKind.value = ''; return }
  try { await request(`/v1/${kind}`, 'POST', { name }); await loadCategories(); newCategoryKind.value = ''; newCategoryName.value = '' } catch (cause) { showError(cause) }
}
function startRenameCategory(item: Category) {
  editingCategory.value = item.id
  editingCategoryName.value = item.name
  pendingCategoryDelete.value = ''
  nextTick(() => document.querySelector<HTMLInputElement>('.category-rename-input')?.focus())
}
async function renameCategory(kind: 'notebooks' | 'tags', item: Category) {
  const name = editingCategoryName.value.trim()
  if (!name) { editingCategory.value = ''; return }
  if (name === item.name) { editingCategory.value = ''; return }
  try { await request(`/v1/${kind}/${item.id}`, 'PATCH', { name }); await loadCategories(); editingCategory.value = '' } catch (cause) { showError(cause) }
}
async function deleteCategory(kind: 'notebooks' | 'tags', item: Category) {
  const key = `${kind}:${item.id}`
  if (pendingCategoryDelete.value !== key) { pendingCategoryDelete.value = key; editingCategory.value = ''; return }
  try {
    await request<void>(`/v1/${kind}/${item.id}`, 'DELETE')
    if (kind === 'notebooks' && filterNotebook.value === item.id) filterNotebook.value = ''
    if (kind === 'tags' && filterTag.value === item.id) filterTag.value = ''
    if (kind === 'notebooks') {
      expandedNotebookIds.value = expandedNotebookIds.value.filter(id => id !== item.id)
      delete sidebarNotesByNotebook.value[item.id]
    }
    if (draft.value?.notebook_id === item.id) draft.value.notebook_id = null
    if (draft.value) draft.value.tag_ids = draft.value.tag_ids.filter(id => id !== item.id)
    pendingCategoryDelete.value = ''
    await Promise.all([loadCategories(), loadNotes(), loadSidebarNotes(), ...(searched.value ? [runSearch()] : [])])
  } catch (cause) { showError(cause) }
}

function toggleCategorySearch(kind: 'notebooks' | 'tags') {
  if (kind === 'notebooks') notebookCreateMenuOpen.value = false
  categorySearchOpen.value = categorySearchOpen.value === kind ? '' : kind
  if (kind === 'notebooks') notebooksSectionOpen.value = true
  else tagsSectionOpen.value = true
  if (categorySearchOpen.value) nextTick(() => categorySearchInput.value?.focus())
  else categorySearch.value[kind] = ''
}

let searchRequestVersion = 0
function clearSearch() {
  searchRequestVersion += 1
  busy.value = false
  searchQuery.value = ''
  results.value = []
  searchNextCursor.value = null
  searched.value = false
}

function changeSearchMode() {
  if (searchQuery.value.trim()) void runSearch()
  else clearSearch()
}

async function runSearch(append = false) {
  const query = searchQuery.value.trim()
  if (!query) {
    results.value = []
    searchNextCursor.value = null
    searched.value = false
    return
  }
  const version = ++searchRequestVersion
  busy.value = true; error.value = ''
  try {
    const params = new URLSearchParams({ limit: '30', updated_desc: String(updatedDesc.value) })
    if (filterNotebook.value) params.set('notebook_id', filterNotebook.value)
    if (filterTag.value) params.set('tag_id', filterTag.value)
    params.set('q', query)
    params.set('q_scope', searchMode.value)
    if (append && searchNextCursor.value) params.set('cursor', searchNextCursor.value)
    const response = await request<{ items: NoteSummary[]; next_cursor: string | null }>(`/v1/notes?${params}`)
    if (version !== searchRequestVersion) return
    results.value = append ? [...results.value, ...response.items] : response.items
    searchNextCursor.value = response.next_cursor
    searched.value = true
  } catch (cause) { if (version === searchRequestVersion) showError(cause) }
  finally { if (version === searchRequestVersion) busy.value = false }
}

function toggleTag(id: string) {
  if (!draft.value) return
  draft.value.tag_ids = draft.value.tag_ids.includes(id) ? draft.value.tag_ids.filter(item => item !== id) : [...draft.value.tag_ids, id]
}

async function refreshIndexStatus() {
  const selected = draft.value
  if (!account.value || !selected?.id || selected.index_status === 'ready' || isDirty.value) return
  try {
    const latest = await request<Note>(`/v1/notes/${selected.id}`)
    if (draft.value?.id !== latest.id || draft.value.version !== latest.version || isDirty.value) return
    draft.value.index_status = latest.index_status
    savedDraft.value = JSON.stringify(draft.value)
    const summary = notes.value.find(item => item.id === latest.id)
    if (summary) summary.index_status = latest.index_status
  } catch { /* The next manual action will show any connection error. */ }
}

function openAssistant() {
  if (editorOpen.value && !confirmLeave()) return
  if (editorOpen.value && isDirty.value) draft.value = draft.value?.id ? JSON.parse(savedDraft.value) as Note : null
  if (view.value !== 'assistant') listOpen.value = true
  editorOpen.value = false; view.value = 'assistant'
  if (!activeConversation.value) {
    if (conversations.value.length) void selectConversation(conversations.value[0].id)
    else void newConversation()
  }
}

function closeEditor() {
  if (!confirmLeave()) return
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  if (isDirty.value) draft.value = draft.value?.id ? JSON.parse(savedDraft.value) as Note : null
  editorOpen.value = false; moreActionsOpen.value = false; editorTagsOpen.value = false
}

function navigate(next: View) {
  profileMenuOpen.value = false
  notebookCreateMenuOpen.value = false
  if (next === 'assistant') { openAssistant(); return }
  if (editorOpen.value && !confirmLeave()) return
  if (editorOpen.value && isDirty.value) draft.value = draft.value?.id ? JSON.parse(savedDraft.value) as Note : null
  view.value = next; editorOpen.value = false; searched.value = false
  if (next === 'notes') { filterNotebook.value = ''; filterTag.value = '' }
  if (next === 'notebooks') { filterNotebook.value = ''; filterTag.value = ''; listOpen.value = true; notebooksSectionOpen.value = true }
}

function showProfileDialog() {
  profileMenuOpen.value = false
  activeSettingsSection.value = 'profile'
  settingsSearch.value = ''
  profileDialog.value = true
}

function handleEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') { profileMenuOpen.value = false; profileDialog.value = false; notebookCreateMenuOpen.value = false; pendingCategoryDelete.value = ''; pendingConversationDelete.value = ''; editingConversationId.value = ''; pendingNoteDelete.value = false; editingCategory.value = ''; newCategoryKind.value = ''; editorTagsOpen.value = false }
}

function selectNotebook(id: string) {
  notebookCreateMenuOpen.value = false
  if (editorOpen.value && !confirmLeave()) return
  if (editorOpen.value && isDirty.value) draft.value = draft.value?.id ? JSON.parse(savedDraft.value) as Note : null
  const wasSelected = view.value === 'notebooks' && filterNotebook.value === id
  filterNotebook.value = id
  if (!id) filterTag.value = ''
  view.value = 'notebooks'; editorOpen.value = false; searched.value = false
  const hasNotes = (notebooks.value.find(item => item.id === id)?.note_count ?? 0) > 0
  if (!hasNotes) return
  const expanded = expandedNotebookIds.value.includes(id)
  if (wasSelected && expanded) expandedNotebookIds.value = expandedNotebookIds.value.filter(item => item !== id)
  else if (!expanded) {
    expandedNotebookIds.value = [...expandedNotebookIds.value, id]
    void loadSidebarNotes().catch(showError)
  }
}

function startNoteDrag(noteId: string, event: DragEvent) {
  if (movingNoteId.value) {
    event.preventDefault()
    return
  }
  if (editorOpen.value && draft.value?.id === noteId && (isDirty.value || saveState.value === 'saving')) {
    event.preventDefault()
    notice.value = '请先保存当前笔记，再移动到笔记本'
    return
  }
  draggedNoteId.value = noteId
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', noteId)
  }
}

function finishNoteDrag() {
  draggedNoteId.value = ''
  dragOverNotebookId.value = ''
}

function dragOverNotebook(id: string, event: DragEvent) {
  if (!draggedNoteId.value) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dragOverNotebookId.value = id
}

function leaveNotebookDrop(event: DragEvent) {
  if (event.relatedTarget instanceof Node && (event.currentTarget as Node).contains(event.relatedTarget)) return
  dragOverNotebookId.value = ''
}

async function dropNoteIntoNotebook(id: string, event: DragEvent) {
  if (!draggedNoteId.value) return
  event.preventDefault()
  const noteId = draggedNoteId.value
  finishNoteDrag()
  if (editorOpen.value && draft.value?.id === noteId && (isDirty.value || saveState.value === 'saving')) {
    notice.value = '请先保存当前笔记，再移动到笔记本'
    return
  }
  movingNoteId.value = noteId
  error.value = ''
  try {
    const current = await request<Note>(`/v1/notes/${noteId}`)
    if (current.notebook_id === id) { notice.value = '笔记已在这个笔记本中'; return }
    const moved = await request<Note>(`/v1/notes/${noteId}`, 'PATCH', { version: current.version, notebook_id: id })
    if (draft.value?.id === noteId) {
      draft.value = moved
      savedDraft.value = JSON.stringify(moved)
      saveState.value = 'saved'
    }
    if (!expandedNotebookIds.value.includes(id)) expandedNotebookIds.value = [...expandedNotebookIds.value, id]
    searched.value = false
    results.value = []
    await Promise.all([loadNotes(), loadCategories(), loadSidebarNotes()])
    notice.value = `已移入${notebooks.value.find(item => item.id === id)?.name ?? '笔记本'}`
  } catch (cause) {
    showError(cause)
    void Promise.all([loadNotes(), loadCategories(), loadSidebarNotes()]).catch(() => {})
  } finally { movingNoteId.value = '' }
}

async function openSidebarNote(note: NoteSummary) {
  await openNote(note.id)
  if (draft.value?.id === note.id) filterNotebook.value = note.notebook_id ?? ''
}

async function loadConversations() {
  const response = await request<{ items: ConversationSummary[] }>('/v1/assistant/conversations')
  conversations.value = response.items.map(item => ({ ...item, messages: [], loaded: false, loading: false }))
  activeConversationId.value = conversations.value[0]?.id ?? ''
  if (activeConversationId.value) await selectConversation(activeConversationId.value)
}

async function selectConversation(id: string) {
  editingConversationId.value = ''
  pendingConversationDelete.value = ''
  activeConversationId.value = id
  const item = conversations.value.find(conversation => conversation.id === id)
  if (!item) return
  const version = ++conversationLoadVersion
  item.loading = true
  try {
    const response = await request<ConversationSummary & { messages: ChatMessage[] }>(`/v1/assistant/conversations/${id}`)
    const target = conversations.value.find(conversation => conversation.id === id)
    if (target) {
      target.title = response.title
      target.updated_at = response.updated_at
      target.messages = response.messages
      target.loaded = true
    }
  } catch (cause) {
    if (version === conversationLoadVersion) showError(cause)
  } finally {
    const target = conversations.value.find(conversation => conversation.id === id)
    if (target) target.loading = false
  }
}

async function newConversation() {
  conversationQuery.value = ''
  editingConversationId.value = ''
  pendingConversationDelete.value = ''
  if (activeConversation.value && activeConversation.value.loaded && !activeConversation.value.messages.length) {
    activeConversationId.value = activeConversation.value.id
    return
  }
  try {
    const created = await request<ConversationSummary>('/v1/assistant/conversations', 'POST')
    conversations.value.unshift({ ...created, messages: [], loaded: true, loading: false })
    activeConversationId.value = created.id
  } catch (cause) { showError(cause) }
}

function startRenameConversation(item: Conversation) {
  editingConversationId.value = item.id
  editingConversationTitle.value = item.title
  pendingConversationDelete.value = ''
  nextTick(() => document.querySelector<HTMLInputElement>('.conversation-rename-input')?.focus())
}

async function renameConversation(item: Conversation) {
  const title = editingConversationTitle.value.trim()
  if (!title) { editingConversationId.value = ''; return }
  if (title === item.title) { editingConversationId.value = ''; return }
  try {
    const updated = await request<ConversationSummary>(`/v1/assistant/conversations/${item.id}`, 'PATCH', { title })
    item.title = updated.title
    item.updated_at = updated.updated_at
    conversations.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    editingConversationId.value = ''
  } catch (cause) { showError(cause) }
}

async function deleteConversation(item: Conversation) {
  if (pendingConversationDelete.value !== item.id) {
    pendingConversationDelete.value = item.id
    editingConversationId.value = ''
    return
  }
  try {
    await request<void>(`/v1/assistant/conversations/${item.id}`, 'DELETE')
    const wasActive = activeConversationId.value === item.id
    conversations.value = conversations.value.filter(conversation => conversation.id !== item.id)
    pendingConversationDelete.value = ''
    if (wasActive) {
      activeConversationId.value = ''
      const next = conversations.value[0]
      if (next) await selectConversation(next.id)
      else await newConversation()
    }
  } catch (cause) { showError(cause) }
}

function toggleConversationSearch() {
  conversationSearchOpen.value = !conversationSearchOpen.value
  if (!conversationSearchOpen.value) conversationQuery.value = ''
}

function handleAnswered(conversationId: string, result: SentMessages) {
  const item = conversations.value.find(conversation => conversation.id === conversationId)
  if (!item) return
  item.title = result.title
  item.updated_at = result.updated_at
  item.loaded = true
  item.messages.push(...result.messages)
  conversations.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

function changeMonth(delta: number) {
  calendarDate.value = new Date(calendarDate.value.getFullYear(), calendarDate.value.getMonth() + delta, 1)
  selectedDay.value = 1
}

function addCalendarEvent() {
  const text = eventInput.value.trim()
  if (!text) return
  calendarEvents.value.push({ id: globalThis.crypto?.randomUUID?.() ?? String(Date.now()), date: selectedDateKey.value, text })
  eventInput.value = ''
}

function addReminder() {
  const text = reminderInput.value.trim()
  if (!text) return
  reminders.value.unshift({ id: globalThis.crypto?.randomUUID?.() ?? String(Date.now()), text, done: false })
  reminderInput.value = ''
}

function openAssistantCitation(citation: { note_id: string; note_version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number }) {
  void openNote(citation.note_id, { ...citation, version: citation.note_version })
}

watch(() => [draft.value?.title, draft.value?.body_md, draft.value?.tag_ids], () => scheduleAutoSave())
watch([filterNotebook, filterTag, updatedDesc], () => { if (account.value) void (searched.value ? runSearch() : loadNotes()).catch(showError) })
onMounted(async () => {
  window.addEventListener('keydown', handleEscape)
  try { account.value = await request<Account>('/v1/auth/me'); await Promise.all([loadCategories(), loadNotes(), loadSidebarNotes(), loadConversations()]); void loadModelConnection().catch(() => { modelConfigured.value = false }) }
  catch { account.value = null }
  finally { booting.value = false; statusTimer = setInterval(() => void refreshIndexStatus(), 5000) }
})
onUnmounted(() => { if (statusTimer) clearInterval(statusTimer); if (autoSaveTimer) clearTimeout(autoSaveTimer); window.removeEventListener('keydown', handleEscape) })
</script>

<template>
  <div v-if="booting" class="loading-screen">正在连接知识库…</div>
  <main v-else-if="!account" class="auth-shell">
    <section class="auth-story" aria-label="个人笔记">
      <img class="auth-artwork" :src="loginArtwork" width="1122" height="1402" alt="自然光下摊开的笔记本与钢笔" fetchpriority="high" />
      <div class="auth-artwork-wash" aria-hidden="true"></div>
      <header class="auth-brand"><span class="auth-monogram" aria-hidden="true">枫</span><span>个人笔记</span></header>
      <div class="auth-story-copy"><h1>给想法一页位置。</h1></div>
    </section>
    <section class="auth-panel" aria-label="账号登录">
      <div class="auth-panel-top"><span>个人笔记</span></div>
      <form class="auth-card" @submit.prevent="submitAuth" :aria-busy="busy">
        <div class="auth-card-heading"><h2>{{ authMode === 'login' ? '欢迎回来' : '创建个人空间' }}</h2></div>
        <label class="auth-field" for="auth-email"><span>邮箱地址</span><input id="auth-email" v-model.trim="email" type="email" autocomplete="email" required placeholder="name@example.com" /></label>
        <label class="auth-field" for="auth-password"><span>密码</span><span class="password-wrap"><input id="auth-password" v-model="password" :type="showPassword ? 'text' : 'password'" :autocomplete="authMode === 'login' ? 'current-password' : 'new-password'" minlength="10" required placeholder="至少 10 个字符" /><button class="password-toggle" type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" :aria-pressed="showPassword" @click="showPassword = !showPassword">{{ showPassword ? '隐藏' : '显示' }}</button></span></label>
        <p v-if="error" class="form-error" role="alert" aria-live="polite">{{ error }}</p>
        <button class="auth-submit" type="submit" :disabled="busy"><span>{{ busy ? authMode === 'login' ? '正在登录…' : '正在创建账号…' : authMode === 'login' ? '登录知识库' : '创建个人空间' }}</span><span v-if="busy" class="submit-spinner" aria-hidden="true"></span></button>
        <div class="auth-switch"><span>{{ authMode === 'login' ? '第一次来这里？' : '已经有账号？' }}</span><button type="button" @click="authMode = authMode === 'login' ? 'register' : 'login'; error = ''">{{ authMode === 'login' ? '创建账号' : '返回登录' }}</button></div>
      </form>
      <div class="auth-panel-foot"></div>
    </section>
  </main>
  <main v-else class="workspace" :class="{ 'with-list': (view === 'notebooks' || view === 'assistant') && listOpen }">
    <aside class="icon-rail" aria-label="主导航">
      <div class="rail-mark" title="个人笔记">枫</div>
      <nav class="rail-nav">
        <button v-for="item in ([['notes','grid','工作台'],['notebooks','book','笔记本'],['assistant','spark','AI 对话'],['calendar','calendar','日历'],['reminders','bell','提醒']] as const)" :key="item[0]" class="rail-button" :class="{ active: view === item[0] }" :aria-label="item[2]" :title="item[2]" @click="navigate(item[0])"><AppIcon :name="item[1]" /></button>
      </nav>
      <div class="rail-foot"><button class="rail-avatar" :title="account.email" aria-label="账户菜单" aria-haspopup="menu" :aria-expanded="profileMenuOpen" @click="profileMenuOpen = !profileMenuOpen">{{ account.email.slice(0, 1).toUpperCase() }}</button></div>
    </aside>

    <div v-if="profileMenuOpen" class="profile-dismiss" @click="profileMenuOpen = false"></div>
    <div v-if="profileMenuOpen" class="profile-menu" role="menu" aria-label="账户菜单">
      <button role="menuitem" @click="showProfileDialog"><AppIcon name="settings" />设置</button>
      <button role="menuitem" @click="profileMenuOpen = false; logout()"><AppIcon name="logout" />退出登录</button>
    </div>

    <Teleport to="body">
      <template v-if="notebookCreateMenuOpen">
        <div class="notebook-create-dismiss" @click="notebookCreateMenuOpen = false"></div>
        <div id="notebook-create-menu" class="notebook-create-menu" role="group" aria-label="新建选项" :style="{ top: `${notebookCreateMenuPosition.top}px`, left: `${notebookCreateMenuPosition.left}px` }">
          <button ref="notebookCreateFirstOption" type="button" @click="createNoteFromNotebookMenu"><AppIcon name="note" /><span>新建笔记</span></button>
          <button type="button" @click="startCreateCategory('notebooks')"><AppIcon name="book" /><span>新建笔记本</span></button>
        </div>
      </template>
    </Teleport>

    <aside v-if="(view === 'notebooks' || view === 'assistant') && listOpen" class="list-pane">
      <template v-if="view === 'notebooks'">
        <div class="taxonomy-section">
          <div class="pane-heading taxonomy-heading"><button class="taxonomy-title" :aria-expanded="notebooksSectionOpen" @click="toggleNotebooksSection"><AppIcon class="taxonomy-chevron" :class="{ expanded: notebooksSectionOpen }" name="chevron" /><h2>笔记本</h2></button><div class="pane-heading-actions"><button class="icon-button" :class="{ selected: !filterNotebook && !filterTag }" title="首页 · 全部笔记" aria-label="首页，全部笔记" :aria-current="!filterNotebook && !filterTag ? 'page' : undefined" @click="selectNotebook('')"><AppIcon name="home" /></button><button class="icon-button" title="搜索笔记本" aria-label="搜索笔记本" :aria-expanded="categorySearchOpen === 'notebooks'" @click="toggleCategorySearch('notebooks')"><AppIcon name="search" /></button><button class="icon-button" title="新建笔记或笔记本" aria-label="新建笔记或笔记本" aria-controls="notebook-create-menu" :aria-expanded="notebookCreateMenuOpen" @click="toggleNotebookCreateMenu"><AppIcon name="plus" /></button></div></div>
          <template v-if="notebooksSectionOpen">
          <input v-if="categorySearchOpen === 'notebooks'" ref="categorySearchInput" v-model="categorySearch.notebooks" class="category-search-input" aria-label="搜索笔记本" placeholder="搜索笔记本" />
          <form v-if="newCategoryKind === 'notebooks'" class="category-create" @submit.prevent="createCategory('notebooks')"><input v-model="newCategoryName" class="category-create-input" maxlength="120" aria-label="新建笔记本名称" placeholder="笔记本名称" /><button class="category-confirm" type="submit" aria-label="确认新建"><AppIcon name="check" /></button><button class="category-cancel" type="button" aria-label="取消新建" @click="newCategoryKind = ''"><AppIcon name="close" /></button></form>
          <div v-for="item in filteredNotebooks" :key="item.id" class="taxonomy-item">
            <div class="pane-row-wrap notebook-row" :class="{ active: filterNotebook === item.id || editingCategory === item.id || pendingCategoryDelete === `notebooks:${item.id}`, 'drop-target': dragOverNotebookId === item.id, 'action-pending': editingCategory === item.id || pendingCategoryDelete === `notebooks:${item.id}` }" @dragover="dragOverNotebook(item.id, $event)" @dragleave="leaveNotebookDrop" @drop="dropNoteIntoNotebook(item.id, $event)">
              <input v-if="editingCategory === item.id" v-model="editingCategoryName" class="category-rename-input" :aria-label="'编辑笔记本名称' + item.name" @keydown.enter.prevent="renameCategory('notebooks', item)" @keydown.esc="editingCategory = ''" />
              <button v-else class="pane-row" :class="{ active: filterNotebook === item.id }" :aria-expanded="(item.note_count ?? 0) > 0 ? expandedNotebookIds.includes(item.id) : undefined" @click="selectNotebook(item.id)"><AppIcon name="book" /><span>{{ item.name }}</span></button>
              <div class="notebook-row-actions">
                <template v-if="editingCategory === item.id"><button class="row-action confirm-edit" aria-label="确认修改" @click="renameCategory('notebooks', item)"><AppIcon name="check" /></button><button class="row-action confirm-cancel" aria-label="取消修改" @click="editingCategory = ''"><AppIcon name="close" /></button></template>
                <template v-else-if="pendingCategoryDelete === `notebooks:${item.id}`"><button class="row-action confirm-delete" aria-label="确认删除" @click="deleteCategory('notebooks', item)"><AppIcon name="check" /></button><button class="row-action confirm-cancel" aria-label="取消删除" @click="pendingCategoryDelete = ''"><AppIcon name="close" /></button></template>
                <template v-else><button class="row-action" :aria-label="'编辑' + item.name" title="编辑" @click="startRenameCategory(item)"><AppIcon name="edit" /></button><button class="row-action" :aria-label="'删除' + item.name" title="删除" @click="deleteCategory('notebooks', item)"><AppIcon name="trash" /></button></template>
              </div>
              <button v-if="(item.note_count ?? 0) > 0" class="notebook-expand" type="button" :aria-label="`${expandedNotebookIds.includes(item.id) ? '收起' : '展开'}${item.name}`" :aria-expanded="expandedNotebookIds.includes(item.id)" @click="selectNotebook(item.id)"><AppIcon class="row-chevron" :class="{ expanded: expandedNotebookIds.includes(item.id) }" name="chevron" /></button>
            </div>
            <div v-if="(item.note_count ?? 0) > 0 && expandedNotebookIds.includes(item.id)" class="sidebar-note-list">
              <button v-for="note in sidebarNotesByNotebook[item.id] || []" :key="note.id" type="button" class="sidebar-note" :class="{ active: editorOpen && draft?.id === note.id, dragging: draggedNoteId === note.id }" draggable="true" @dragstart="startNoteDrag(note.id, $event)" @dragend="finishNoteDrag" @click="openSidebarNote(note)">
                <span class="sidebar-note-title"><AppIcon name="note" /><span>{{ note.title || '无标题笔记' }}</span></span>
                <span v-if="note.tag_ids.length" class="sidebar-note-tags"><span v-for="tagId in note.tag_ids" :key="tagId">#{{ tagNames[tagId] || '标签' }}</span></span>
              </button>
            </div>
          </div>
          <div v-if="unclassifiedNotes.length" class="sidebar-unclassified">
            <div class="sidebar-unclassified-heading">未分类</div>
            <div class="sidebar-note-list">
              <button v-for="note in unclassifiedNotes" :key="note.id" type="button" class="sidebar-note" :class="{ active: editorOpen && draft?.id === note.id, dragging: draggedNoteId === note.id }" draggable="true" @dragstart="startNoteDrag(note.id, $event)" @dragend="finishNoteDrag" @click="openSidebarNote(note)">
                <span class="sidebar-note-title"><AppIcon name="note" /><span>{{ note.title || '无标题笔记' }}</span></span>
                <span v-if="note.tag_ids.length" class="sidebar-note-tags"><span v-for="tagId in note.tag_ids" :key="tagId">#{{ tagNames[tagId] || '标签' }}</span></span>
              </button>
            </div>
          </div>
          <div v-if="!filteredNotebooks.length && !unclassifiedNotes.length && newCategoryKind !== 'notebooks'" class="taxonomy-empty">暂无笔记本或未分类笔记</div>
          </template>
        </div>
        <div class="taxonomy-section tag-section">
          <div class="pane-heading taxonomy-heading"><button class="taxonomy-title" :aria-expanded="tagsSectionOpen" @click="tagsSectionOpen = !tagsSectionOpen"><AppIcon class="taxonomy-chevron" :class="{ expanded: tagsSectionOpen }" name="chevron" /><h2>标签</h2></button><div class="pane-heading-actions"><button class="icon-button" title="搜索标签" aria-label="搜索标签" :aria-expanded="categorySearchOpen === 'tags'" @click="toggleCategorySearch('tags')"><AppIcon name="search" /></button><button class="icon-button" title="新建标签" aria-label="新建标签" @click="startCreateCategory('tags')"><AppIcon name="plus" /></button></div></div>
          <template v-if="tagsSectionOpen">
          <input v-if="categorySearchOpen === 'tags'" ref="categorySearchInput" v-model="categorySearch.tags" class="category-search-input" aria-label="搜索标签" placeholder="搜索标签" />
          <form v-if="newCategoryKind === 'tags'" class="category-create" @submit.prevent="createCategory('tags')"><input v-model="newCategoryName" class="category-create-input" maxlength="80" aria-label="新建标签名称" placeholder="标签名称" /><button class="category-confirm" type="submit" aria-label="确认新建"><AppIcon name="check" /></button><button class="category-cancel" type="button" aria-label="取消新建" @click="newCategoryKind = ''"><AppIcon name="close" /></button></form>
          <div v-for="item in filteredTags" :key="item.id" class="pane-row-wrap" :class="{ active: filterTag === item.id || editingCategory === item.id || pendingCategoryDelete === `tags:${item.id}` }">
            <input v-if="editingCategory === item.id" v-model="editingCategoryName" class="category-rename-input" :aria-label="'编辑标签名称' + item.name" @keydown.enter.prevent="renameCategory('tags', item)" @keydown.esc="editingCategory = ''" />
            <button v-else class="pane-row" :class="{ active: filterTag === item.id }" @click="filterTag = filterTag === item.id ? '' : item.id"><span># {{ item.name }}</span></button>
            <template v-if="editingCategory === item.id"><button class="row-action confirm-edit" aria-label="确认修改" @click="renameCategory('tags', item)"><AppIcon name="check" /></button><button class="row-action confirm-cancel" aria-label="取消修改" @click="editingCategory = ''"><AppIcon name="close" /></button></template>
            <template v-else-if="pendingCategoryDelete === `tags:${item.id}`"><button class="row-action confirm-delete" aria-label="确认删除" @click="deleteCategory('tags', item)"><AppIcon name="check" /></button><button class="row-action confirm-cancel" aria-label="取消删除" @click="pendingCategoryDelete = ''"><AppIcon name="close" /></button></template>
            <template v-else-if="filterTag === item.id"><button class="row-action" :aria-label="'编辑' + item.name" title="编辑" @click="startRenameCategory(item)"><AppIcon name="edit" /></button><button class="row-action" :aria-label="'删除' + item.name" title="删除" @click="deleteCategory('tags', item)"><AppIcon name="trash" /></button></template>
          </div>
          <div v-if="!filteredTags.length && newCategoryKind !== 'tags'" class="taxonomy-empty">暂无标签</div>
          </template>
        </div>
      </template>
      <template v-else>
        <div class="pane-heading"><h2>对话</h2><div class="pane-heading-actions"><button class="icon-button" title="新建对话" aria-label="新建对话" @click="newConversation"><AppIcon name="plus" /></button><button class="icon-button" title="搜索对话" aria-label="搜索对话" :aria-expanded="conversationSearchOpen" @click="toggleConversationSearch"><AppIcon name="search" /></button></div></div>
        <input v-if="conversationSearchOpen" v-model="conversationQuery" class="conversation-search" aria-label="搜索会话" placeholder="搜索会话" />
        <div class="conversation-list">
          <div v-for="item in filteredConversations" :key="item.id" class="pane-row-wrap conversation-item" :class="{ active: activeConversationId === item.id || editingConversationId === item.id || pendingConversationDelete === item.id }">
            <input v-if="editingConversationId === item.id" v-model="editingConversationTitle" class="conversation-rename-input" :aria-label="'编辑对话标题' + item.title" @keydown.enter.prevent="renameConversation(item)" @keydown.esc="editingConversationId = ''" />
            <button v-else class="pane-row conversation-row" :class="{ active: activeConversationId === item.id }" @click="selectConversation(item.id)"><AppIcon name="spark" /><span>{{ item.title }}</span></button>
            <template v-if="editingConversationId === item.id"><button class="row-action confirm-edit" aria-label="确认修改" title="保存" @click="renameConversation(item)"><AppIcon name="check" /></button><button class="row-action confirm-cancel" aria-label="取消修改" title="取消" @click="editingConversationId = ''"><AppIcon name="close" /></button></template>
            <template v-else-if="pendingConversationDelete === item.id"><button class="row-action confirm-delete" aria-label="确认删除" title="确认删除" @click="deleteConversation(item)"><AppIcon name="check" /></button><button class="row-action confirm-cancel" aria-label="取消删除" title="取消" @click="pendingConversationDelete = ''"><AppIcon name="close" /></button></template>
            <template v-else><button class="row-action" :aria-label="'编辑' + item.title" title="编辑" @click="startRenameConversation(item)"><AppIcon name="edit" /></button><button class="row-action" :aria-label="'删除' + item.title" title="删除" @click="deleteConversation(item)"><AppIcon name="trash" /></button></template>
          </div>
        </div>
      </template>
    </aside>

    <button v-if="view === 'notebooks' || view === 'assistant'" class="list-boundary-toggle" :class="{ open: listOpen }" :aria-label="listOpen ? '折叠列表' : '展开列表'" :title="listOpen ? '折叠列表' : '展开列表'" @click="listOpen = !listOpen"><AppIcon name="panel" /></button>

    <section class="main-pane">
      <template v-if="editorOpen && (view === 'notes' || view === 'notebooks') && draft">
        <div class="note-editor">
          <header class="note-editor-header">
            <div class="note-editor-identity">
              <button class="icon-button editor-back" title="返回" aria-label="返回" @click="closeEditor"><AppIcon name="arrow-left" /></button>
              <span class="editor-file-icon"><AppIcon name="note" /></span>
              <span class="editor-file-name">{{ draft.title || '无标题笔记' }}</span>
              <span class="editor-save-state" :class="`state-${saveState}`" :title="saveState === 'error' ? error : undefined" aria-live="polite"><AppIcon :name="saveState === 'saved' ? 'check' : saveState === 'error' ? 'close' : saveState === 'saving' ? 'loader' : 'clock'" /><span>{{ saveState === 'saving' ? '保存中' : saveState === 'error' ? '保存失败' : saveState === 'unsaved' ? '未保存' : '已保存' }}</span></span>
              <span class="editor-date">{{ draft.id ? formatDate(draft.updated_at) : '新的记录' }}</span>
            </div>
            <div class="note-editor-actions">
              <div class="editor-tag-wrap">
                <button class="editor-tag-trigger" :class="{ active: editorTagsOpen, 'has-tags': draft.tag_ids.length }" :aria-label="editorTagsOpen ? '关闭标签选择' : '添加标签'" title="标签" :aria-expanded="editorTagsOpen" @click="editorTagsOpen = !editorTagsOpen"><AppIcon name="tag" /></button>
                <button v-if="editorTagsOpen" class="editor-tag-dismiss" aria-label="关闭标签选择" @click="editorTagsOpen = false"></button>
                <div v-if="editorTagsOpen" class="editor-tag-menu" role="group" aria-label="为笔记添加标签">
                  <button v-for="tag in tags" :key="tag.id" class="editor-tag-option" :class="{ selected: draft.tag_ids.includes(tag.id) }" role="checkbox" :aria-checked="draft.tag_ids.includes(tag.id)" @click="toggleTag(tag.id)"><span class="editor-tag-check"><AppIcon v-if="draft.tag_ids.includes(tag.id)" name="check" /></span><span>{{ tag.name }}</span></button>
                  <span v-if="!tags.length" class="editor-tag-empty">暂无标签</span>
                </div>
              </div>
              <button class="preview-toggle" :class="{ active: editorMode === 'preview' }" :aria-label="editorMode === 'preview' ? '返回编辑' : '预览'" :title="editorMode === 'preview' ? '返回编辑' : '预览'" :aria-pressed="editorMode === 'preview'" @click="editorMode = editorMode === 'write' ? 'preview' : 'write'"><AppIcon name="eye" /></button>
              <div class="editor-more-wrap">
                <button class="icon-button" title="更多操作" aria-label="更多操作" :aria-expanded="moreActionsOpen" @click="moreActionsOpen = !moreActionsOpen"><AppIcon name="more" /></button>
                <div v-if="moreActionsOpen" class="editor-more-menu">
                  <button :disabled="!draft.id" @click="exportCurrentNote(); moreActionsOpen = false"><AppIcon name="export" />导出 Markdown</button>
                  <template v-if="draft.id">
                    <button v-if="!pendingNoteDelete" class="menu-danger" @click="pendingNoteDelete = true"><AppIcon name="trash" />删除笔记</button>
                    <template v-else><span class="menu-confirm-copy">确定删除？</span><button class="menu-danger" @click="deleteNote"><AppIcon name="check" />确认删除</button><button @click="pendingNoteDelete = false"><AppIcon name="close" />取消</button></template>
                  </template>
                </div>
              </div>
            </div>
          </header>
          <div v-if="editorMode === 'write'" class="editor-toolbar-wrap">
            <div class="editor-toolbar" role="toolbar" aria-label="文本格式">
              <button class="editor-tool" title="撤销" aria-label="撤销" @mousedown.prevent @click="applyEditorCommand('undo')"><AppIcon name="undo" /></button>
              <button class="editor-tool" title="重做" aria-label="重做" @mousedown.prevent @click="applyEditorCommand('redo')"><AppIcon name="redo" /></button>
              <span class="editor-tool-divider"></span>
              <button class="editor-tool heading-tool" title="标题" aria-label="标题" @mousedown.prevent @click="applyEditorCommand('heading')"><AppIcon name="heading" /></button>
              <button class="editor-tool format-bold" title="加粗" aria-label="加粗" @mousedown.prevent @click="applyEditorCommand('bold')">B</button>
              <button class="editor-tool format-italic" title="斜体" aria-label="斜体" @mousedown.prevent @click="applyEditorCommand('italic')">I</button>
              <button class="editor-tool format-underline" title="下划线" aria-label="下划线" @mousedown.prevent @click="applyEditorCommand('underline')">U</button>
              <span class="editor-tool-divider"></span>
              <button class="editor-tool" title="项目符号列表" aria-label="项目符号列表" @mousedown.prevent @click="applyEditorCommand('list')"><AppIcon name="listFormat" /></button>
              <button class="editor-tool" title="待办清单" aria-label="待办清单" @mousedown.prevent @click="applyEditorCommand('checklist')"><AppIcon name="checklist" /></button>
              <span class="editor-tool-divider"></span>
              <button class="editor-tool" title="插入链接" aria-label="插入链接" @mousedown.prevent @click="applyEditorCommand('link')"><AppIcon name="link" /></button>
              <button class="editor-tool" title="插入图片" aria-label="插入图片" @mousedown.prevent @click="applyEditorCommand('image')"><AppIcon name="image" /></button>
              <button class="editor-tool" title="引用" aria-label="引用" @mousedown.prevent @click="applyEditorCommand('quote')"><AppIcon name="quote" /></button>
              <button class="editor-tool" title="代码块" aria-label="代码块" @mousedown.prevent @click="applyEditorCommand('code')"><AppIcon name="code" /></button>
            </div>
          </div>
          <main class="editor-writing-area">
            <div class="editor-writing-page">
              <input ref="titleInput" v-model="draft.title" class="writing-title" maxlength="240" placeholder="无标题笔记" aria-label="笔记标题" />
              <textarea v-show="editorMode === 'write'" ref="bodyInput" v-model="draft.body_md" class="writing-body" maxlength="100000" placeholder="开始写作…" aria-label="笔记内容" />
              <article v-if="editorMode === 'preview'" class="markdown-preview" v-html="previewHtml" />
            </div>
          </main>
        </div>
      </template>

      <template v-else-if="view === 'notes'">
        <header class="page-head"><h1>工作台</h1><button class="accent-button" @click="createDraft"><AppIcon name="plus" /> 新建笔记</button></header>
        <div class="content-width workbench-content">
          <div class="workbench-grid">
            <button class="workbench-card workbench-card-primary" @click="navigate('notebooks')"><span class="workbench-icon"><AppIcon name="book" /></span><strong>笔记本</strong><AppIcon class="workbench-arrow" name="arrow" /></button>
            <button class="workbench-card" @click="navigate('assistant')"><span class="workbench-icon"><AppIcon name="spark" /></span><strong>AI 对话</strong><AppIcon class="workbench-arrow" name="arrow" /></button>
            <button class="workbench-card" @click="navigate('calendar')"><span class="workbench-icon"><AppIcon name="calendar" /></span><strong>日历</strong><AppIcon class="workbench-arrow" name="arrow" /></button>
            <button class="workbench-card" @click="navigate('reminders')"><span class="workbench-icon"><AppIcon name="bell" /></span><strong>提醒</strong><AppIcon class="workbench-arrow" name="arrow" /></button>
          </div>
          <section v-if="notes[0]" class="workbench-recent"><h2>继续写作</h2><button class="recent-note" @click="openNote(notes[0].id)"><span><strong>{{ notes[0].title || '无标题笔记' }}</strong><small>{{ formatDate(notes[0].updated_at) }}</small></span><AppIcon name="arrow" /></button></section>
        </div>
      </template>

      <template v-else-if="view === 'notebooks'">
        <header class="page-head"><h1>{{ notebooks.find(item => item.id === filterNotebook)?.name || (!filterTag ? '全部笔记' : '笔记') }}</h1><div class="page-head-actions"><button class="import-button" type="button" disabled aria-label="上传文件，暂未开放"><AppIcon name="upload" /><span>上传文件</span><small>暂未开放</small></button><button class="import-button" type="button" disabled aria-label="识别外部链接，AI 总结生成笔记草稿，暂未开放"><AppIcon name="link" /><span>识别外部链接</span><small>暂未开放</small></button><button class="accent-button" @click="createDraft"><AppIcon name="plus" /> 新建笔记</button></div></header>
        <div class="content-width notebook-content">
          <div class="notebook-toolbar">
            <div class="notebook-search-controls">
              <select v-model="searchMode" class="note-search-scope" aria-label="笔记搜索范围" @change="changeSearchMode"><option value="all">全部</option><option value="title">标题</option><option value="tag">标签</option></select>
              <form class="note-search-box" role="search" @submit.prevent="runSearch()"><button type="submit" aria-label="执行搜索"><AppIcon name="search" /></button><input v-model="searchQuery" :aria-label="searchMode === 'tag' ? '按标签名称搜索笔记' : searchMode === 'title' ? '按标题搜索笔记' : '搜索笔记标题或标签'" :placeholder="searchMode === 'tag' ? '输入标签名称' : searchMode === 'title' ? '搜索笔记标题' : '搜索标题或标签'" /></form>
            </div>
            <div class="notebook-view-actions"><button class="icon-button" :class="{ selected: cardLayout === 'grid' }" title="网格视图" aria-label="网格视图" @click="cardLayout = 'grid'"><AppIcon name="grid" /></button><button class="icon-button" :class="{ selected: cardLayout === 'list' }" title="列表视图" aria-label="列表视图" @click="cardLayout = 'list'"><AppIcon name="list" /></button><button class="icon-button" title="导出全部" aria-label="导出全部" @click="exportAllNotes"><AppIcon name="export" /></button><button class="quiet-button" @click="updatedDesc = !updatedDesc">{{ updatedDesc ? '最近更新 ↓' : '最早更新 ↑' }}</button></div>
          </div>
          <div v-if="searched" class="search-caption"><span>搜索结果 · 已显示 {{ results.length }} 条</span><button @click="clearSearch">清除搜索</button></div>
          <div class="note-grid" :class="{ 'as-list': cardLayout === 'list', 'empty-note-grid': !visibleNotes.length }">
            <button v-for="note in visibleNotes" :key="note.id" class="note-card" :class="{ dragging: draggedNoteId === note.id }" draggable="true" @dragstart="startNoteDrag(note.id, $event)" @dragend="finishNoteDrag" @click="openNote(note.id)">
              <span class="note-card-heading"><span class="note-card-symbol"><AppIcon name="note" /></span><strong :title="note.title">{{ note.title || '无标题笔记' }}</strong></span>
              <span class="note-card-excerpt" :class="{ empty: !note.excerpt }" :title="note.excerpt">{{ note.excerpt || '暂无正文' }}</span>
              <span class="note-card-meta"><span class="note-card-notebook" :title="notebooks.find(item => item.id === note.notebook_id)?.name || '未分类'">{{ notebooks.find(item => item.id === note.notebook_id)?.name || '未分类' }}</span><span v-for="tagId in note.tag_ids.slice(0, 2)" :key="tagId" class="note-card-tag" :title="tagNames[tagId]">#{{ tagNames[tagId] || '标签' }}</span><span v-if="note.tag_ids.length > 2" class="note-card-tag-more" :title="note.tag_ids.slice(2).map(tagId => tagNames[tagId] || '标签').join('、')">+{{ note.tag_ids.length - 2 }}</span><time :datetime="note.updated_at">{{ formatDate(note.updated_at) }}</time></span>
            </button>
            <div v-if="!visibleNotes.length" class="empty-state">{{ searched ? '没有匹配的笔记，试试其他标题或标签' : '暂无笔记' }}</div>
          </div>
          <div v-if="(searched ? searchNextCursor : nextCursor)" class="list-end"><button class="quiet-button" :disabled="busy" @click="searched ? runSearch(true) : loadNotes(true)">加载更多</button></div>
        </div>
      </template>

      <template v-else-if="view === 'assistant'"><div class="assistant-page-head"><h1>AI 对话</h1></div><AssistantPanel :key="activeConversationId" :conversation-id="activeConversationId" :messages="activeConversation?.messages || []" :loading="activeConversation?.loading || false" :model-name="currentModelName" :model-configured="modelConfigured" @answered="handleAnswered" @open-citation="openAssistantCitation" /></template>

      <template v-else-if="view === 'calendar'">
        <header class="page-head"><h1>日历</h1></header>
        <div class="content-width calendar-content"><div class="calendar-card">
          <div class="calendar-toolbar"><h2>{{ calendarDate.getFullYear() }} 年 {{ calendarDate.getMonth() + 1 }} 月</h2><div><button class="icon-button" aria-label="上个月" @click="changeMonth(-1)">‹</button><button class="icon-button" aria-label="回到本月" @click="calendarDate = new Date(); selectedDay = new Date().getDate()">今</button><button class="icon-button" aria-label="下个月" @click="changeMonth(1)">›</button></div></div>
          <div class="calendar-grid"><span v-for="day in ['日','一','二','三','四','五','六']" :key="day" class="week-day">{{ day }}</span><button v-for="(day, index) in calendarDays" :key="index" class="calendar-day" :class="{ today: day === new Date().getDate() && calendarDate.getMonth() === new Date().getMonth() && calendarDate.getFullYear() === new Date().getFullYear(), selected: day === selectedDay }" :disabled="!day" @click="selectedDay = day || 1">{{ day }}</button></div>
        </div><div class="event-panel"><h2>{{ calendarDate.getMonth() + 1 }} 月 {{ selectedDay }} 日</h2><form class="reminder-add" @submit.prevent="addCalendarEvent"><input v-model="eventInput" maxlength="100" placeholder="添加日程" aria-label="添加日程" /><button class="accent-button" type="submit"><AppIcon name="plus" /> 添加</button></form><div v-for="item in selectedEvents" :key="item.id" class="reminder-row"><span>{{ item.text }}</span><button class="icon-button" :aria-label="'删除' + item.text" @click="calendarEvents = calendarEvents.filter(row => row.id !== item.id)"><AppIcon name="trash" /></button></div></div></div>
      </template>

      <template v-else><header class="page-head"><h1>提醒</h1></header><div class="content-width reminders-content"><form class="reminder-add" @submit.prevent="addReminder"><input v-model="reminderInput" maxlength="100" placeholder="添加提醒" aria-label="添加提醒" /><button class="accent-button" type="submit"><AppIcon name="plus" /> 添加</button></form><div class="reminder-list"><div v-for="item in reminders" :key="item.id" class="reminder-row"><label><input v-model="item.done" type="checkbox" /><span :class="{ done: item.done }">{{ item.text }}</span></label><button class="icon-button" :aria-label="'删除' + item.text" @click="reminders = reminders.filter(row => row.id !== item.id)"><AppIcon name="trash" /></button></div><div v-if="!reminders.length" class="empty-state">暂无提醒</div></div></div></template>
    </section>
    <div v-if="profileDialog" class="profile-dialog-backdrop settings-screen" @click.self="profileDialog = false">
      <section class="profile-dialog settings-window" role="dialog" aria-modal="true" aria-label="设置">
        <aside class="settings-sidebar">
          <h1>设置</h1>
          <label class="settings-search"><AppIcon name="search" /><input v-model="settingsSearch" type="search" placeholder="搜索" aria-label="搜索设置" /></label>
          <nav class="settings-nav" aria-label="设置分类">
            <template v-for="group in ['个人', '集成']" :key="group">
              <h2 v-if="visibleSettingsItems.some(item => item.group === group)" class="settings-nav-group">{{ group }}</h2>
              <button v-for="item in visibleSettingsItems.filter(item => item.group === group)" :key="item.id" :class="{ active: activeSettingsSection === item.id }" :aria-current="activeSettingsSection === item.id ? 'page' : undefined" @click="activeSettingsSection = item.id">
                <AppIcon :name="item.id === 'profile' ? 'home' : 'spark'" /><span>{{ item.name }}</span>
              </button>
            </template>
            <p v-if="!visibleSettingsItems.length" class="settings-no-results">没有匹配的设置</p>
          </nav>
        </aside>
        <main class="settings-content">
          <button class="settings-close icon-button" aria-label="关闭设置" @click="profileDialog = false"><AppIcon name="close" /></button>
          <section v-if="activeSettingsSection === 'profile'" class="settings-section">
            <h2 class="settings-page-title">个人信息</h2>
            <div class="settings-section-heading"><h3>账户</h3></div>
            <div class="settings-card">
              <div class="profile-setting-row"><div><strong>邮箱</strong><small>当前登录账号</small></div><span class="settings-value">{{ account?.email }}</span></div>
            </div>
          </section>
          <section v-else class="settings-section">
            <h2 class="settings-page-title">模型配置</h2>
            <div class="settings-section-heading"><h3>AI 连接</h3></div>
            <div class="settings-card model-settings-card">
              <p class="settings-card-description">连接模型后可使用笔记分析与分类建议；AI 对话的笔记检索无需配置模型。</p>
              <ModelConnectionSettings @status="modelConfigured = $event; void loadModelConnection()" />
            </div>
          </section>
        </main>
      </section>
    </div>
    <div v-if="error || notice" class="toast" :class="{ error: !!error }" role="status" @click="error = ''; notice = ''">{{ error || notice }} <span>×</span></div>
  </main>
</template>
