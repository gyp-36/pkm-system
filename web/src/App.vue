<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import AssistantPanel from './AssistantPanel.vue'
import AppIcon from './AppIcon.vue'
import FileTypeIcon from './FileTypeIcon.vue'
import ModelConnectionSettings from './ModelConnectionSettings.vue'
import loginArtwork from './assets/login-still-life.jpg'
import OfficeNoteEditor from './OfficeNoteEditor.vue'
import ImageNoteEditor from './ImageNoteEditor.vue'
import MarkdownImagePicker from './MarkdownImagePicker.vue'
import NoteReferencePicker from './NoteReferencePicker.vue'
import UploadPanel from './UploadPanel.vue'
import LinkDraftWorkspace from './LinkDraftWorkspace.vue'
import ConfirmationDialog from './ConfirmationDialog.vue'
import ReminderDialog from './ReminderDialog.vue'
import WeeklyReportsPage from './WeeklyReportsPage.vue'
import WorkbenchHome from './WorkbenchHome.vue'
import type { ReportKind, WorkbenchDigest } from './workbench'
import { askForConfirmation, askForInput } from './confirmation'

type Account = { id: string; email: string }
type Category = { id: string; name: string; note_count?: number }
type NoteTemplate = { id: string; name: string; title: string; body_md: string; created_at?: string; updated_at?: string }
type NoteFile = { filename: string; extension: string; media_type: string; size_bytes: number; file_version: number; sha256: string }
type NoteSummary = { id: string; title: string; excerpt: string; notebook_id: string | null; tag_ids: string[]; version: number; index_status: string; updated_at: string; created_at: string; content_kind?: string; file?: NoteFile | null; extraction_status?: string; source_url?: string | null }
type ArchivedNote = NoteSummary & { deleted_at: string; purge_at: string; days_remaining: number }
type Note = NoteSummary & { body_md: string; original_files?: { filename: string; extension: string; file_version: number }[]; digest_sources_changed?: number }
type LinkDraft = { id: string; title: string; source_url: string; snapshot_text: string; body_md: string; fetch_status: string; fetch_error: string | null; status: string; notebook_id: string | null }
type Position = { note_id: string; version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number; location?: Record<string, string | number> | null }
type Citation = { note_id: string; note_version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number }
type SearchHit = { note_id: string; title: string; notebook_id: string | null; version: number; source_field: 'title' | 'body'; start_offset: number; end_offset: number; snippet: string; updated_at: string; match_source: 'keyword' | 'semantic' | 'both'; score: number; content_kind?: string; location?: Record<string, string | number> | null }
type UserMessage = { id: string; role: 'user'; content: { text: string }; created_at: string }
type AssistantCitation = { citation_id: string; note_id: string; note_version: number; title: string; source_field: 'title' | 'body'; start_offset: number; end_offset: number; quote: string }
type AssistantMessage = { id: string; role: 'assistant'; content: { answer: string; citations: AssistantCitation[]; semantic_status: 'ready' | 'unavailable' | 'not_requested'; answer_source?: 'knowledge_base' | 'mixed' | 'model_knowledge' } | { items: SearchHit[]; semantic_status: 'ready' | 'unavailable' }; created_at: string }
type ChatMessage = UserMessage | AssistantMessage
type Conversation = { id: string; title: string; created_at: string; updated_at: string; messages: ChatMessage[]; loaded: boolean; loading: boolean }
type ConversationSummary = Pick<Conversation, 'id' | 'title' | 'created_at' | 'updated_at'>
type SentMessages = ConversationSummary & { messages: [UserMessage, AssistantMessage] }
type View = 'notes' | 'notebooks' | 'assistant' | 'calendar' | 'weekly' | 'archive'
type AppRoute = {
  view: View
  notebookId?: string
  tagId?: string
  noteId?: string
  linkDraftId?: string
  newNote?: boolean
  searchQuery?: string
  searchMode?: 'all' | 'title' | 'tag'
  conversationId?: string
  settings?: SettingsSection
  upload?: boolean
  calendarMonth?: string
  selectedDay?: number
  listOpen?: boolean
  cardLayout?: 'grid' | 'list'
  editorMode?: 'write' | 'preview'
  updatedDesc?: boolean
}
type SettingsSection = 'profile' | 'model'
type Reminder = { id: string; note_id: string | null; note_title: string | null; text: string; due_at: string; status: 'open' | 'done' }
type WorkbenchOverview = { reminders: Reminder[]; latest_daily: WorkbenchDigest | null; latest_weekly: WorkbenchDigest | null; archive: ArchivedNote[]; recent_note: NoteSummary | null }

const account = ref<Account | null>(null)
const mainPane = ref<HTMLElement | null>(null)
const authMode = ref<'login' | 'register'>('login')
const email = ref('')
const password = ref('')
const uploadPanelOpen = ref(false)
const templatePickerOpen = ref(false)
const templateImportInput = ref<HTMLInputElement | null>(null)
const templateImporting = ref(false)
const customTemplates = ref<NoteTemplate[]>([])
const templateTab = ref<'preset' | 'mine'>('preset')
const selectedTemplate = ref<NoteTemplate | null>(null)
const customTemplatePage = ref(1)
const fileBusy = ref(false)
const linkDrafts = ref<LinkDraft[]>([])
const showPassword = ref(false)
const busy = ref(false)
const booting = ref(true)
const error = ref('')
const notice = ref('')
const notebooks = ref<Category[]>([])
const tags = ref<Category[]>([])
const notes = ref<NoteSummary[]>([])
const archivedNotes = ref<ArchivedNote[]>([])
const archiveNextCursor = ref<string | null>(null)
const selectedArchiveIds = ref<string[]>([])
const archiveBusy = ref(false)
const sidebarNotesByNotebook = ref<Record<string, NoteSummary[]>>({})
const unclassifiedNotes = ref<NoteSummary[]>([])
const expandedNotebookIds = ref<string[]>([])
const draggedNoteId = ref('')
const dragOverNotebookId = ref('')
const movingNoteId = ref('')
const selectingNotes = ref(false)
const selectedNoteIds = ref<string[]>([])
const notesDeleting = ref(false)
const nextCursor = ref<string | null>(null)
const draft = ref<Note | null>(null)
const activeLinkDraft = ref<LinkDraft | null>(null)
const savedLinkDraft = ref('')
const linkDraftDirty = computed(() => activeLinkDraft.value !== null && JSON.stringify({ title: activeLinkDraft.value.title, body_md: activeLinkDraft.value.body_md }) !== savedLinkDraft.value)
const savedDraft = ref('')
const editorMode = ref<'write' | 'preview'>('write')
const saveState = ref<'saved' | 'saving' | 'unsaved' | 'error'>('saved')
const editorTagsOpen = ref(false)
const bodyInput = ref<HTMLTextAreaElement | null>(null)
const bodyOverlayScrollTop = ref(0)
const bodyOverlayWidth = ref(0)
const imagePickerOpen = ref(false)
const imageInsertionRange = ref({ start: 0, end: 0, noteId: '' })
const noteReferencePickerOpen = ref(false)
const noteReferenceInsertionRange = ref({ start: 0, end: 0, noteId: '', bodyScrollTop: 0, areaScrollTop: 0, pageScrollY: 0 })
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
const calendarDate = ref(new Date())
const selectedDay = ref(new Date().getDate())
const calendarDayPanelOpen = ref(false)
const calendarStatusFilter = ref<'all' | 'open' | 'done'>('all')
const reminders = ref<Reminder[]>([])
const calendarReminders = ref<Reminder[]>([])
const reminderDialog = ref<{ initialDate: string; fixedNoteId: string | null; fixedNoteTitle: string | null } | null>(null)
const focusedReminderId = ref<string | null>(null)
const workbenchOverview = ref<WorkbenchOverview>({ reminders: [], latest_daily: null, latest_weekly: null, archive: [], recent_note: null })
const workbenchLoading = ref(false)
const workbenchLoaded = ref(false)
const workbenchError = ref('')
const workbenchSearch = ref('')
const digestHistoryKind = ref<ReportKind | 'all'>('all')
const completingWorkbenchReminders = ref<string[]>([])
const focusedArchiveId = ref<string | null>(null)
let workbenchLoadVersion = 0
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
const filteredNotebooks = computed(() => notebooks.value.filter(item => item.name.toLocaleLowerCase().includes(categorySearch.value.notebooks.trim().toLocaleLowerCase())))
const filteredTags = computed(() => tags.value.filter(item => item.name.toLocaleLowerCase().includes(categorySearch.value.tags.trim().toLocaleLowerCase())))
const tagNames = computed<Record<string, string>>(() => Object.fromEntries(tags.value.map(item => [item.id, item.name])))
const visibleNotes = computed(() => searched.value ? results.value : notes.value)
const visibleSelectedNoteIds = computed(() => selectedNoteIds.value.filter(id => visibleNotes.value.some(note => note.id === id)))
const profileMenuOpen = ref(false)
const profileDialog = ref(false)
const activeSettingsSection = ref<SettingsSection>('profile')
const assistantTraceViewEnabled = ref(false)
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
const selectedDateKey = computed(() => `${calendarDate.value.getFullYear()}-${String(calendarDate.value.getMonth() + 1).padStart(2, '0')}-${String(selectedDay.value).padStart(2, '0')}`)
const selectedEvents = computed(() => calendarReminders.value.filter(item => localDateKey(item.due_at) === selectedDateKey.value))
const selectedOpenEvents = computed(() => selectedEvents.value.filter(item => item.status === 'open'))
const selectedDoneEvents = computed(() => selectedEvents.value.filter(item => item.status === 'done'))
const calendarEventsByDay = computed(() => calendarReminders.value.reduce<Record<string, Reminder[]>>((days, item) => { const key = localDateKey(item.due_at); (days[key] ||= []).push(item); return days }, {}))
const calendarDayCounts = computed(() => Object.fromEntries(Object.entries(calendarEventsByDay.value).map(([key, items]) => [key, items.length])))
const filteredSelectedEvents = computed(() => calendarStatusFilter.value === 'all' ? selectedEvents.value : selectedEvents.value.filter(item => item.status === calendarStatusFilter.value))
const selectedWeekday = computed(() => new Date(`${selectedDateKey.value}T00:00:00+08:00`).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', weekday: 'long' }))
const todayOpenCount = computed(() => reminders.value.filter(item => localDateKey(item.due_at) === localDateKey(new Date().toISOString())).length)
const weekDueCount = computed(() => reminders.value.filter(item => { const due = new Date(item.due_at).getTime(); return due >= Date.now() && due < Date.now() + 7 * 24 * 60 * 60 * 1000 }).length)
const monthDoneCount = computed(() => calendarReminders.value.filter(item => item.status === 'done').length)
const upcomingReminders = computed(() => reminders.value.filter(item => new Date(item.due_at).getTime() >= Date.now()).sort((a, b) => a.due_at.localeCompare(b.due_at)))
const customTemplatePageCount = computed(() => Math.max(1, Math.ceil(customTemplates.value.length / 9)))
const pagedCustomTemplates = computed(() => customTemplates.value.slice((customTemplatePage.value - 1) * 9, customTemplatePage.value * 9))
const selectedTemplatePreviewHtml = computed(() => selectedTemplate.value
  ? DOMPurify.sanitize(marked.parse(selectedTemplate.value.body_md || '') as string, { FORBID_TAGS: ['iframe'] })
  : '')
let statusTimer: ReturnType<typeof setInterval> | undefined
let reminderTimer: ReturnType<typeof setInterval> | undefined
let calendarLoadVersion = 0
let autoSaveTimer: ReturnType<typeof setTimeout> | undefined
let routeReady = false
let restoringRoute = false
let popstateVersion = 0
let routeRestoreVersion = 0
let currentAppHistoryIndex = 0
let bodyInputResizeObserver: ResizeObserver | null = null
const noteReferenceHref = /^#\/notes\?note=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i
const noteReferenceMarkdown = /\[((?:\\.|[^\]\\\r\n])*)\]\(#\/notes\?note=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)/gi

const editableBodyParts = computed(() => {
  const body = draft.value?.body_md || ''
  const parts: { text: string; noteId?: string }[] = []
  let previousEnd = 0
  for (const match of body.matchAll(noteReferenceMarkdown)) {
    const start = match.index
    if (start > previousEnd) parts.push({ text: body.slice(previousEnd, start) })
    parts.push({ text: match[0], noteId: match[2] })
    previousEnd = start + match[0].length
  }
  if (previousEnd < body.length) parts.push({ text: body.slice(previousEnd) })
  return parts
})
const hasEditableNoteReferences = computed(() => editableBodyParts.value.some(part => Boolean(part.noteId)))

function syncBodyOverlay() {
  const input = bodyInput.value
  if (!input) return
  bodyOverlayScrollTop.value = input.scrollTop
  bodyOverlayWidth.value = input.clientWidth
}

watch(bodyInput, input => {
  bodyInputResizeObserver?.disconnect()
  if (!input) return
  bodyInputResizeObserver = new ResizeObserver(syncBodyOverlay)
  bodyInputResizeObserver.observe(input)
  void nextTick(syncBodyOverlay)
})

const previewHtml = computed(() => {
  const renderer = new marked.Renderer()
  const escapeAttribute = (value: string) => value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  renderer.link = token => {
    const rawHref = token.href.trim()
    const isExplicitUrl = /^(?:[a-z][a-z\d+.-]*:|\/\/|\/|\?|#|\.\.?\/)/i.test(rawHref)
    const host = rawHref.split(/[/?#]/, 1)[0]
    const isBareWebsite = !isExplicitUrl && (host === 'localhost' || host.startsWith('www.') || host.includes('.'))
    const href = escapeAttribute(isBareWebsite ? `https://${rawHref}` : token.href)
    const title = token.title ? ` title="${escapeAttribute(token.title)}"` : ''
    const label = marked.parseInline(token.text) as string
    const referenceClass = noteReferenceHref.test(rawHref) ? ' class="note-reference-link"' : ''
    return `<a href="${href}"${title}${referenceClass}>${label}</a>`
  }
  renderer.image = token => {
    const src = escapeAttribute(token.href)
    const alt = escapeAttribute(token.text)
    const title = token.title ? ` title="${escapeAttribute(token.title)}"` : ''
    return `<a class="markdown-image-link" href="${src}" target="_blank" rel="noopener noreferrer"><img src="${src}" alt="${alt}"${title} loading="lazy"></a>`
  }
  const html = marked.parse(draft.value?.body_md || '', { renderer }) as string
  return DOMPurify.sanitize(html, { FORBID_TAGS: ['iframe'] })
})
const isDirty = computed(() => draft.value !== null && JSON.stringify(draft.value) !== savedDraft.value)

function captureAppRoute(): AppRoute {
  const route: AppRoute = {
    view: view.value,
    notebookId: filterNotebook.value || undefined,
    tagId: filterTag.value || undefined,
    searchMode: searchMode.value,
    calendarMonth: `${calendarDate.value.getFullYear()}-${String(calendarDate.value.getMonth() + 1).padStart(2, '0')}`,
    selectedDay: calendarDayPanelOpen.value ? selectedDay.value : undefined,
    listOpen: listOpen.value,
    cardLayout: cardLayout.value,
    editorMode: editorMode.value,
    updatedDesc: updatedDesc.value,
  }
  if (editorOpen.value) {
    if (draft.value?.id) route.noteId = draft.value.id
    else route.newNote = true
  }
  if (activeLinkDraft.value) route.linkDraftId = activeLinkDraft.value.id
  if (searched.value) route.searchQuery = searchQuery.value
  if (view.value === 'assistant' && activeConversationId.value) route.conversationId = activeConversationId.value
  if (profileDialog.value) route.settings = activeSettingsSection.value
  if (uploadPanelOpen.value) route.upload = true
  return route
}

function routeHash(route: AppRoute) {
  const params = new URLSearchParams()
  if (route.view === 'notes' || route.view === 'notebooks') {
    if (route.notebookId) params.set('notebook', route.notebookId)
    if (route.tagId) params.set('tag', route.tagId)
    if (route.noteId) params.set('note', route.noteId)
    if (route.linkDraftId) params.set('linkDraft', route.linkDraftId)
    if (route.newNote) params.set('new', '1')
    if (route.searchQuery) params.set('q', route.searchQuery)
    if (route.searchMode && route.searchMode !== 'all') params.set('mode', route.searchMode)
  }
  if (route.view === 'assistant' && route.conversationId) params.set('conversation', route.conversationId)
  if (route.settings) params.set('settings', route.settings)
  if (route.upload) params.set('upload', '1')
  if (route.view === 'calendar') {
    if (route.calendarMonth) params.set('month', route.calendarMonth)
    if (route.selectedDay) params.set('day', String(route.selectedDay))
  }
  if (route.view === 'notebooks' || route.view === 'assistant') {
    if (route.listOpen === false) params.set('list', '0')
  }
  if (route.view === 'notebooks' && route.cardLayout === 'list') params.set('layout', 'list')
  if (route.view === 'notebooks' && route.updatedDesc === false) params.set('sort', 'oldest')
  if ((route.noteId || route.newNote) && route.editorMode === 'preview') params.set('editor', 'preview')
  const query = params.toString()
  return `#/${route.view}${query ? `?${query}` : ''}`
}

function routeFromHash(): AppRoute {
  const hash = window.location.hash
  if (!hash.startsWith('#/')) return { view: 'notes' }
  const [path, query = ''] = hash.slice(2).split('?')
  const validViews: View[] = ['notes', 'notebooks', 'assistant', 'calendar', 'weekly', 'archive']
  const params = new URLSearchParams(query)
  const view = path === 'reminders' ? 'calendar' : validViews.includes(path as View) ? path as View : 'notes'
  const settings = params.get('settings')
  const month = params.get('month')
  const day = Number(params.get('day'))
  const mode = params.get('mode')
  return {
    view,
    notebookId: params.get('notebook') || undefined,
    tagId: params.get('tag') || undefined,
    noteId: params.get('note') || undefined,
    linkDraftId: params.get('linkDraft') || undefined,
    newNote: params.get('new') === '1',
    searchQuery: params.get('q') || undefined,
    searchMode: mode === 'title' || mode === 'tag' ? mode : 'all',
    conversationId: params.get('conversation') || undefined,
    settings: settings === 'profile' || settings === 'model' ? settings : undefined,
    upload: params.get('upload') === '1',
    calendarMonth: month && /^\d{4}-\d{2}$/.test(month) ? month : undefined,
    selectedDay: Number.isInteger(day) && day >= 1 && day <= 31 ? day : undefined,
    listOpen: params.get('list') !== '0',
    cardLayout: params.get('layout') === 'list' ? 'list' : 'grid',
    editorMode: params.get('editor') === 'preview' ? 'preview' : 'write',
    updatedDesc: params.get('sort') !== 'oldest',
  }
}

function replaceAppRoute(route = captureAppRoute()) {
  const href = `${window.location.pathname}${window.location.search}${routeHash(route)}`
  const state = window.history.state || {}
  const previousRoute = state.pkmRoute ? state.pkmPreviousRoute || null : null
  currentAppHistoryIndex = Number.isInteger(state.pkmEntryIndex) ? state.pkmEntryIndex : 0
  window.history.replaceState({ ...state, pkmRoute: route, pkmPreviousRoute: previousRoute, pkmEntryIndex: currentAppHistoryIndex }, '', href)
}

function pushAppRoute() {
  if (!routeReady || restoringRoute) return
  const route = captureAppRoute()
  const current = window.history.state?.pkmRoute as AppRoute | undefined
  if (current && routeHash(current) === routeHash(route)) return
  const href = `${window.location.pathname}${window.location.search}${routeHash(route)}`
  currentAppHistoryIndex += 1
  window.history.pushState({ pkmRoute: route, pkmPreviousRoute: current || null, pkmEntryIndex: currentAppHistoryIndex }, '', href)
}

function routeHasPreviousAppEntry() {
  return Boolean(window.history.state?.pkmPreviousRoute)
}

function goBackWithinApp(fallback: () => void) {
  if (routeHasPreviousAppEntry()) window.history.back()
  else {
    fallback()
    replaceAppRoute()
  }
}

async function restoreAppRoute(route: AppRoute) {
  const version = ++routeRestoreVersion
  const wasEditingNewDraft = editorOpen.value && draft.value !== null && !draft.value.id
  restoringRoute = true
  try {
    view.value = (route.view as string) === 'reminders' ? 'calendar' : route.view
    filterNotebook.value = route.notebookId || ''
    filterTag.value = route.tagId || ''
    searchMode.value = route.searchMode || 'all'
    searchQuery.value = route.searchQuery || ''
    searched.value = false
    editorOpen.value = false
    uploadPanelOpen.value = Boolean(route.upload)
    profileDialog.value = Boolean(route.settings)
    if (route.settings) activeSettingsSection.value = route.settings
    if (route.calendarMonth) {
      const [year, month] = route.calendarMonth.split('-').map(Number)
      calendarDate.value = new Date(year, month - 1, 1)
    } else if (view.value === 'calendar') {
      setCalendarToToday()
    }
    selectedDay.value = route.selectedDay || (route.calendarMonth ? 1 : selectedDay.value)
    calendarDayPanelOpen.value = view.value === 'calendar' && (Boolean(route.selectedDay) || !route.calendarMonth)
    listOpen.value = route.listOpen !== false
    cardLayout.value = route.cardLayout || 'grid'
    editorMode.value = route.editorMode || 'write'
    updatedDesc.value = route.updatedDesc !== false
    if (route.linkDraftId) {
      if (activeLinkDraft.value?.id !== route.linkDraftId) {
        const linkDraft = await request<LinkDraft>(`/v1/link-drafts/${route.linkDraftId}`)
        if (version !== routeRestoreVersion) return
        activeLinkDraft.value = linkDraft
        savedLinkDraft.value = JSON.stringify({ title: linkDraft.title, body_md: linkDraft.body_md })
      }
      editorOpen.value = false
    } else {
      activeLinkDraft.value = null
      savedLinkDraft.value = ''
    }
    if (route.newNote) {
      editorOpen.value = true
      if (!wasEditingNewDraft) {
        draft.value = { id: '', title: '', excerpt: '', body_md: '', notebook_id: route.notebookId || null, tag_ids: [], version: 0, index_status: 'pending', created_at: '', updated_at: '' }
        savedDraft.value = JSON.stringify(draft.value)
        saveState.value = 'saved'
      }
    } else if (route.noteId) {
      editorOpen.value = true
      if (draft.value?.id !== route.noteId) {
        const note = await request<Note>(`/v1/notes/${route.noteId}`)
        if (version !== routeRestoreVersion) return
        draft.value = note
        savedDraft.value = JSON.stringify(note)
        saveState.value = 'saved'
      }
    } else if (draft.value && (draft.value.id || !isDirty.value)) {
      draft.value = draft.value.id ? JSON.parse(savedDraft.value) as Note : null
    }
    if (route.view === 'assistant') {
      const conversationId = route.conversationId || conversations.value[0]?.id || ''
      if (conversationId) await selectConversation(conversationId)
      if (version !== routeRestoreVersion) return
    }
    if (route.searchQuery) await runSearch()
    if (version !== routeRestoreVersion) return
    if (route.view === 'archive') await loadArchive()
    if (view.value === 'calendar') await loadReminderData()
  } catch (cause) { showError(cause) }
  finally { if (version === routeRestoreVersion) restoringRoute = false }
}

async function handlePopState(event: PopStateEvent) {
  if (!account.value) return
  const version = ++popstateVersion
  const previousIndex = currentAppHistoryIndex
  const targetIndex = Number.isInteger(event.state?.pkmEntryIndex) ? event.state.pkmEntryIndex as number : previousIndex - 1
  currentAppHistoryIndex = targetIndex
  const route = (event.state?.pkmRoute as AppRoute | undefined) || routeFromHash()
  const leavingCurrentNote = editorOpen.value && (route.noteId !== draft.value?.id || Boolean(route.newNote) !== !draft.value?.id)
  const leavingCurrentLinkDraft = Boolean(activeLinkDraft.value && route.linkDraftId !== activeLinkDraft.value.id)
  if ((leavingCurrentNote && isDirty.value || leavingCurrentLinkDraft && linkDraftDirty.value) && !await confirmLeave()) {
    if (version === popstateVersion) window.history.go(previousIndex - targetIndex)
    return
  }
  if (version !== popstateVersion) return
  if (leavingCurrentNote && isDirty.value) draft.value = draft.value?.id ? JSON.parse(savedDraft.value) as Note : null
  if (leavingCurrentLinkDraft && linkDraftDirty.value) activeLinkDraft.value = null
  await restoreAppRoute(route)
}

async function handleLegacyReminderHash() {
  if (!account.value || !window.location.hash.startsWith('#/reminders')) return
  if ((editorOpen.value || activeLinkDraft.value) && !await confirmLeave()) { replaceAppRoute(); return }
  reminderDialog.value = null
  await restoreAppRoute(routeFromHash())
  replaceAppRoute()
}

watch(visibleNotes, items => {
  const visibleIds = new Set(items.map(note => note.id))
  selectedNoteIds.value = selectedNoteIds.value.filter(id => visibleIds.has(id))
})

async function request<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await fetch(path, { method, credentials: 'same-origin', headers: data === undefined ? {} : { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data) })
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const value = (await response.json()) as { detail?: string | { msg?: string }[] }
      if (typeof value.detail === 'string') detail = value.detail
      else if (Array.isArray(value.detail)) detail = value.detail.map(item => item.msg).join('；')
    } catch { /* 保留状态提示。 */ }
    if (response.status === 401 && path !== '/v1/auth/login') account.value = null
    throw new Error(detail)
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

function localDateKey(value: string): string {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value))
}

async function loadCalendarReminders(): Promise<void> {
  const version = ++calendarLoadVersion
  const year = calendarDate.value.getFullYear(), month = calendarDate.value.getMonth()
  const monthStart = `${year}-${String(month + 1).padStart(2, '0')}-01T00:00:00+08:00`
  const nextYear = month === 11 ? year + 1 : year
  const nextMonth = month === 11 ? 1 : month + 2
  const monthEnd = `${nextYear}-${String(nextMonth).padStart(2, '0')}-01T00:00:00+08:00`
  const from = new Date(monthStart).toISOString()
  const to = new Date(monthEnd).toISOString()
  const items = await listAllReminders(`status=all&from_at=${encodeURIComponent(from)}&to_at=${encodeURIComponent(to)}`)
  if (version !== calendarLoadVersion) return
  calendarReminders.value = items
}

async function listAllReminders(query: string): Promise<Reminder[]> {
  const items: Reminder[] = []
  let offset: number | null = 0
  while (offset !== null) {
    const page: { items: Reminder[]; next_offset: number | null } = await request<{ items: Reminder[]; next_offset: number | null }>(`/v1/reminders?${query}&limit=300&offset=${offset}`)
    items.push(...page.items)
    offset = page.next_offset
  }
  return items
}

async function loadReminderData(): Promise<void> {
  const version = ++workbenchLoadVersion
  workbenchLoading.value = true
  workbenchError.value = ''
  try {
    const [listed, overview] = await Promise.all([
      listAllReminders('status=open'),
      request<WorkbenchOverview>('/v1/workbench'),
    ])
    if (version !== workbenchLoadVersion || !account.value) return
    reminders.value = listed
    workbenchOverview.value = overview
    workbenchLoaded.value = true
    if (view.value === 'calendar') await loadCalendarReminders()
  } catch (cause) {
    if (version === workbenchLoadVersion) workbenchError.value = '工作台内容加载失败'
    throw cause
  } finally {
    if (version === workbenchLoadVersion) workbenchLoading.value = false
  }
}

function openReminderDialog(fixedNoteId: string | null = null, fixedNoteTitle: string | null = null) {
  const today = localDateKey(new Date().toISOString())
  reminderDialog.value = { initialDate: fixedNoteId || !calendarDayPanelOpen.value ? today : selectedDateKey.value, fixedNoteId, fixedNoteTitle }
}

async function reminderSaved() {
  reminderDialog.value = null
  await loadReminderData()
  notice.value = '提醒已保存'
}

async function openReminderItem(item: Reminder) {
  if (item.note_id) { await openNote(item.note_id); return }
  const key = localDateKey(item.due_at)
  const [year, month, day] = key.split('-').map(Number)
  calendarDate.value = new Date(year, month - 1, day)
  selectedDay.value = day
  calendarDayPanelOpen.value = true
  focusedReminderId.value = item.id
  await navigate('calendar')
  await nextTick()
  document.querySelector('.calendar-day-panel')?.scrollIntoView({ block: 'start' })
}

async function searchFromWorkbench() {
  const query = workbenchSearch.value.trim()
  if (!query) return
  await navigate('notebooks')
  searchQuery.value = query
  searchMode.value = 'all'
  await runSearch()
}

function openDigestHistory(kind: ReportKind) {
  digestHistoryKind.value = kind
  void navigate('weekly')
}

async function openWorkbenchReport(run: WorkbenchDigest) {
  if (run.status === 'ready' && run.note_id && run.note_active) await openNote(run.note_id)
  else if (run.status === 'ready' && run.note_archived) {
    focusedArchiveId.value = run.note_id
    await navigate('archive')
  } else openDigestHistory(run.kind)
}

async function openHomeArchive(id?: string) {
  const item = workbenchOverview.value.archive.find(note => note.id === id)
  if (item) await openWorkbenchArchive(item)
  else { focusedArchiveId.value = null; await navigate('archive') }
}

async function completeWorkbenchReminder(item: Reminder) {
  if (completingWorkbenchReminders.value.includes(item.id)) return
  completingWorkbenchReminders.value = [...completingWorkbenchReminders.value, item.id]
  try { await setReminderStatus(item, 'done') }
  finally { completingWorkbenchReminders.value = completingWorkbenchReminders.value.filter(id => id !== item.id) }
}

async function openWorkbenchArchive(item: ArchivedNote) {
  focusedArchiveId.value = item.id
  await navigate('archive')
  while (view.value === 'archive' && !archivedNotes.value.some(note => note.id === item.id) && archiveNextCursor.value) {
    await loadArchive(true)
  }
  await nextTick()
  document.getElementById(`archive-note-${item.id}`)?.scrollIntoView({ block: 'center' })
}

async function setReminderStatus(item: Reminder, status: 'open' | 'done'): Promise<void> {
  try { await request(`/v1/reminders/${item.id}`, 'PATCH', { status }); await loadReminderData() }
  catch (cause) { showError(cause) }
}

async function postponeReminder(item: Reminder): Promise<void> {
  const value = await askForInput({ title: '延期提醒', message: '请输入新的北京时间（如 2026-10-05 09:00）', initialValue: new Date(item.due_at).toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }).slice(0, 16) })
  if (!value) return
  const parsed = new Date(`${value.replace(' ', 'T')}:00+08:00`)
  if (Number.isNaN(parsed.getTime())) { showError(new Error('日期时间格式无效')); return }
  try { await request(`/v1/reminders/${item.id}`, 'PATCH', { due_at: parsed.toISOString() }); await loadReminderData() }
  catch (cause) { showError(cause) }
}

async function cancelReminder(item: Reminder): Promise<void> {
  try { await request(`/v1/reminders/${item.id}`, 'DELETE'); await loadReminderData() }
  catch (cause) { showError(cause) }
}


async function loadAssistantTraceAvailability() {
  try {
    const result = await request<{ enabled: boolean }>('/v1/dev/assistant-traces/enabled')
    assistantTraceViewEnabled.value = result.enabled
  } catch {
    assistantTraceViewEnabled.value = false
  }
}

function showError(cause: unknown) { error.value = cause instanceof Error ? cause.message : '操作失败，请稍后重试'; notice.value = '' }
async function confirmLeave() { return !(isDirty.value || linkDraftDirty.value) || await askForConfirmation({ message: '当前内容有未保存的修改，确定离开吗？', title: '离开编辑', confirmLabel: '离开', danger: true }) }
function formatDate(value: string) { return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
function formatBeijingDate(value: string) { return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
function formatWorkbenchDate(value: string) {
  const day = localDateKey(value)
  const today = localDateKey(new Date().toISOString())
  const tomorrow = localDateKey(new Date(Date.now() + 86400000).toISOString())
  const time = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
  return day === today ? `今天 ${time}` : day === tomorrow ? `明天 ${time}` : formatBeijingDate(value)
}

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

async function loadArchive(append = false) {
  const params = new URLSearchParams({ limit: '100' })
  if (append && archiveNextCursor.value) params.set('cursor', archiveNextCursor.value)
  const page = await request<{ items: ArchivedNote[]; next_cursor: string | null }>(`/v1/notes/archive?${params}`)
  archivedNotes.value = append ? [...archivedNotes.value, ...page.items] : page.items
  archiveNextCursor.value = page.next_cursor
  selectedArchiveIds.value = selectedArchiveIds.value.filter(id => archivedNotes.value.some(item => item.id === id))
}

function toggleArchiveSelection(id: string) {
  selectedArchiveIds.value = selectedArchiveIds.value.includes(id)
    ? selectedArchiveIds.value.filter(item => item !== id)
    : [...selectedArchiveIds.value, id]
}

function toggleAllArchiveSelection(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const pageIds = archivedNotes.value.map(item => item.id)
  selectedArchiveIds.value = checked
    ? [...new Set([...selectedArchiveIds.value, ...pageIds])]
    : selectedArchiveIds.value.filter(id => !pageIds.includes(id))
}

async function restoreArchivedNote(item: ArchivedNote) {
  archiveBusy.value = true
  error.value = ''
  try {
    await request(`/v1/notes/archive/${item.id}/restore`, 'POST')
    archivedNotes.value = archivedNotes.value.filter(note => note.id !== item.id)
    selectedArchiveIds.value = selectedArchiveIds.value.filter(id => id !== item.id)
    await Promise.all([loadNotes(), loadSidebarNotes(), loadCategories()])
    notice.value = '已恢复'
  } catch (cause) { showError(cause) }
  finally { archiveBusy.value = false }
}

async function purgeArchivedNote(item: ArchivedNote) {
  if (!await askForConfirmation({ message: `彻底删除“${item.title || '无标题笔记'}”？文件、修订记录和索引都会一并清除，且无法恢复。`, title: '彻底删除笔记', confirmLabel: '彻底删除', danger: true })) return
  archiveBusy.value = true
  error.value = ''
  try {
    await request<void>(`/v1/notes/archive/${item.id}`, 'DELETE')
    archivedNotes.value = archivedNotes.value.filter(note => note.id !== item.id)
    selectedArchiveIds.value = selectedArchiveIds.value.filter(id => id !== item.id)
    notice.value = '已彻底删除'
  } catch (cause) { showError(cause) }
  finally { archiveBusy.value = false }
}

async function purgeSelectedArchive() {
  const ids = [...selectedArchiveIds.value]
  if (!ids.length || !await askForConfirmation({ message: `彻底删除选中的 ${ids.length} 条笔记？相关文件和索引会一并清除，且无法恢复。`, title: '彻底删除笔记', confirmLabel: '彻底删除', danger: true })) return
  archiveBusy.value = true
  error.value = ''
  try {
    const purged: string[] = []
    const failed: { id: string; error: string }[] = []
    for (let start = 0; start < ids.length; start += 100) {
      const result = await request<{ purged: string[]; failed: { id: string; error: string }[] }>('/v1/notes/archive/purge', 'POST', { note_ids: ids.slice(start, start + 100) })
      purged.push(...result.purged)
      failed.push(...result.failed)
    }
    archivedNotes.value = archivedNotes.value.filter(item => !purged.includes(item.id))
    selectedArchiveIds.value = failed.map(item => item.id)
    notice.value = failed.length
      ? `已清除 ${purged.length} 条，${failed.length} 条失败，可重试`
      : `已清除 ${purged.length} 条`
    if (failed.length) error.value = `${notice.value}：${failed.map(item => item.error).join('；')}`
  } catch (cause) { showError(cause) }
  finally { archiveBusy.value = false }
}

async function submitAuth() {
  busy.value = true; error.value = ''
  try {
    account.value = await request<Account>(`/v1/auth/${authMode.value}`, 'POST', { email: email.value, password: password.value })
    customTemplates.value = []
    password.value = ''
    await Promise.all([loadCategories(), loadNotes(), loadSidebarNotes(), loadConversations(), loadLinkDrafts(), loadReminderData()])
    void loadModelConnection().catch(() => { modelConfigured.value = false })
    void loadAssistantTraceAvailability()
    routeReady = true
    await restoreAppRoute((window.history.state?.pkmRoute as AppRoute | undefined) || routeFromHash())
    replaceAppRoute()
  } catch (cause) { showError(cause) }
  finally { busy.value = false }
}

async function logout() {
  if (!await confirmLeave()) return
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  try {
    await request<void>('/v1/auth/logout', 'POST')
    account.value = null; assistantTraceViewEnabled.value = false; draft.value = null; activeLinkDraft.value = null; savedLinkDraft.value = ''; notes.value = []; customTemplates.value = []; templatePickerOpen.value = false; unclassifiedNotes.value = []; sidebarNotesByNotebook.value = {}; expandedNotebookIds.value = []; conversations.value = []; activeConversationId.value = ''; reminders.value = []; linkDrafts.value = []
    workbenchLoadVersion += 1
    workbenchOverview.value = { reminders: [], latest_daily: null, latest_weekly: null, archive: [], recent_note: null }
    workbenchLoaded.value = false; workbenchLoading.value = false; workbenchError.value = ''; workbenchSearch.value = ''; focusedArchiveId.value = null
    clearSearch(); searchMode.value = 'all'
    profileMenuOpen.value = false; profileDialog.value = false; modelConfigured.value = false
    routeReady = false
    window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}`)
  } catch (cause) { showError(cause) }
}

async function createDraft() {
  if (!await confirmLeave()) return
  templatePickerOpen.value = true
  templateTab.value = 'preset'
  selectedTemplate.value = builtinTemplates()[0]
  customTemplatePage.value = 1
  void loadCustomTemplates()
}

function builtinTemplates(): NoteTemplate[] {
  const date = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
  return [
    { id: 'builtin-essay', name: '随笔', title: '随笔', body_md: '## 灵感\n\n## 正文\n\n## 其他记录\n' },
    { id: 'builtin-daily', name: '每日一记', title: `每日一记 ${date}`, body_md: `# ${date}\n\n## 今日计划\n- [ ] \n\n## 今日记录\n\n## 今日收获\n\n## 明日待办\n- [ ] \n` },
    { id: 'builtin-meeting', name: '工作纪要', title: '工作纪要', body_md: '## 会议信息\n- 时间：\n- 参会人：\n- 主题：\n\n## 讨论内容\n\n## 决议\n\n## 待办事项\n- [ ] 事项：\n  - 负责人：\n  - 截止时间：\n' },
    { id: 'builtin-course', name: '课程摘要', title: '课程摘要', body_md: '## 课程信息\n- 课程：\n- 日期：\n- 讲师：\n\n## 核心概念\n\n## 重点摘要\n\n## 疑问与思考\n\n## 复习清单\n- [ ] \n' },
  ]
}

async function loadCustomTemplates() {
  try {
    customTemplates.value = await request<NoteTemplate[]>('/v1/note-templates')
    if (templateTab.value === 'mine' && !selectedTemplate.value) selectedTemplate.value = customTemplates.value[0] || null
  }
  catch (cause) { showError(cause) }
}

function chooseTemplate(template: NoteTemplate) {
  selectedTemplate.value = template
  if (templateTab.value === 'mine') {
    const index = customTemplates.value.findIndex(item => item.id === template.id)
    if (index >= 0) customTemplatePage.value = Math.floor(index / 9) + 1
  }
}

function selectTemplateTab(tab: 'preset' | 'mine') {
  templateTab.value = tab
  customTemplatePage.value = 1
  selectedTemplate.value = tab === 'preset' ? builtinTemplates()[0] : customTemplates.value[0] || null
}

function createDraftFromTemplate(template: NoteTemplate | null) {
  templatePickerOpen.value = false
  activeLinkDraft.value = null
  savedLinkDraft.value = ''
  if (view.value === 'assistant') view.value = 'notes'
  editorOpen.value = true
  draft.value = { id: '', title: template?.title || '', excerpt: '', body_md: template?.body_md || '', notebook_id: view.value === 'notebooks' ? filterNotebook.value || null : null, tag_ids: [], version: 0, index_status: 'pending', created_at: '', updated_at: '' }
  savedDraft.value = JSON.stringify(draft.value)
  saveState.value = 'saved'; editorTagsOpen.value = false
  editorMode.value = 'write'
  void nextTick(() => titleInput.value?.focus())
  pushAppRoute()
}

async function importNoteTemplate(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.name.toLocaleLowerCase().endsWith('.md')) { showError(new Error('目前只支持导入 Markdown（.md）模板')); return }
  templateImporting.value = true
  try {
    const text = (await file.text()).replace(/^\uFEFF/, '')
    if (text.length > 100_000) throw new Error('模板正文不能超过 100000 个字符')
    const heading = text.match(/^#\s+(.+)\s*$/m)
    const suggestedName = file.name.replace(/\.md$/i, '').trim() || '导入模板'
    const name = await askForInput({ title: '导入 Markdown 模板', message: '设置模板名称。之后可以反复用它新建笔记。', initialValue: suggestedName, placeholder: '模板名称', required: true, confirmLabel: '导入' })
    if (!name) return
    const body = heading ? text.replace(heading[0], '').replace(/^\s*\n/, '') : text
    const template = await request<NoteTemplate>('/v1/note-templates', 'POST', { name, title: heading?.[1]?.trim() || suggestedName, body_md: body })
    customTemplates.value = [template, ...customTemplates.value]
    templateTab.value = 'mine'
    customTemplatePage.value = 1
    selectedTemplate.value = template
    notice.value = `已导入模板「${template.name}」`
  } catch (cause) { showError(cause) }
  finally { templateImporting.value = false }
}

async function renameNoteTemplate(template: NoteTemplate) {
  const name = await askForInput({ title: '编辑模板标题', initialValue: template.name, placeholder: '模板标题', required: true, confirmLabel: '保存' })
  if (!name || name.trim() === template.name) return
  try {
    const updated = await request<NoteTemplate>(`/v1/note-templates/${template.id}`, 'PATCH', { name })
    customTemplates.value = customTemplates.value.map(item => item.id === updated.id ? updated : item)
    if (selectedTemplate.value?.id === updated.id) selectedTemplate.value = updated
  } catch (cause) { showError(cause) }
}

async function deleteNoteTemplate(template: NoteTemplate) {
  if (!await askForConfirmation({ title: '删除模板', message: `删除模板「${template.name}」？已有笔记不会受影响。`, confirmLabel: '删除', danger: true })) return
  try {
    await request<void>(`/v1/note-templates/${template.id}`, 'DELETE')
    customTemplates.value = customTemplates.value.filter(item => item.id !== template.id)
    if (selectedTemplate.value?.id === template.id) selectedTemplate.value = customTemplates.value[0] || null
    customTemplatePage.value = Math.min(customTemplatePage.value, customTemplatePageCount.value)
  } catch (cause) { showError(cause) }
}

async function openNote(id: string, position?: Position) {
  if ((activeLinkDraft.value || draft.value?.id !== id) && !await confirmLeave()) return
  activeLinkDraft.value = null
  savedLinkDraft.value = ''
  if (view.value !== 'notebooks') view.value = 'notes'
  editorOpen.value = true
  error.value = ''
  try {
    draft.value = await request<Note>(`/v1/notes/${id}`)
    savedDraft.value = JSON.stringify(draft.value)
    saveState.value = 'saved'; editorTagsOpen.value = false
    pushAppRoute()
    if (position) {
      if (position.version !== draft.value.version) { notice.value = '笔记已更新，请重新搜索以定位最新原文'; return }
      if (draft.value.file && draft.value.file.extension !== 'md' && position.location) {
        const place = position.location
        notice.value = place.kind === 'page' ? `原文位置：PDF 第 ${place.page} 页` : place.kind === 'cell' ? `原文位置：工作表「${place.sheet}」单元格 ${place.cell}` : place.kind === 'paragraph' ? `原文位置：DOCX 第 ${place.paragraph} 段` : `原文位置：工作表「${place.sheet}」`
      }
      editorMode.value = 'write'
      await nextTick()
      if (position.source_field === 'body' && bodyInput.value) {
        // API 偏移量按 Unicode 码点计数；textarea 偏移量按 UTF-16 代码单元计数。
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
      ? draft.value.file?.extension === 'md'
        ? await (async () => {
            const form = new FormData()
            form.append('file', new Blob([snapshot.body_md], { type: 'text/markdown' }), draft.value?.file?.filename || 'note.md')
            const response = await fetch(`/v1/notes/${startId}/file?version=${draft.value?.version}`, { method: 'PUT', credentials: 'same-origin', body: form })
            const result = await response.json()
            if (!response.ok) throw new Error(result.detail || '保存失败')
            return result as Note
          })()
        : await request<Note>(`/v1/notes/${startId}`, 'PATCH', { ...snapshot, version: draft.value.version })
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

function openImagePicker() {
  const input = bodyInput.value
  if (!input || !draft.value) return
  imageInsertionRange.value = { start: input.selectionStart, end: input.selectionEnd, noteId: draft.value.id }
  imagePickerOpen.value = true
}

function closeImagePicker() {
  imagePickerOpen.value = false
  nextTick(() => bodyInput.value?.focus())
}

function insertImageUrlPlaceholder() {
  if (!draft.value || draft.value.id !== imageInsertionRange.value.noteId) { imagePickerOpen.value = false; return }
  imagePickerOpen.value = false
  nextTick(() => {
    bodyInput.value?.setSelectionRange(imageInsertionRange.value.start, imageInsertionRange.value.end)
    applyEditorCommand('image')
  })
}

function insertExistingImage(image: { id: string; title: string; file: { filename: string } | null }) {
  const current = draft.value
  if (!current || current.id !== imageInsertionRange.value.noteId) { imagePickerOpen.value = false; return }
  const { start, end } = imageInsertionRange.value
  const label = (image.title || image.file?.filename || '图片').replace(/\\/g, '\\\\').replace(/\[/g, '\\[').replace(/\]/g, '\\]').replace(/[\r\n]+/g, ' ')
  const markdown = `![${label}](/v1/notes/${image.id}/file)`
  if (current.body_md.length - (end - start) + markdown.length > 100000) { showError(new Error('笔记正文已达到 100000 字符上限')); return }
  current.body_md = current.body_md.slice(0, start) + markdown + current.body_md.slice(end)
  imagePickerOpen.value = false
  nextTick(() => {
    bodyInput.value?.focus()
    bodyInput.value?.setSelectionRange(start + markdown.length, start + markdown.length)
  })
}

function openNoteReferencePicker() {
  const input = bodyInput.value
  if (!input || !draft.value) return
  noteReferenceInsertionRange.value = {
    start: input.selectionStart,
    end: input.selectionEnd,
    noteId: draft.value.id,
    bodyScrollTop: input.scrollTop,
    areaScrollTop: input.closest('.editor-writing-area')?.scrollTop || 0,
    pageScrollY: window.scrollY,
  }
  noteReferencePickerOpen.value = true
}

function closeNoteReferencePicker() {
  noteReferencePickerOpen.value = false
  nextTick(() => bodyInput.value?.focus({ preventScroll: true }))
}

function insertNoteReference(note: { id: string; title: string }) {
  const current = draft.value
  if (!current || current.id !== noteReferenceInsertionRange.value.noteId) { noteReferencePickerOpen.value = false; return }
  const { start, end, bodyScrollTop, areaScrollTop, pageScrollY } = noteReferenceInsertionRange.value
  const label = (note.title || '无标题笔记').replace(/\\/g, '\\\\').replace(/\[/g, '\\[').replace(/\]/g, '\\]').replace(/[\r\n]+/g, ' ')
  const markdown = `[${label}](#/notes?note=${note.id})`
  if (current.body_md.length - (end - start) + markdown.length > 100000) { showError(new Error('笔记正文已达到 100000 字符上限')); return }
  current.body_md = current.body_md.slice(0, start) + markdown + current.body_md.slice(end)
  noteReferencePickerOpen.value = false
  nextTick(() => {
    const input = bodyInput.value
    if (!input) return
    input.focus({ preventScroll: true })
    input.setSelectionRange(start + markdown.length, start + markdown.length)
    requestAnimationFrame(() => {
      input.scrollTop = bodyScrollTop
      const area = input.closest('.editor-writing-area')
      if (area) area.scrollTop = areaScrollTop
      window.scrollTo(window.scrollX, pageScrollY)
      syncBodyOverlay()
    })
  })
}

function openNoteReferenceLink(event: MouseEvent) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  const target = event.target
  if (!(target instanceof Element)) return
  const link = target.closest<HTMLAnchorElement>('a.note-reference-link')
  if (!link) return
  const match = noteReferenceHref.exec(link.getAttribute('href') || '')
  if (!match) return
  event.preventDefault()
  void openNote(match[1])
}

async function deleteNote() {
  const current = draft.value
  if (!current?.id) return
  let referenceWarning = ''
  if (current.file && ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tif', 'tiff', 'ico'].includes(current.file.extension)) {
    let references: { total_notes: number; total_references: number; items: { title: string }[] }
    try { references = await request<{ total_notes: number; total_references: number; items: { title: string }[] }>(`/v1/notes/${current.id}/image-references`) }
    catch (cause) { showError(cause); return }
    if (references.total_notes) {
      const titles = references.items.slice(0, 3).map(item => `「${item.title || '无标题笔记'}」`).join('、')
      const remainder = references.total_notes > 3 ? `，另有 ${references.total_notes - 3} 篇` : ''
      referenceWarning = `\n\n此图片被 ${references.total_references} 处引用（${titles}${remainder}）。归档后引用图片会暂时失效，图片描述也会从检索上下文移除；30 天内恢复图片后会重新显示。`
    }
  }
  if (!await askForConfirmation({ message: `删除“${current.title || '无标题笔记'}”？删除后可在归档中恢复，30 天后自动清除。${referenceWarning}`, title: '删除笔记', confirmLabel: '删除并归档', danger: true })) return
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  busy.value = true
  try {
    await request<void>(`/v1/notes/${current.id}?version=${current.version}`, 'DELETE')
    draft.value = null; savedDraft.value = ''; editorOpen.value = false; notice.value = '笔记已删除'
    replaceAppRoute()
    await Promise.all([loadNotes(), loadCategories(), loadSidebarNotes(), loadReminderData(), ...(searched.value ? [runSearch()] : [])])
  } catch (cause) { showError(cause) }
  finally { busy.value = false }
}

function toggleNoteSelection(id: string) {
  selectedNoteIds.value = selectedNoteIds.value.includes(id)
    ? selectedNoteIds.value.filter(item => item !== id)
    : [...selectedNoteIds.value, id]
}

function toggleNoteSelectionMode() {
  selectingNotes.value = !selectingNotes.value
  if (!selectingNotes.value) selectedNoteIds.value = []
}

function toggleAllVisibleNotes(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const visibleIds = visibleNotes.value.map(note => note.id)
  selectedNoteIds.value = checked
    ? [...new Set([...selectedNoteIds.value, ...visibleIds])]
    : selectedNoteIds.value.filter(id => !visibleIds.includes(id))
}

async function deleteNotesFromList(targets: NoteSummary[]) {
  if (!targets.length || notesDeleting.value) return
  const noun = targets.length === 1 ? '这条笔记' : `选中的 ${targets.length} 条笔记`
  if (!await askForConfirmation({ message: `删除${noun}？删除后可在归档中恢复，30 天后自动清除。`, title: '删除笔记', confirmLabel: '删除并归档', danger: true })) return

  notesDeleting.value = true
  error.value = ''
  const outcomes: PromiseSettledResult<void>[] = []
  for (let start = 0; start < targets.length; start += 5) {
    outcomes.push(...await Promise.allSettled(targets.slice(start, start + 5).map(note =>
      request<void>(`/v1/notes/${note.id}?version=${note.version}`, 'DELETE'),
    )))
  }
  const deletedIds = targets.filter((_note, index) => outcomes[index].status === 'fulfilled').map(note => note.id)
  const failed = outcomes.filter((result): result is PromiseRejectedResult => result.status === 'rejected')

  if (draft.value?.id && deletedIds.includes(draft.value.id)) {
    if (autoSaveTimer) clearTimeout(autoSaveTimer)
    draft.value = null
    savedDraft.value = ''
    editorOpen.value = false
  }
  notes.value = notes.value.filter(note => !deletedIds.includes(note.id))
  results.value = results.value.filter(note => !deletedIds.includes(note.id))
  for (const noteId of deletedIds) {
    for (const [notebookId, items] of Object.entries(sidebarNotesByNotebook.value)) {
      sidebarNotesByNotebook.value[notebookId] = items.filter(note => note.id !== noteId)
    }
    unclassifiedNotes.value = unclassifiedNotes.value.filter(note => note.id !== noteId)
  }
  selectedNoteIds.value = selectedNoteIds.value.filter(id => !deletedIds.includes(id))
  selectingNotes.value = selectedNoteIds.value.length > 0
  try {
    await Promise.all([loadNotes(), loadCategories(), loadSidebarNotes(), loadReminderData(), ...(searched.value ? [runSearch()] : [])])
  } catch (cause) { showError(cause) }
  if (failed.length) {
    error.value = `已删除 ${deletedIds.length} 条，${failed.length} 条失败，请重试`
    notice.value = ''
  } else {
    notice.value = `已移入归档${deletedIds.length > 1 ? `（${deletedIds.length} 条）` : ''}`
  }
  notesDeleting.value = false
}

function deleteNoteFromCard(note: NoteSummary) {
  return deleteNotesFromList([note])
}

function deleteSelectedNotes() {
  const selected = visibleNotes.value.filter(note => visibleSelectedNoteIds.value.includes(note.id))
  return deleteNotesFromList(selected)
}

async function exportCurrentNote() {
  const current = draft.value
  if (!current?.id) return
  if (isDirty.value && !await askForConfirmation({ message: '当前笔记有未保存修改。导出将包含上次保存的版本，继续吗？', title: '导出已保存版本', confirmLabel: '继续导出' })) return
  window.location.assign(`/v1/notes/${current.id}/export`)
}

function exportAllNotes() {
  window.location.assign(filterNotebook.value ? `/v1/notebooks/${filterNotebook.value}/export` : '/v1/notes/export')
}

async function uploadNoteFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!await confirmLeave()) { input.value = ''; return }
  fileBusy.value = true; error.value = ''; notice.value = ''
  try {
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
    const duplicateResponse = await fetch('/v1/notes/file-duplicate-check', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sha256 }),
    })
    const duplicate = await duplicateResponse.json()
    if (!duplicateResponse.ok) throw new Error(typeof duplicate.detail === 'string' ? duplicate.detail : '无法检查文件是否重复')
    if (duplicate.exists) {
      notice.value = `文件已存在于笔记「${duplicate.title}」（${duplicate.filename}），未重复上传`
      return
    }
    const form = new FormData(); form.append('file', file); form.append('sha256', sha256)
    const params = new URLSearchParams()
    if (filterNotebook.value) params.set('notebook_id', filterNotebook.value)
    let response = await fetch(`/v1/notes/upload?${params}`, { method: 'POST', credentials: 'same-origin', body: form })
    let data = await response.json()
    if (response.status === 409 && data.detail?.code === 'duplicate_file') {
      notice.value = `文件已存在于笔记「${data.detail.title}」（${data.detail.filename}），未重复上传`
      return
    }
    if (response.status === 409 && typeof data.detail === 'string' && ['.doc', '.xls'].some(extension => file.name.toLowerCase().endsWith(extension))) {
      const convert = await askForConfirmation({ message: `${data.detail}\n\n确认使用 ONLYOFFICE 转换吗？原始文件会保留。`, title: '转换旧版 Office 文件', confirmLabel: '转换并上传' })
      if (convert) {
        params.set('convert_legacy', 'true')
        response = await fetch(`/v1/notes/upload?${params}`, { method: 'POST', credentials: 'same-origin', body: form })
        data = await response.json()
      } else return
    }
    if (response.status === 409 && data.detail?.code === 'duplicate_file') {
      notice.value = `文件已存在于笔记「${data.detail.title}」（${data.detail.filename}），未重复上传`
      return
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '上传失败')
    draft.value = data as Note; savedDraft.value = JSON.stringify(data); editorOpen.value = true; view.value = 'notebooks'; saveState.value = 'saved'
    pushAppRoute()
    await Promise.all([loadNotes(), loadCategories(), loadSidebarNotes()])
  } catch (cause) { showError(cause) }
  finally { fileBusy.value = false; input.value = '' }
}

function openLinkDraftWorkspace(item: LinkDraft) {
  activeLinkDraft.value = { ...item }
  savedLinkDraft.value = JSON.stringify({ title: item.title, body_md: item.body_md })
  editorOpen.value = false
  uploadPanelOpen.value = false
  if (view.value !== 'notebooks') view.value = 'notebooks'
  editorMode.value = 'write'
  pushAppRoute()
}

async function closeLinkDraftWorkspace() {
  if (!await confirmLeave()) return
  activeLinkDraft.value = null
  savedLinkDraft.value = ''
  goBackWithinApp(() => replaceAppRoute())
}

function onLinkDraftUpdated(item: LinkDraft) {
  const index = linkDrafts.value.findIndex(draft => draft.id === item.id)
  if (index >= 0) linkDrafts.value[index] = item
  if (activeLinkDraft.value?.id === item.id) savedLinkDraft.value = JSON.stringify({ title: item.title, body_md: item.body_md })
}

function onLinkDraftChanged(item: LinkDraft) {
  if (activeLinkDraft.value?.id === item.id) activeLinkDraft.value = item
}

async function onLinkDraftPublished(note: { id: string; title: string }) {
  activeLinkDraft.value = null
  savedLinkDraft.value = ''
  notice.value = `已发布：${note.title}`
  replaceAppRoute()
  await Promise.all([loadNotes(), loadCategories(), loadSidebarNotes(), loadLinkDrafts()])
}

async function loadLinkDrafts() {
  const result = await request<{ items: LinkDraft[] }>('/v1/link-drafts')
  linkDrafts.value = result.items
}

async function importLinkDraft() {
  const url = await askForInput({ title: '识别网页', message: '输入公开网页链接。', placeholder: 'https://', required: true, confirmLabel: '继续' })
  if (!url) return
  fileBusy.value = true
  try {
    const draft = await request<LinkDraft>('/v1/link-drafts', 'POST', { url, notebook_id: filterNotebook.value || null })
    notice.value = draft.fetch_status === 'ready' ? '网页正文已抓取并保存为草稿' : draft.fetch_status === 'pending' ? '网页草稿已创建，Agent 正在后台获取网页' : `草稿已保存：${draft.fetch_error || '抓取失败，可手动补充正文'}`
    await loadLinkDrafts()
    openLinkDraftWorkspace(draft)
  } catch (cause) { showError(cause) }
  finally { fileBusy.value = false }
}

async function openLinkDraftList() {
  try {
    await loadLinkDrafts()
    if (!linkDrafts.value.length) { notice.value = '暂无网页草稿'; return }
    const choice = await askForInput({ title: '打开网页草稿', message: `${linkDrafts.value.map((item, index) => `${index + 1}. ${item.title}`).join('\n')}\n\n输入序号打开草稿。`, placeholder: '序号', required: true, confirmLabel: '打开' })
    const selected = Number(choice) - 1
    if (choice && linkDrafts.value[selected]) openLinkDraftWorkspace(linkDrafts.value[selected])
  } catch (cause) { showError(cause) }
}

async function openUploadPanel() {
  if (!await confirmLeave()) return
  uploadPanelOpen.value = true
  pushAppRoute()
}

function closeUploadPanel() {
  goBackWithinApp(() => { uploadPanelOpen.value = false })
}

async function afterUploadUpdated() {
  try { await Promise.all([loadNotes(), loadCategories(), loadSidebarNotes(), ...(searched.value ? [runSearch()] : [])]) }
  catch (cause) { showError(cause) }
}

async function openUploadLinkDraft(item: LinkDraft) {
  if (!await confirmLeave()) return
  openLinkDraftWorkspace(item)
}

async function refreshFileNote() {
  if (!draft.value?.id) return
  try {
    const fresh = await request<Note>(`/v1/notes/${draft.value.id}`)
    draft.value = fresh; savedDraft.value = JSON.stringify(fresh); saveState.value = 'saved'
    void Promise.all([loadNotes(), loadSidebarNotes(), ...(searched.value ? [runSearch()] : [])])
  } catch (cause) { showError(cause) }
}

function startCreateCategory(kind: 'notebooks' | 'tags') {
  notebookCreateMenuOpen.value = false
  newCategoryKind.value = kind
  if (kind === 'notebooks') notebooksSectionOpen.value = true
  else tagsSectionOpen.value = true
  newCategoryName.value = ''
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
  nextTick(() => document.querySelector<HTMLInputElement>('.category-rename-input')?.focus())
}
async function renameCategory(kind: 'notebooks' | 'tags', item: Category) {
  const name = editingCategoryName.value.trim()
  if (!name) { editingCategory.value = ''; return }
  if (name === item.name) { editingCategory.value = ''; return }
  try { await request(`/v1/${kind}/${item.id}`, 'PATCH', { name }); await loadCategories(); editingCategory.value = '' } catch (cause) { showError(cause) }
}
async function deleteCategory(kind: 'notebooks' | 'tags', item: Category) {
  if (!await askForConfirmation({ message: `删除${kind === 'notebooks' ? '笔记本' : '标签'}“${item.name}”？`, title: `删除${kind === 'notebooks' ? '笔记本' : '标签'}`, confirmLabel: '删除', danger: true })) return
  editingCategory.value = ''
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
    replaceAppRoute()
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
  pushAppRoute()
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
    const notebookFilter = view.value === 'notebooks' ? filterNotebook.value : ''
    if (searchMode.value === 'all') {
      const params = new URLSearchParams({ q: query, mode: 'hybrid', limit: '30' })
      if (notebookFilter) params.set('notebook_id', notebookFilter)
      if (filterTag.value) params.set('tag_id', filterTag.value)
      const response = await request<{ items: SearchHit[]; semantic_status: string }>(`/v1/search?${params}`)
      const summaries = await Promise.all(response.items.map(hit => request<NoteSummary>(`/v1/notes/${hit.note_id}`)))
      if (version !== searchRequestVersion) return
      results.value = summaries
      searchNextCursor.value = null
      searched.value = true
      if (!append) pushAppRoute()
      return
    }

    const params = new URLSearchParams({ limit: '30', updated_desc: String(updatedDesc.value) })
    if (notebookFilter) params.set('notebook_id', notebookFilter)
    if (filterTag.value) params.set('tag_id', filterTag.value)
    params.set('q', query)
    params.set('q_scope', searchMode.value)
    if (append && searchNextCursor.value) params.set('cursor', searchNextCursor.value)
    const response = await request<{ items: NoteSummary[]; next_cursor: string | null }>(`/v1/notes?${params}`)
    if (version !== searchRequestVersion) return
    results.value = append ? [...results.value, ...response.items] : response.items
    searchNextCursor.value = response.next_cursor
    searched.value = true
    if (!append) pushAppRoute()
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
  } catch { /* 后续手动操作会显示连接错误。 */ }
}

async function openAssistant() {
  if ((editorOpen.value || activeLinkDraft.value) && !await confirmLeave()) return
  activeLinkDraft.value = null
  savedLinkDraft.value = ''
  if (editorOpen.value && isDirty.value) draft.value = draft.value?.id ? JSON.parse(savedDraft.value) as Note : null
  if (view.value !== 'assistant') listOpen.value = true
  editorOpen.value = false; view.value = 'assistant'
  if (activeConversation.value) pushAppRoute()
  else if (conversations.value.length) void selectConversation(conversations.value[0].id)
  else void newConversation()
}

async function closeEditor() {
  if (!await confirmLeave()) return
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  if (isDirty.value) draft.value = draft.value?.id ? JSON.parse(savedDraft.value) as Note : null
  editorTagsOpen.value = false
  goBackWithinApp(() => { editorOpen.value = false })
}

async function navigate(next: View) {
  profileMenuOpen.value = false
  notebookCreateMenuOpen.value = false
  if (next === 'assistant') { openAssistant(); return }
  if ((editorOpen.value || activeLinkDraft.value) && !await confirmLeave()) return
  activeLinkDraft.value = null
  savedLinkDraft.value = ''
  if (editorOpen.value && isDirty.value) draft.value = draft.value?.id ? JSON.parse(savedDraft.value) as Note : null
  view.value = next; editorOpen.value = false; searched.value = false
  if (next === 'calendar') setCalendarToToday()
  if (next === 'notes') { filterNotebook.value = ''; filterTag.value = '' }
  if (next === 'notebooks') { filterNotebook.value = ''; filterTag.value = ''; listOpen.value = true; notebooksSectionOpen.value = true }
  if (next === 'archive') { selectedArchiveIds.value = []; await loadArchive().catch(showError) }
  if (next === 'notes' || next === 'calendar') void loadReminderData().catch(showError)
  pushAppRoute()
  await nextTick()
  window.scrollTo(0, 0)
}

function showProfileDialog() {
  profileMenuOpen.value = false
  activeSettingsSection.value = 'profile'
  settingsSearch.value = ''
  profileDialog.value = true
  pushAppRoute()
}

function showModelSettings() {
  profileMenuOpen.value = false
  activeSettingsSection.value = 'model'
  settingsSearch.value = ''
  profileDialog.value = true
  pushAppRoute()
}

function closeSettingsDialog() {
  goBackWithinApp(() => { profileDialog.value = false })
}

function handleEscape(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  profileMenuOpen.value = false
  if (imagePickerOpen.value) { closeImagePicker(); return }
  if (noteReferencePickerOpen.value) { closeNoteReferencePicker(); return }
  if (templatePickerOpen.value) { templatePickerOpen.value = false; return }
  if (profileDialog.value) { closeSettingsDialog(); return }
  if (activeLinkDraft.value) { void closeLinkDraftWorkspace(); return }
  notebookCreateMenuOpen.value = false; editingConversationId.value = ''; editingCategory.value = ''; newCategoryKind.value = ''; editorTagsOpen.value = false
}

async function selectNotebook(id: string) {
  notebookCreateMenuOpen.value = false
  if ((editorOpen.value || activeLinkDraft.value) && !await confirmLeave()) return
  activeLinkDraft.value = null
  savedLinkDraft.value = ''
  if (editorOpen.value && isDirty.value) draft.value = draft.value?.id ? JSON.parse(savedDraft.value) as Note : null
  const wasSelected = view.value === 'notebooks' && filterNotebook.value === id
  filterNotebook.value = id
  if (!id) filterTag.value = ''
  view.value = 'notebooks'; editorOpen.value = false; searched.value = false
  pushAppRoute()
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
  if (draft.value?.id === note.id) {
    filterNotebook.value = note.notebook_id ?? ''
    replaceAppRoute()
  }
}

async function loadConversations() {
  const response = await request<{ items: ConversationSummary[] }>('/v1/assistant/conversations')
  conversations.value = response.items.map(item => ({ ...item, messages: [], loaded: false, loading: false }))
  activeConversationId.value = conversations.value[0]?.id ?? ''
  if (activeConversationId.value) await selectConversation(activeConversationId.value)
}

async function selectConversation(id: string, recordRoute = true) {
  editingConversationId.value = ''
  activeConversationId.value = id
  if (recordRoute) pushAppRoute()
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

async function newConversation(recordRoute = true) {
  conversationQuery.value = ''
  editingConversationId.value = ''
  if (activeConversation.value && activeConversation.value.loaded && !activeConversation.value.messages.length) {
    activeConversationId.value = activeConversation.value.id
    return
  }
  try {
    const created = await request<ConversationSummary>('/v1/assistant/conversations', 'POST')
    conversations.value.unshift({ ...created, messages: [], loaded: true, loading: false })
    activeConversationId.value = created.id
    if (recordRoute) pushAppRoute()
  } catch (cause) { showError(cause) }
}

function startRenameConversation(item: Conversation) {
  editingConversationId.value = item.id
  editingConversationTitle.value = item.title
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
  if (!await askForConfirmation({ message: `删除对话“${item.title}”？`, title: '删除对话', confirmLabel: '删除', danger: true })) return
  editingConversationId.value = ''
  try {
    await request<void>(`/v1/assistant/conversations/${item.id}`, 'DELETE')
    const wasActive = activeConversationId.value === item.id
    conversations.value = conversations.value.filter(conversation => conversation.id !== item.id)
    if (wasActive) {
      activeConversationId.value = ''
      const next = conversations.value[0]
      if (next) await selectConversation(next.id, false)
      else await newConversation(false)
    }
    replaceAppRoute()
  } catch (cause) { showError(cause) }
}

function toggleConversationSearch() {
  conversationSearchOpen.value = !conversationSearchOpen.value
  if (!conversationSearchOpen.value) conversationQuery.value = ''
}

function handleAnswered(conversationId: string, result: SentMessages, replaceFromMessageId: string | null) {
  const item = conversations.value.find(conversation => conversation.id === conversationId)
  if (!item) return
  item.title = result.title
  item.updated_at = result.updated_at
  item.loaded = true
  if (replaceFromMessageId) {
    const index = item.messages.findIndex(message => message.id === replaceFromMessageId)
    if (index >= 0) item.messages.splice(index)
  }
  item.messages.push(...result.messages)
  conversations.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

function handleConversationChanged(conversationId: string, result: ConversationSummary & { messages: ChatMessage[] }) {
  const item = conversations.value.find(conversation => conversation.id === conversationId)
  if (!item) return
  item.title = result.title
  item.updated_at = result.updated_at
  item.messages = result.messages
  item.loaded = true
  conversations.value.sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

function changeMonth(delta: number) {
  calendarDate.value = new Date(calendarDate.value.getFullYear(), calendarDate.value.getMonth() + delta, 1)
  selectedDay.value = 1
  calendarDayPanelOpen.value = false
  pushAppRoute()
  void loadCalendarReminders().catch(showError)
}

function calendarDayKey(day: number): string {
  return `${calendarDate.value.getFullYear()}-${String(calendarDate.value.getMonth() + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function calendarDayItems(day: number): Reminder[] {
  return calendarEventsByDay.value[calendarDayKey(day)] || []
}

function calendarDayPreview(day: number): Reminder[] {
  const items = calendarDayItems(day)
  return items.slice(0, items.length > 3 ? 2 : 3)
}

function reminderTime(value: string): string {
  return new Date(value).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false })
}

function setCalendarToToday() {
  const [year, month, day] = localDateKey(new Date().toISOString()).split('-').map(Number)
  calendarDate.value = new Date(year, month - 1, day)
  selectedDay.value = day
  calendarDayPanelOpen.value = true
  calendarStatusFilter.value = 'all'
}

function selectCalendarDay(day: number) {
  selectedDay.value = day
  calendarDayPanelOpen.value = true
  calendarStatusFilter.value = 'all'
  pushAppRoute()
}

function closeCalendarDayPanel() {
  calendarDayPanelOpen.value = false
  replaceAppRoute()
}

function goToToday() {
  setCalendarToToday()
  pushAppRoute()
  void loadCalendarReminders().catch(showError)
}

function toggleListPane() {
  listOpen.value = !listOpen.value
  pushAppRoute()
}

function scrollNotebookToTop() {
  mainPane.value?.scrollTo({ top: 0, behavior: 'smooth' })
}

function setCardLayout(layout: 'grid' | 'list') {
  cardLayout.value = layout
  pushAppRoute()
}

function toggleUpdatedSort() {
  updatedDesc.value = !updatedDesc.value
  pushAppRoute()
}

function setSettingsSection(section: SettingsSection) {
  activeSettingsSection.value = section
  replaceAppRoute()
}

watch(() => [draft.value?.title, draft.value?.body_md, draft.value?.tag_ids], () => scheduleAutoSave())
watch([filterNotebook, filterTag, updatedDesc], () => { if (account.value) void (searched.value ? runSearch() : loadNotes()).catch(showError) })
onMounted(async () => {
  window.addEventListener('keydown', handleEscape)
  window.addEventListener('popstate', handlePopState)
  window.addEventListener('hashchange', handleLegacyReminderHash)
  try { account.value = await request<Account>('/v1/auth/me'); await Promise.all([loadCategories(), loadNotes(), loadSidebarNotes(), loadConversations(), loadLinkDrafts(), loadReminderData()]); void loadModelConnection().catch(() => { modelConfigured.value = false }); void loadAssistantTraceAvailability() }
  catch { account.value = null }
  finally {
    if (account.value) {
      routeReady = true
      await restoreAppRoute((window.history.state?.pkmRoute as AppRoute | undefined) || routeFromHash())
      replaceAppRoute()
    }
    booting.value = false
    statusTimer = setInterval(() => void refreshIndexStatus(), 5000)
    reminderTimer = setInterval(() => { if (account.value) void loadReminderData().catch(() => {}) }, 60000)
  }
})
onUnmounted(() => { if (statusTimer) clearInterval(statusTimer); if (reminderTimer) clearInterval(reminderTimer); if (autoSaveTimer) clearTimeout(autoSaveTimer); bodyInputResizeObserver?.disconnect(); window.removeEventListener('keydown', handleEscape); window.removeEventListener('popstate', handlePopState); window.removeEventListener('hashchange', handleLegacyReminderHash) })
</script>

<template>
  <div v-if="booting" class="loading-screen">正在连接知识库…</div>
  <main v-else-if="!account" class="login-page">
    <section class="login-form-side" aria-label="账号登录">
      <div class="login-brand"><span class="login-brand-mark" aria-hidden="true">枫</span><span>个人知识库</span></div>
      <form class="login-form" @submit.prevent="submitAuth" :aria-busy="busy">
        <h1>{{ authMode === 'login' ? '欢迎回来' : '创建账号' }}</h1>
        <label class="login-field" for="auth-email"><span>邮箱地址</span><input id="auth-email" v-model.trim="email" type="email" autocomplete="email" required placeholder="请输入邮箱" /></label>
        <label class="login-field" for="auth-password"><span>密码</span><span class="login-password-wrap"><input id="auth-password" v-model="password" :type="showPassword ? 'text' : 'password'" :autocomplete="authMode === 'login' ? 'current-password' : 'new-password'" minlength="10" required :placeholder="authMode === 'login' ? '请输入密码' : '至少 10 个字符'" /><button class="login-password-toggle" type="button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" :aria-pressed="showPassword" @click="showPassword = !showPassword"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.7-5.5 10-5.5S22 12 22 12s-3.7 5.5-10 5.5S2 12 2 12Z"/><circle cx="12" cy="12" r="2.6"/><path v-if="showPassword" d="M4 20 20 4"/></svg></button></span></label>
        <p v-if="error" class="login-error" role="alert" aria-live="polite">{{ error }}</p>
        <button class="login-submit" type="submit" :disabled="busy"><span>{{ busy ? authMode === 'login' ? '正在登录…' : '正在创建…' : authMode === 'login' ? '登录' : '创建账号' }}</span><span v-if="busy" class="login-spinner" aria-hidden="true"></span><svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12h15M13 6l6 6-6 6"/></svg></button>
        <div class="login-switch"><span>{{ authMode === 'login' ? '还没有账号？' : '已有账号？' }}</span><button type="button" @click="authMode = authMode === 'login' ? 'register' : 'login'; error = ''">{{ authMode === 'login' ? '创建账号' : '返回登录' }}</button></div>
      </form>
    </section>
    <section class="login-story" aria-label="个人知识库">
      <div class="login-photo-frame"><img :src="loginArtwork" width="1122" height="1402" alt="自然光下的笔记本与钢笔" fetchpriority="high" /></div>
      <div class="login-sticky-note" aria-hidden="true"><small>随手记</small><strong>每个念头，<br />都值得被记得。</strong></div>
      <h2>让想法，慢慢长成答案。</h2>
    </section>
  </main>
  <main v-else class="workspace" :class="{ 'with-list': (view === 'notebooks' || view === 'assistant') && listOpen, 'calendar-workspace': view === 'calendar', 'notebook-workspace': view === 'notebooks' }">
    <aside class="icon-rail" aria-label="主导航">
      <div class="rail-mark" title="个人笔记">枫</div>
      <nav class="rail-nav">
        <button v-for="item in ([['notes','grid','工作台'],['notebooks','book','笔记本'],['assistant','spark','AI 对话'],['calendar','calendar','日程提醒'],['weekly','note','周报'],['archive','archive','归档']] as const)" :key="item[0]" class="rail-button" :class="{ active: view === item[0] }" :aria-label="item[2]" :title="item[2]" @click="navigate(item[0])"><AppIcon :name="item[1]" /></button>
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
            <div class="pane-row-wrap notebook-row" :class="{ active: filterNotebook === item.id || editingCategory === item.id, 'drop-target': dragOverNotebookId === item.id, 'action-pending': editingCategory === item.id }" @dragover="dragOverNotebook(item.id, $event)" @dragleave="leaveNotebookDrop" @drop="dropNoteIntoNotebook(item.id, $event)">
              <input v-if="editingCategory === item.id" v-model="editingCategoryName" class="category-rename-input" :aria-label="'编辑笔记本名称' + item.name" @keydown.enter.prevent="renameCategory('notebooks', item)" @keydown.esc="editingCategory = ''" />
              <button v-else class="pane-row" :class="{ active: filterNotebook === item.id }" :aria-expanded="(item.note_count ?? 0) > 0 ? expandedNotebookIds.includes(item.id) : undefined" @click="selectNotebook(item.id)"><AppIcon name="book" /><span>{{ item.name }}</span></button>
              <div class="notebook-row-actions">
                <template v-if="editingCategory === item.id"><button class="row-action confirm-edit" aria-label="确认修改" @click="renameCategory('notebooks', item)"><AppIcon name="check" /></button><button class="row-action confirm-cancel" aria-label="取消修改" @click="editingCategory = ''"><AppIcon name="close" /></button></template>
                <template v-else><button class="row-action" :aria-label="'编辑' + item.name" title="编辑" @click="startRenameCategory(item)"><AppIcon name="edit" /></button><button class="row-action" :aria-label="'删除' + item.name" title="删除" @click="deleteCategory('notebooks', item)"><AppIcon name="trash" /></button></template>
              </div>
              <button v-if="(item.note_count ?? 0) > 0" class="notebook-expand" type="button" :aria-label="`${expandedNotebookIds.includes(item.id) ? '收起' : '展开'}${item.name}`" :aria-expanded="expandedNotebookIds.includes(item.id)" @click="selectNotebook(item.id)"><AppIcon class="row-chevron" :class="{ expanded: expandedNotebookIds.includes(item.id) }" name="chevron" /></button>
            </div>
            <div v-if="(item.note_count ?? 0) > 0 && expandedNotebookIds.includes(item.id)" class="sidebar-note-list">
              <button v-for="note in sidebarNotesByNotebook[item.id] || []" :key="note.id" type="button" class="sidebar-note" :class="{ active: editorOpen && draft?.id === note.id, dragging: draggedNoteId === note.id }" draggable="true" @dragstart="startNoteDrag(note.id, $event)" @dragend="finishNoteDrag" @click="openSidebarNote(note)">
                <span class="sidebar-note-title"><FileTypeIcon :extension="note.file?.extension || note.content_kind" /><span>{{ note.title || '无标题笔记' }}</span></span>
                <span v-if="note.tag_ids.length" class="sidebar-note-tags"><span v-for="tagId in note.tag_ids" :key="tagId">#{{ tagNames[tagId] || '标签' }}</span></span>
              </button>
            </div>
          </div>
          <div v-if="unclassifiedNotes.length" class="sidebar-unclassified">
            <div class="sidebar-unclassified-heading">未分类</div>
            <div class="sidebar-note-list">
              <button v-for="note in unclassifiedNotes" :key="note.id" type="button" class="sidebar-note" :class="{ active: editorOpen && draft?.id === note.id, dragging: draggedNoteId === note.id }" draggable="true" @dragstart="startNoteDrag(note.id, $event)" @dragend="finishNoteDrag" @click="openSidebarNote(note)">
                <span class="sidebar-note-title"><FileTypeIcon :extension="note.file?.extension || note.content_kind" /><span>{{ note.title || '无标题笔记' }}</span></span>
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
          <div v-for="item in filteredTags" :key="item.id" class="pane-row-wrap tag-row" :class="{ 'action-pending': editingCategory === item.id }">
            <input v-if="editingCategory === item.id" v-model="editingCategoryName" class="category-rename-input" :aria-label="'编辑标签名称' + item.name" @keydown.enter.prevent="renameCategory('tags', item)" @keydown.esc="editingCategory = ''" />
            <div v-else class="pane-row tag-row-label"><span># {{ item.name }}</span></div>
            <template v-if="editingCategory === item.id"><button class="row-action confirm-edit" aria-label="确认修改" @click="renameCategory('tags', item)"><AppIcon name="check" /></button><button class="row-action confirm-cancel" aria-label="取消修改" @click="editingCategory = ''"><AppIcon name="close" /></button></template>
            <template v-else><button class="row-action" :aria-label="'编辑' + item.name" title="编辑" @click="startRenameCategory(item)"><AppIcon name="edit" /></button><button class="row-action" :aria-label="'删除' + item.name" title="删除" @click="deleteCategory('tags', item)"><AppIcon name="trash" /></button></template>
          </div>
          <div v-if="!filteredTags.length && newCategoryKind !== 'tags'" class="taxonomy-empty">暂无标签</div>
          </template>
        </div>
      </template>
      <template v-else>
        <div class="pane-heading"><h2>对话</h2><div class="pane-heading-actions"><button class="icon-button" title="新建对话" aria-label="新建对话" @click="() => newConversation()"><AppIcon name="plus" /></button><button class="icon-button" title="搜索对话" aria-label="搜索对话" :aria-expanded="conversationSearchOpen" @click="toggleConversationSearch"><AppIcon name="search" /></button></div></div>
        <input v-if="conversationSearchOpen" v-model="conversationQuery" class="conversation-search" aria-label="搜索会话" placeholder="搜索会话" />
        <div class="conversation-list">
          <div v-for="item in filteredConversations" :key="item.id" class="pane-row-wrap conversation-item" :class="{ active: activeConversationId === item.id || editingConversationId === item.id }">
            <input v-if="editingConversationId === item.id" v-model="editingConversationTitle" class="conversation-rename-input" :aria-label="'编辑对话标题' + item.title" @keydown.enter.prevent="renameConversation(item)" @keydown.esc="editingConversationId = ''" />
            <button v-else class="pane-row conversation-row" :class="{ active: activeConversationId === item.id }" @click="selectConversation(item.id)"><AppIcon name="spark" /><span>{{ item.title }}</span></button>
            <template v-if="editingConversationId === item.id"><button class="row-action confirm-edit" aria-label="确认修改" title="保存" @click="renameConversation(item)"><AppIcon name="check" /></button><button class="row-action confirm-cancel" aria-label="取消修改" title="取消" @click="editingConversationId = ''"><AppIcon name="close" /></button></template>
            <template v-else><button class="row-action" :aria-label="'编辑' + item.title" title="编辑" @click="startRenameConversation(item)"><AppIcon name="edit" /></button><button class="row-action" :aria-label="'删除' + item.title" title="删除" @click="deleteConversation(item)"><AppIcon name="trash" /></button></template>
          </div>
        </div>
      </template>
    </aside>

    <button v-if="view === 'notebooks' || view === 'assistant'" class="list-boundary-toggle" :class="{ open: listOpen }" :aria-label="listOpen ? '折叠列表' : '展开列表'" :title="listOpen ? '折叠列表' : '展开列表'" @click="toggleListPane"><AppIcon name="panel" /></button>

    <section ref="mainPane" class="main-pane" :class="{ 'calendar-main': view === 'calendar' }">
      <LinkDraftWorkspace v-if="activeLinkDraft" :key="activeLinkDraft.id" :draft="activeLinkDraft" :model-configured="modelConfigured" :notebooks="notebooks" :tags="tags" @close="closeLinkDraftWorkspace" @changed="onLinkDraftChanged" @updated="onLinkDraftUpdated" @published="onLinkDraftPublished" />
      <template v-else-if="editorOpen && (view === 'notes' || view === 'notebooks') && draft">
        <div class="note-editor">
          <header class="note-editor-header">
            <div class="note-editor-identity">
              <button class="icon-button editor-back" title="返回" aria-label="返回" @click="closeEditor"><AppIcon name="arrow-left" /></button>
              <span class="editor-file-icon"><FileTypeIcon :extension="draft.file?.extension || draft.content_kind" /></span>
              <input v-if="draft.file && draft.file.extension !== 'md'" v-model="draft.title" class="editor-file-name editor-file-name-input" aria-label="文件笔记标题" maxlength="240" />
              <span v-else class="editor-file-name">{{ draft.title || '无标题笔记' }}</span>
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
              <button v-if="!draft.file || draft.file.extension === 'md'" class="preview-toggle" :class="{ active: editorMode === 'preview' }" :aria-label="editorMode === 'preview' ? '返回编辑' : '预览 Markdown，链接和图片可点击'" :title="editorMode === 'preview' ? '返回编辑' : '预览 Markdown，链接和图片可点击'" :aria-pressed="editorMode === 'preview'" @click="editorMode = editorMode === 'write' ? 'preview' : 'write'; pushAppRoute()"><AppIcon name="eye" /></button>
              <button v-if="draft.id" class="editor-action-button" title="为本笔记设置提醒" aria-label="为本笔记设置提醒" @click="openReminderDialog(draft.id, draft.title)"><AppIcon name="bell" /></button>
              <button v-if="draft.id" class="editor-action-button" title="导出原格式" aria-label="导出原格式" @click="exportCurrentNote"><AppIcon name="export" /></button>
              <template v-if="draft.id">
                <button class="editor-action-button danger" title="删除笔记" aria-label="删除笔记" @click="deleteNote"><AppIcon name="trash" /></button>
              </template>
            </div>
          </header>
          <p v-if="draft.digest_sources_changed" class="digest-source-warning">本报告有 {{ draft.digest_sources_changed }} 处来源笔记已更新或删除；报告保留生成时的引用版本，请打开来源核对。</p>
          <div v-if="editorMode === 'write' && (!draft.file || draft.file.extension === 'md')" class="editor-toolbar-wrap">
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
              <button class="editor-tool" title="引用其他笔记" aria-label="引用其他笔记" @mousedown.prevent @click="openNoteReferencePicker"><AppIcon name="note" /></button>
              <button class="editor-tool" title="引用已有图片" aria-label="引用已有图片" @mousedown.prevent @click="openImagePicker"><AppIcon name="image" /></button>
              <button class="editor-tool" title="引用块" aria-label="引用块" @mousedown.prevent @click="applyEditorCommand('quote')"><AppIcon name="quote" /></button>
              <button class="editor-tool" title="代码块" aria-label="代码块" @mousedown.prevent @click="applyEditorCommand('code')"><AppIcon name="code" /></button>
            </div>
          </div>
          <main v-if="draft.file && draft.file.extension !== 'md'" class="editor-writing-area file-note-area">
            <ImageNoteEditor v-if="['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tif', 'tiff', 'ico'].includes(draft.file.extension)" :key="draft.id" :note-id="draft.id" :version="draft.version" @saved="refreshFileNote" />
            <div v-else-if="['docx', 'xlsx', 'pdf'].includes(draft.file.extension)" class="office-note-shell"><div v-if="draft.original_files?.length" class="original-file-links"><span>保留的原件：</span><a v-for="original in draft.original_files" :key="original.file_version" :href="`/v1/notes/${draft.id}/file?version=${original.file_version}&download=true`">下载 {{ original.filename }}</a></div><OfficeNoteEditor :key="draft.id" :note-id="draft.id" :extension="draft.file.extension" /></div>
            <div v-else class="unsupported-file"><p>{{ draft.file.extension.toUpperCase() }} 文件暂不支持站内编辑。</p><a :href="`/v1/notes/${draft.id}/file`">下载原件</a><label class="replace-file-button">上传编辑后的文件<input type="file" :accept="`.${draft.file.extension}`" @change="uploadNoteFile" /></label></div>
          </main>
          <main v-else class="editor-writing-area">
            <div class="editor-writing-page">
              <input ref="titleInput" v-model="draft.title" class="writing-title" maxlength="240" placeholder="无标题笔记" aria-label="笔记标题" />
              <a v-if="draft.source_url" class="note-source-link" :href="draft.source_url" target="_blank" rel="noopener noreferrer">来源网页：{{ draft.source_url }}</a>
              <p v-if="draft.file && draft.extraction_status === 'unsupported'" class="extraction-note">该文件没有可检索正文。</p>
              <div v-show="editorMode === 'write'" class="writing-body-layer">
                <textarea ref="bodyInput" v-model="draft.body_md" class="writing-body" :class="{ 'writing-body-with-links': hasEditableNoteReferences }" maxlength="100000" :placeholder="draft.file ? '该 Markdown 文件暂无可编辑正文' : '开始写作…'" aria-label="笔记内容" @scroll="syncBodyOverlay" @input="nextTick(syncBodyOverlay)" />
                <div v-if="hasEditableNoteReferences" class="writing-body-overlay" :style="{ width: `${bodyOverlayWidth}px` }" role="group" aria-label="正文中的笔记链接" @click="openNoteReferenceLink">
                  <div class="writing-body-overlay-content" :style="{ transform: `translateY(-${bodyOverlayScrollTop}px)` }"><template v-for="(part, index) in editableBodyParts" :key="index"><a v-if="part.noteId" class="note-reference-link" :href="`#/notes?note=${part.noteId}`" :aria-label="`打开引用笔记：${part.text}`">{{ part.text }}</a><span v-else aria-hidden="true">{{ part.text }}</span></template></div>
                </div>
              </div>
              <article v-if="editorMode === 'preview'" class="markdown-preview" v-html="previewHtml" @click="openNoteReferenceLink" />
            </div>
          </main>
        </div>
      </template>

      <template v-else-if="view === 'notes'">
        <WorkbenchHome
          v-model:search="workbenchSearch"
          :account-id="account.id"
          :daily="workbenchOverview.latest_daily"
          :weekly="workbenchOverview.latest_weekly"
          :reminders="reminders"
          :recent-note="workbenchOverview.recent_note"
          :archive="workbenchOverview.archive"
          :loading="workbenchLoading"
          :loaded="workbenchLoaded"
          :error="workbenchError"
          :busy="busy"
          :completing="completingWorkbenchReminders"
          @search="searchFromWorkbench"
          @create-note="createDraft"
          @open-note="openNote"
          @open-report="openWorkbenchReport"
          @open-history="openDigestHistory"
          @open-reminder="openReminderItem"
          @complete-reminder="completeWorkbenchReminder"
          @open-calendar="navigate('calendar')"
          @open-notebooks="navigate('notebooks')"
          @open-assistant="navigate('assistant')"
          @open-archive="openHomeArchive"
          @retry="loadReminderData().catch(showError)"
        />
      </template>

      <template v-else-if="view === 'notebooks'">
        <header class="page-head notebook-page-head"><h1>{{ notebooks.find(item => item.id === filterNotebook)?.name || (!filterTag ? '全部笔记' : '笔记') }}</h1><div class="page-head-actions notebook-head-actions"><button class="import-button" type="button" @click="openUploadPanel"><AppIcon name="upload" /><span>上传文件</span></button><button class="note-delete-notes-button" @click="toggleNoteSelectionMode"><AppIcon :name="selectingNotes ? 'close' : 'trash'" />{{ selectingNotes ? '取消' : '删除笔记' }}</button><button class="accent-button" @click="createDraft"><AppIcon name="plus" /> 新建笔记</button></div></header>
        <div class="content-width notebook-content">
          <div class="notebook-toolbar">
            <div v-if="selectingNotes" class="note-selection-controls">
              <label class="note-select-all"><input type="checkbox" :checked="visibleNotes.length > 0 && visibleNotes.every(note => visibleSelectedNoteIds.includes(note.id))" @change="toggleAllVisibleNotes" />全选</label>
              <span class="note-selection-count">已选 {{ visibleSelectedNoteIds.length }} 项</span>
              <button class="note-delete-notes-button selection-delete-button" :disabled="!visibleSelectedNoteIds.length || notesDeleting" @click="deleteSelectedNotes"><AppIcon name="trash" />删除笔记</button>
            </div>
            <div class="notebook-search-controls">
              <select v-model="searchMode" class="note-search-scope" aria-label="笔记搜索范围" @change="changeSearchMode"><option value="all">全部</option><option value="title">标题</option><option value="tag">标签</option></select>
              <form class="note-search-box" role="search" @submit.prevent="runSearch()"><button type="submit" aria-label="执行搜索"><AppIcon name="search" /></button><input v-model="searchQuery" :aria-label="searchMode === 'tag' ? '按标签名称搜索笔记' : searchMode === 'title' ? '按标题搜索笔记' : '搜索笔记标题或标签'" :placeholder="searchMode === 'tag' ? '输入标签名称' : searchMode === 'title' ? '搜索笔记标题' : '搜索标题或标签'" /></form>
            </div>
            <div class="notebook-view-actions">
              <button class="icon-button" :class="{ selected: cardLayout === 'grid' }" title="网格视图" aria-label="网格视图" @click="setCardLayout('grid')"><AppIcon name="grid" /></button>
              <button class="icon-button" :class="{ selected: cardLayout === 'list' }" title="列表视图" aria-label="列表视图" @click="setCardLayout('list')"><AppIcon name="list" /></button>
              <button class="icon-button" title="导出全部" aria-label="导出全部" @click="exportAllNotes"><AppIcon name="export" /></button>
              <button class="quiet-button" @click="toggleUpdatedSort">{{ updatedDesc ? '最近更新 ↓' : '最早更新 ↑' }}</button>
            </div>
          </div>
          <div v-if="searched" class="search-caption"><span>搜索结果 · 已显示 {{ results.length }} 条</span><button @click="clearSearch">清除搜索</button></div>
          <div class="note-grid" :class="{ 'as-list': cardLayout === 'list', 'empty-note-grid': !visibleNotes.length }">
            <article v-for="note in visibleNotes" :key="note.id" class="note-card" :class="{ dragging: draggedNoteId === note.id, 'note-selected': selectedNoteIds.includes(note.id) }" draggable="true" @dragstart="startNoteDrag(note.id, $event)" @dragend="finishNoteDrag">
              <div class="note-card-actions">
                <input v-if="selectingNotes" type="checkbox" :aria-label="`选择${note.title || '无标题笔记'}`" :checked="selectedNoteIds.includes(note.id)" @change="toggleNoteSelection(note.id)" />
                <button type="button" class="note-card-delete" :aria-label="`删除${note.title || '无标题笔记'}`" title="删除笔记" :disabled="notesDeleting" @click="deleteNoteFromCard(note)"><AppIcon name="trash" /></button>
              </div>
              <button type="button" class="note-card-open" @click="openNote(note.id)">
                <span class="note-card-heading"><span class="note-card-symbol"><FileTypeIcon :extension="note.file?.extension || note.content_kind" /></span><strong :title="note.title">{{ note.title || '无标题笔记' }}</strong></span>
                <span class="note-card-excerpt" :class="{ empty: !note.excerpt }" :title="note.excerpt">{{ note.excerpt || '暂无正文' }}</span>
                <span class="note-card-meta"><span class="note-card-notebook" :title="notebooks.find(item => item.id === note.notebook_id)?.name || '未分类'">{{ notebooks.find(item => item.id === note.notebook_id)?.name || '未分类' }}</span><span v-for="tagId in note.tag_ids.slice(0, 2)" :key="tagId" class="note-card-tag" :title="tagNames[tagId]">#{{ tagNames[tagId] || '标签' }}</span><span v-if="note.tag_ids.length > 2" class="note-card-tag-more" :title="note.tag_ids.slice(2).map(tagId => tagNames[tagId] || '标签').join('、')">+{{ note.tag_ids.length - 2 }}</span><time :datetime="note.updated_at">{{ formatDate(note.updated_at) }}</time></span>
              </button>
            </article>
            <div v-if="!visibleNotes.length" class="empty-state">{{ searched ? '没有匹配的笔记，试试其他搜索词' : '暂无笔记' }}</div>
          </div>
          <div v-if="(searched ? searchNextCursor : nextCursor)" class="list-end"><button class="quiet-button" :disabled="busy" @click="searched ? runSearch(true) : loadNotes(true)">加载更多</button></div>
        </div>
        <button type="button" class="notebook-back-to-top" aria-label="回到顶部" title="回到顶部" @click="scrollNotebookToTop"><AppIcon name="arrow-up" /></button>
      </template>

      <template v-else-if="view === 'assistant'"><header class="assistant-page-head"><h1>{{ activeConversation?.title || '新对话' }}</h1></header><AssistantPanel :key="activeConversationId" :conversation-id="activeConversationId" :messages="activeConversation?.messages || []" :loading="activeConversation?.loading || false" :model-name="currentModelName" :model-configured="modelConfigured" :trace-view-enabled="assistantTraceViewEnabled" @answered="handleAnswered" @conversation-changed="handleConversationChanged" @open-note="openNote" @configure-model="showModelSettings" @model-changed="currentModelName = $event" /></template>

      <template v-else-if="view === 'archive'">
        <header class="page-head"><h1>归档</h1></header>
        <div class="content-width archive-content">
          <div v-if="archivedNotes.length" class="archive-toolbar">
            <label><input type="checkbox" :checked="archivedNotes.length > 0 && archivedNotes.every(item => selectedArchiveIds.includes(item.id))" @change="toggleAllArchiveSelection" /><span>全选已加载</span></label>
            <div class="archive-toolbar-actions"><span v-if="selectedArchiveIds.length">已选 {{ selectedArchiveIds.length }} 项</span><button v-if="selectedArchiveIds.length" class="archive-purge-button" :disabled="archiveBusy" @click="purgeSelectedArchive"><AppIcon name="trash" />立即清除</button></div>
          </div>
          <div v-if="archivedNotes.length" class="archive-list">
            <article v-for="item in archivedNotes" :id="`archive-note-${item.id}`" :key="item.id" class="archive-item" :class="{ 'archive-item-focused': focusedArchiveId === item.id }">
              <input type="checkbox" :aria-label="`选择${item.title || '无标题笔记'}`" :checked="selectedArchiveIds.includes(item.id)" @change="toggleArchiveSelection(item.id)" />
              <span class="archive-item-icon"><FileTypeIcon :extension="item.file?.extension || item.content_kind" /></span>
              <div class="archive-item-info"><strong :title="item.title">{{ item.title || '无标题笔记' }}</strong><small>{{ item.file?.filename || item.excerpt || '笔记' }}</small><time :datetime="item.purge_at">{{ item.days_remaining ? `${item.days_remaining} 天后自动清除` : '即将自动清除' }}</time></div>
              <div class="archive-item-actions"><button class="archive-restore-button" :disabled="archiveBusy" @click="restoreArchivedNote(item)"><AppIcon name="undo" />恢复</button><button class="archive-purge-button" :disabled="archiveBusy" @click="purgeArchivedNote(item)"><AppIcon name="trash" />立即清除</button></div>
            </article>
          </div>
          <div v-else class="empty-state">归档为空</div>
          <div v-if="archiveNextCursor" class="list-end"><button class="quiet-button" :disabled="archiveBusy" @click="loadArchive(true).catch(showError)">加载更多</button></div>
        </div>
      </template>

      <template v-else-if="view === 'calendar'">
        <header class="page-head calendar-page-head">
          <h1>日程提醒</h1>
          <div class="calendar-head-actions">
            <div class="calendar-stat"><span class="calendar-stat-icon" aria-hidden="true"><AppIcon name="sun" /></span><span class="calendar-stat-copy">今日待办<strong>{{ todayOpenCount }}</strong></span></div>
            <div class="calendar-stat"><span class="calendar-stat-icon" aria-hidden="true"><AppIcon name="clock" /></span><span class="calendar-stat-copy">未来 7 天<strong>{{ weekDueCount }}</strong></span></div>
            <div class="calendar-stat"><span class="calendar-stat-icon" aria-hidden="true"><AppIcon name="check" /></span><span class="calendar-stat-copy">本月已完成<strong>{{ monthDoneCount }}</strong></span></div>
            <button class="accent-button" @click="openReminderDialog()"><AppIcon name="plus" /> 新建提醒</button>
          </div>
        </header>
        <div class="content-width calendar-content">
          <div class="calendar-layout">
            <div class="calendar-card">
              <div class="calendar-toolbar"><h2>{{ calendarDate.getFullYear() }} 年 {{ calendarDate.getMonth() + 1 }} 月</h2><div><button class="icon-button" aria-label="上个月" @click="changeMonth(-1)">‹</button><button class="icon-button" aria-label="回到本月" @click="goToToday">今</button><button class="icon-button" aria-label="下个月" @click="changeMonth(1)">›</button></div></div>
              <div class="calendar-grid">
                <span v-for="day in ['日','一','二','三','四','五','六']" :key="day" class="week-day">{{ day }}</span>
                <button v-for="(day, index) in calendarDays" :key="index" class="calendar-day" :class="{ today: day === new Date().getDate() && calendarDate.getMonth() === new Date().getMonth() && calendarDate.getFullYear() === new Date().getFullYear(), selected: calendarDayPanelOpen && day === selectedDay }" :aria-pressed="Boolean(day && calendarDayPanelOpen && day === selectedDay)" :disabled="!day" @click="day && selectCalendarDay(day)">
                  <span v-if="day" class="calendar-day-head"><strong>{{ day }}</strong><small v-if="calendarDayCounts[calendarDayKey(day)]">{{ calendarDayCounts[calendarDayKey(day)] }}</small></span>
                  <span v-if="day" class="calendar-day-previews">
                    <span v-for="item in calendarDayPreview(day)" :key="item.id" class="calendar-preview" :class="{ done: item.status === 'done' }" :title="item.text"><i aria-hidden="true" /> <span>{{ item.text }}</span></span>
                    <span v-if="calendarDayItems(day).length > 3" class="calendar-preview-more" :title="calendarDayItems(day).slice(2).map(item => item.text).join('\n')">还有 {{ calendarDayItems(day).length - 2 }} 条…</span>
                  </span>
                </button>
              </div>
            </div>
            <aside class="event-panel calendar-day-panel" aria-label="日程详情">
              <template v-if="calendarDayPanelOpen">
              <div class="reminder-section-head"><h2>{{ calendarDate.getMonth() + 1 }} 月 {{ selectedDay }} 日 · {{ selectedWeekday }}</h2><div class="calendar-panel-actions"><button class="calendar-panel-add" @click="openReminderDialog()"><AppIcon name="plus" /> 新建提醒</button><button class="icon-button" aria-label="关闭日期提醒" @click="closeCalendarDayPanel"><AppIcon name="close" /></button></div></div>
              <div class="calendar-panel-tabs" role="group" aria-label="筛选当天提醒">
                <button :class="{ active: calendarStatusFilter === 'all' }" :aria-pressed="calendarStatusFilter === 'all'" @click="calendarStatusFilter = 'all'">全部 <span>{{ selectedEvents.length }}</span></button>
                <button :class="{ active: calendarStatusFilter === 'open' }" :aria-pressed="calendarStatusFilter === 'open'" @click="calendarStatusFilter = 'open'">未完成 <span>{{ selectedOpenEvents.length }}</span></button>
                <button :class="{ active: calendarStatusFilter === 'done' }" :aria-pressed="calendarStatusFilter === 'done'" @click="calendarStatusFilter = 'done'">已完成 <span>{{ selectedDoneEvents.length }}</span></button>
                <span v-if="filteredSelectedEvents.length > 4" class="calendar-scroll-hint calendar-selected-hint">向下滚动查看更多</span>
              </div>
              <div class="calendar-selected-list" role="region" aria-label="当天提醒列表" tabindex="0">
                <div v-for="item in filteredSelectedEvents" :key="item.id" class="calendar-selected-item" :class="{ done: item.status === 'done', 'reminder-focused': focusedReminderId === item.id }">
                  <button class="calendar-status-toggle" :class="{ done: item.status === 'done' }" :aria-label="`${item.status === 'done' ? '恢复未完成' : '标记完成'}：${item.text}`" @click="setReminderStatus(item, item.status === 'done' ? 'open' : 'done')"><AppIcon v-if="item.status === 'done'" name="check" /></button>
                  <button class="calendar-selected-main" @click="openReminderItem(item)"><strong :title="item.text">{{ item.text }}</strong><span><time :datetime="item.due_at">{{ reminderTime(item.due_at) }}</time><em :title="item.note_title || '独立提醒'">{{ item.note_title ? `关联笔记 · ${item.note_title}` : '独立提醒' }}</em></span></button>
                  <div class="calendar-selected-actions"><button class="quiet-button" @click="postponeReminder(item)">延期</button><button class="icon-button" :aria-label="`取消：${item.text}`" @click="cancelReminder(item)"><AppIcon name="trash" /></button></div>
                </div>
                <div v-if="!filteredSelectedEvents.length" class="calendar-panel-empty">当天暂无{{ calendarStatusFilter === 'all' ? '' : calendarStatusFilter === 'done' ? '已完成' : '未完成' }}提醒</div>
              </div>
              </template>
              <div v-else class="calendar-panel-prompt"><AppIcon name="calendar" /><p>选择日历中的日期，查看当天提醒</p></div>
              <section class="calendar-upcoming" aria-label="即将到期提醒">
                <div class="calendar-upcoming-head"><h3>即将到期</h3><span v-if="upcomingReminders.length > 6" class="calendar-scroll-hint">向下滚动查看更多</span></div>
                <div v-if="upcomingReminders.length" class="calendar-upcoming-grid" role="region" aria-label="即将到期提醒列表" tabindex="0">
                  <button v-for="item in upcomingReminders" :key="item.id" class="calendar-upcoming-card" @click="openReminderItem(item)">
                    <span class="calendar-upcoming-icon"><AppIcon :name="item.note_id ? 'note' : 'bell'" /></span>
                    <strong :title="item.text">{{ item.text }}</strong>
                    <small>{{ formatDate(item.due_at) }}</small>
                    <span class="calendar-upcoming-source" :title="item.note_title || '独立提醒'">{{ item.note_title || '独立提醒' }}</span>
                  </button>
                </div>
                <p v-else class="calendar-upcoming-empty">暂无即将到期的提醒</p>
              </section>
            </aside>
          </div>
        </div>
      </template>
      <template v-else-if="view === 'weekly'"><WeeklyReportsPage :initial-kind="digestHistoryKind" @open-note="openNote" @open-archive="navigate('archive')" /></template>
    </section>
    <div v-if="profileDialog" class="profile-dialog-backdrop settings-screen" @click.self="closeSettingsDialog">
      <section class="profile-dialog settings-window" role="dialog" aria-modal="true" aria-label="设置">
        <aside class="settings-sidebar">
          <h1>设置</h1>
          <label class="settings-search"><AppIcon name="search" /><input v-model="settingsSearch" type="search" placeholder="搜索" aria-label="搜索设置" /></label>
          <nav class="settings-nav" aria-label="设置分类">
            <template v-for="group in ['个人', '集成']" :key="group">
              <h2 v-if="visibleSettingsItems.some(item => item.group === group)" class="settings-nav-group">{{ group }}</h2>
              <button v-for="item in visibleSettingsItems.filter(item => item.group === group)" :key="item.id" :class="{ active: activeSettingsSection === item.id }" :aria-current="activeSettingsSection === item.id ? 'page' : undefined" @click="setSettingsSection(item.id)">
                <AppIcon :name="item.id === 'profile' ? 'home' : 'spark'" /><span>{{ item.name }}</span>
              </button>
            </template>
            <p v-if="!visibleSettingsItems.length" class="settings-no-results">没有匹配的设置</p>
          </nav>
        </aside>
        <main class="settings-content">
          <button class="settings-close icon-button" aria-label="关闭设置" @click="closeSettingsDialog"><AppIcon name="close" /></button>
          <section v-if="activeSettingsSection === 'profile'" class="settings-section">
            <h2 class="settings-page-title">个人信息</h2>
            <div class="settings-section-heading"><h3>账户</h3></div>
            <div class="settings-card">
              <div class="profile-setting-row"><div><strong>邮箱</strong><small>当前登录账号</small></div><span class="settings-value">{{ account?.email }}</span></div>
            </div>
          </section>
          <section v-else-if="activeSettingsSection === 'model'" class="settings-section">
            <h2 class="settings-page-title">模型配置</h2>
            <div class="settings-section-heading"><h3>AI 连接</h3></div>
            <div class="settings-card model-settings-card">
              <p class="settings-card-description">连接模型后可使用知识库问答、笔记分析与分类建议。AI 对话会检索本人笔记并显示可打开的来源引用。</p>
              <ModelConnectionSettings @status="modelConfigured = $event; void loadModelConnection()" />
            </div>
          </section>
        </main>
      </section>
    </div>
    <ReminderDialog v-if="reminderDialog" :initial-date="reminderDialog.initialDate" :fixed-note-id="reminderDialog.fixedNoteId" :fixed-note-title="reminderDialog.fixedNoteTitle" @close="reminderDialog = null" @saved="reminderSaved" />
    <UploadPanel :visible="uploadPanelOpen" :notebook-id="filterNotebook || null" :account-id="account?.id || null" @close="closeUploadPanel" @updated="void afterUploadUpdated()" @open-note="id => { uploadPanelOpen = false; void openNote(id) }" @open-link-draft="openUploadLinkDraft" @notice="notice = $event" />
    <MarkdownImagePicker v-if="imagePickerOpen" @close="closeImagePicker" @select="insertExistingImage" @url="insertImageUrlPlaceholder" />
    <NoteReferencePicker v-if="noteReferencePickerOpen" :current-note-id="draft?.id || ''" @close="closeNoteReferencePicker" @select="insertNoteReference" />
    <div v-if="templatePickerOpen" class="template-picker-backdrop" @click.self="templatePickerOpen = false">
      <section class="template-picker" role="dialog" aria-modal="true" aria-labelledby="template-picker-title">
        <header class="template-picker-header"><div><h2 id="template-picker-title">选择笔记模板</h2><p>选中模板查看预览，确认后再创建笔记。</p></div><button type="button" class="icon-button" aria-label="关闭模板选择" @click="templatePickerOpen = false"><AppIcon name="close" /></button></header>
        <div class="template-picker-layout">
          <section class="template-picker-library" aria-label="模板列表">
            <nav class="template-picker-tabs" aria-label="模板分类">
              <button type="button" :class="{ active: templateTab === 'preset' }" :aria-pressed="templateTab === 'preset'" @click="selectTemplateTab('preset')">预设模板<span>{{ builtinTemplates().length + 1 }}</span></button>
              <button type="button" :class="{ active: templateTab === 'mine' }" :aria-pressed="templateTab === 'mine'" @click="selectTemplateTab('mine')">我的模板<span>{{ customTemplates.length }}</span></button>
            </nav>
            <div v-if="templateTab === 'preset'" class="template-picker-body">
              <div class="template-choice-grid">
                <button v-for="template in builtinTemplates()" :key="template.id" type="button" class="template-choice" :class="{ selected: selectedTemplate?.id === template.id }" :aria-pressed="selectedTemplate?.id === template.id" @click="chooseTemplate(template)"><span class="template-choice-icon"><AppIcon :name="template.id === 'builtin-daily' ? 'calendar' : template.id === 'builtin-meeting' ? 'checklist' : template.id === 'builtin-course' ? 'book' : 'note'" /></span><strong>{{ template.name }}</strong><small>{{ template.id === 'builtin-essay' ? '记录灵感、想法和日常片段' : template.id === 'builtin-daily' ? '计划、回顾与明日待办' : template.id === 'builtin-meeting' ? '讨论内容、决议和后续事项' : '课程信息、重点与复习清单' }}</small><span v-if="selectedTemplate?.id === template.id" class="template-choice-check"><AppIcon name="check" /></span></button>
                <button type="button" class="template-choice template-choice-blank" :class="{ selected: selectedTemplate?.id === 'builtin-blank' }" :aria-pressed="selectedTemplate?.id === 'builtin-blank'" @click="chooseTemplate({ id: 'builtin-blank', name: '空白笔记', title: '', body_md: '' })"><span class="template-choice-icon"><AppIcon name="plus" /></span><strong>空白笔记</strong><small>从空白页面开始写作</small><span v-if="selectedTemplate?.id === 'builtin-blank'" class="template-choice-check"><AppIcon name="check" /></span></button>
              </div>
            </div>
            <div v-else class="template-picker-body">
              <div v-if="pagedCustomTemplates.length" class="template-choice-grid template-custom-grid">
                <article v-for="template in pagedCustomTemplates" :key="template.id" class="template-choice template-custom-card" :class="{ selected: selectedTemplate?.id === template.id }">
                  <button type="button" class="template-custom-card-select" :aria-pressed="selectedTemplate?.id === template.id" @click="chooseTemplate(template)"><span class="template-choice-icon"><AppIcon name="note" /></span><strong :title="template.name">{{ template.name }}</strong><small>{{ template.title || '空白模板' }}</small><span v-if="selectedTemplate?.id === template.id" class="template-choice-check"><AppIcon name="check" /></span></button>
                  <div class="template-custom-card-actions"><button type="button" :aria-label="`编辑模板标题${template.name}`" title="编辑标题" @click="renameNoteTemplate(template)"><AppIcon name="edit" /></button><button type="button" :aria-label="`删除模板${template.name}`" title="删除模板" @click="deleteNoteTemplate(template)"><AppIcon name="trash" /></button></div>
                </article>
              </div>
              <div v-else class="template-custom-empty">还没有导入模板。导入 Markdown 文件后，就能在这里反复使用。</div>
              <nav v-if="customTemplatePageCount > 1" class="template-pagination" aria-label="我的模板分页"><button type="button" :disabled="customTemplatePage <= 1" @click="customTemplatePage -= 1; selectedTemplate = pagedCustomTemplates[0] || null">上一页</button><span>{{ customTemplatePage }} / {{ customTemplatePageCount }}</span><button type="button" :disabled="customTemplatePage >= customTemplatePageCount" @click="customTemplatePage += 1; selectedTemplate = pagedCustomTemplates[0] || null">下一页</button></nav>
            </div>
          </section>
          <aside class="template-preview-panel" aria-label="模板预览">
            <div class="template-preview-heading"><span>模板预览</span><small>{{ selectedTemplate ? (selectedTemplate.id.startsWith('builtin-') ? '预设模板' : '我的模板') : '未选择' }}</small></div>
            <div v-if="selectedTemplate" class="template-preview-document">
              <span class="template-preview-paper-mark"><AppIcon name="note" /></span>
              <h3>{{ selectedTemplate.title || selectedTemplate.name || '无标题笔记' }}</h3>
              <article v-if="selectedTemplate.body_md" class="template-preview-content markdown-preview" v-html="selectedTemplatePreviewHtml" />
              <p v-else class="template-preview-placeholder">空白正文</p>
            </div>
            <div v-else class="template-preview-empty">选择左侧卡片，预览笔记标题和正文结构。</div>
          </aside>
        </div>
        <footer class="template-picker-footer">
          <div class="template-picker-footer-left"><label class="template-import-button" :class="{ busy: templateImporting }"><input ref="templateImportInput" type="file" accept=".md,text/markdown" :disabled="templateImporting" @change="importNoteTemplate" /><AppIcon name="upload" />{{ templateImporting ? '正在导入…' : '导入 Markdown 模板' }}</label><span>支持 .md 文件 · 正文最多 100000 个字符</span></div>
          <div class="template-picker-footer-actions"><button type="button" class="quiet-button" @click="templatePickerOpen = false">取消</button><button type="button" class="accent-button" :disabled="!selectedTemplate" @click="createDraftFromTemplate(selectedTemplate)">确认使用该模版</button></div>
        </footer>
      </section>
    </div>
    <ConfirmationDialog />
    <div v-if="error || notice" class="toast" :class="{ error: !!error }" role="status" @click="error = ''; notice = ''">{{ error || notice }} <span>×</span></div>
  </main>
</template>
