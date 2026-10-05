<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { askForConfirmation } from './confirmation'
import AppIcon from './AppIcon.vue'

type NoteResult = { id: string; title: string; index_status: string; indexed_chunks?: number; file?: { extraction_status?: string; extraction_error?: string | null; is_current_version?: boolean } | null }
type LinkDraft = { id: string; title: string; source_url: string; snapshot_text: string; body_md: string; fetch_status: string; fetch_error: string | null; status: string; notebook_id: string | null }
type Session = { id: string; status: string; filename: string; size_bytes: number; sha256: string; part_size: number; part_count: number; uploaded_parts: { part_number: number }[]; expires_at: string; created_at?: string; note_id: string | null; duplicate_note_id: string | null; last_error: string | null; note?: NoteResult; duplicate?: { id: string; title: string } | null }
type TaskStatus = 'queued' | 'hashing' | 'uploading' | 'verifying' | 'extracting' | 'paused' | 'complete' | 'duplicate' | 'error' | 'cancelled'
type FileTask = { key: string; idempotencyKey: string; file: File | null; filename: string; size: number; sha256: string; sessionId: string; status: TaskStatus; progress: number; createdAt: string; note: NoteResult | null; duplicate: { id: string; title: string } | null; error: string; abort: AbortController | null }

const props = defineProps<{ visible: boolean; notebookId: string | null; accountId: string | null }>()
const emit = defineEmits<{
  (event: 'close'): void
  (event: 'updated'): void
  (event: 'open-note', noteId: string): void
  (event: 'open-link-draft', draft: LinkDraft): void
  (event: 'notice', message: string): void
}>()

const mode = ref<'files' | 'link'>('files')
const tasks = ref<FileTask[]>([])
const titleQuery = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const fileType = ref('all')
const currentPage = ref(1)
const PAGE_SIZE = 5
const input = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const linkUrl = ref('')
const linkBusy = ref(false)
const linkError = ref('')
const linkNotice = ref('')
const linkDrafts = ref<LinkDraft[]>([])
const activeUploads = ref(0)
const MAX_PARALLEL = 3
const supported = '.md,.docx,.xlsx,.pdf,.png,.jpg,.jpeg,.gif,.bmp,.webp,.tif,.tiff,.ico,.doc,.xls'
const imageExtensions = new Set(['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tif', 'tiff', 'ico'])
const hasActive = computed(() => tasks.value.some(item => ['hashing', 'uploading', 'verifying', 'extracting'].includes(item.status)))
const sortedTasks = computed(() => tasks.value
  .map((task, index) => ({ task, index }))
  .sort((a, b) => new Date(b.task.createdAt).getTime() - new Date(a.task.createdAt).getTime() || b.index - a.index)
  .map(({ task }) => task))
const filteredTasks = computed(() => {
  const query = titleQuery.value.trim().toLocaleLowerCase()
  return sortedTasks.value.filter(task => {
    const nameMatches = !query || task.filename.toLocaleLowerCase().includes(query)
    const taskDate = localDateKey(task.createdAt)
    const fromMatches = !dateFrom.value || taskDate >= dateFrom.value
    const toMatches = !dateTo.value || taskDate <= dateTo.value
    const extension = getExtension(task.filename)
    const typeMatches = fileType.value === 'all' || (fileType.value === 'image' ? imageExtensions.has(extension) : extension === fileType.value)
    return nameMatches && fromMatches && toMatches && typeMatches
  })
})
const pageCount = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / PAGE_SIZE)))
const pagedTasks = computed(() => filteredTasks.value.slice((currentPage.value - 1) * PAGE_SIZE, currentPage.value * PAGE_SIZE))
watch([titleQuery, dateFrom, dateTo, fileType], () => { currentPage.value = 1 })
watch(dateFrom, start => {
  if (start && dateTo.value && start > dateTo.value) dateTo.value = start
})
watch(dateTo, end => {
  if (end && dateFrom.value && end < dateFrom.value) dateFrom.value = end
})
watch(pageCount, count => { if (currentPage.value > count) currentPage.value = count })

function storageKey() { return `pkm-upload-sessions:${props.accountId || 'anonymous'}` }
function dismissedKey() { return `pkm-upload-dismissed:${props.accountId || 'anonymous'}` }
function pendingQueueKey() { return `pkm-upload-pending:${props.accountId || 'anonymous'}` }
function readDismissedSessions(): string[] {
  try { return JSON.parse(localStorage.getItem(dismissedKey()) || '[]') as string[] } catch { return [] }
}
function readLocalSessions(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(storageKey()) || '{}') as Record<string, string> } catch { return {} }
}
function writeLocalSession(idempotencyKey: string, sessionId: string) {
  const entries = readLocalSessions(); entries[idempotencyKey] = sessionId
  localStorage.setItem(storageKey(), JSON.stringify(entries))
}
function dropLocalSession(idempotencyKey: string) {
  const entries = readLocalSessions(); delete entries[idempotencyKey]
  localStorage.setItem(storageKey(), JSON.stringify(entries))
}

function persistPendingTasks() {
  const pending = tasks.value
    .filter(item => !['complete', 'duplicate', 'cancelled'].includes(item.status))
    .map(({ file: _file, abort: _abort, ...item }) => item)
  try { localStorage.setItem(pendingQueueKey(), JSON.stringify(pending)) } catch { /* 本地存储不可用时，服务端上传会话仍可恢复。 */ }
}

function restorePendingTasks() {
  try {
    const saved = JSON.parse(localStorage.getItem(pendingQueueKey()) || '[]') as Omit<FileTask, 'file' | 'abort'>[]
    for (const task of saved) {
      if (tasks.value.some(item => item.key === task.key || (task.sessionId && item.sessionId === task.sessionId))) continue
      tasks.value.push({ ...task, file: null, abort: null, status: task.status === 'error' ? 'error' : 'paused' })
    }
  } catch { /* 丢弃无法读取的本地队列快照。 */ }
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { credentials: 'same-origin', ...init })
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    let payload: unknown
    try {
      payload = await response.json()
      const value = payload as { detail?: unknown }
      if (typeof value.detail === 'string') detail = value.detail
      else if (value.detail) detail = JSON.stringify(value.detail)
    } catch { /* 使用状态文本。 */ }
    const error = new Error(detail) as Error & { status?: number; payload?: unknown }
    error.status = response.status
    error.payload = payload
    throw error
  }
  return response.status === 204 ? undefined as T : await response.json() as T
}

async function completeSession(session: Session, signal?: AbortSignal) {
  let result = await request<{ status: string; note?: NoteResult; duplicate?: { id: string; title: string } }>(`/v1/file-uploads/sessions/${session.id}/complete`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parts: Array.from({ length: session.part_count }, (_, index) => index + 1) }), signal,
  })
  for (let attempt = 0; result.status === 'completing' && attempt < 90; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 1500))
    const refreshed = await request<Session>(`/v1/file-uploads/sessions/${session.id}`, { signal })
    if (refreshed.status === 'completed') result = { status: 'completed', note: refreshed.note }
    else if (refreshed.status === 'duplicate') result = { status: 'duplicate', duplicate: refreshed.duplicate || undefined }
    else result = { status: refreshed.status }
  }
  return result
}

async function sha256(file: File) {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

function hydrate(session: Session) {
  const old = tasks.value.find(item => item.sessionId === session.id)
  if (old) {
    old.note = session.note || old.note
    old.duplicate = session.duplicate || old.duplicate
    old.progress = session.part_count ? Math.floor(session.uploaded_parts.length / session.part_count * 100) : 0
    return old
  }
  const task: FileTask = {
    key: session.id,
    idempotencyKey: '',
    file: null,
    filename: session.filename,
    size: session.size_bytes,
    sha256: session.sha256,
    sessionId: session.id,
    status: session.status === 'completed' ? 'extracting' : session.status === 'duplicate' ? 'duplicate' : session.status === 'failed' ? 'error' : 'paused',
    progress: session.status === 'completed' ? 100 : session.part_count ? Math.floor(session.uploaded_parts.length / session.part_count * 100) : 0,
    createdAt: session.created_at || new Date().toISOString(),
    note: session.note || null,
    duplicate: session.duplicate || null,
    error: session.last_error || (session.status === 'failed' ? '上传未完成，请重新选择文件重试' : ''),
    abort: null,
  }
  tasks.value.unshift(task)
  return task
}

async function loadSessions() {
  try {
    const result = await request<{ items: Session[] }>('/v1/file-uploads/sessions')
    for (const session of result.items) {
      if (readDismissedSessions().includes(session.id)) continue
      const task = hydrate(session)
      if (session.status === 'completed' && !['complete', 'duplicate'].includes(task.status)) {
        task.status = 'extracting'
        void pollRecognition(task)
      } else if (session.status === 'failed') {
        task.status = 'error'
        task.error = session.last_error || '上传未完成，请重新选择文件重试'
      }
    }
  } catch { /* 登录状态失效时，应用会在下次上传操作中显示认证错误。 */ }
}

async function loadLinkDrafts() {
  try { linkDrafts.value = (await request<{ items: LinkDraft[] }>('/v1/link-drafts')).items } catch { linkDrafts.value = [] }
}

async function deleteLinkDraft(item: LinkDraft) {
  const confirmed = await askForConfirmation({ message: `删除网页草稿“${item.title || item.source_url}”？`, title: '删除网页草稿', confirmLabel: '删除', danger: true })
  if (!confirmed) return
  try {
    await request(`/v1/link-drafts/${item.id}`, { method: 'DELETE' })
    linkDrafts.value = linkDrafts.value.filter(draft => draft.id !== item.id)
    emit('notice', '网页草稿已删除')
  } catch (cause) {
    emit('notice', cause instanceof Error ? cause.message : '删除网页草稿失败')
  }
}

function addFiles(list: FileList | File[]) {
  const files = Array.from(list)
  for (const file of files) {
    const resumable = tasks.value.find(item => ['paused', 'error'].includes(item.status) && !item.file && !item.note?.id && item.filename === file.name && item.size === file.size)
    if (resumable) {
      if (resumable.status === 'error' && !resumable.note?.id) {
        dropLocalSession(resumable.idempotencyKey)
        resumable.idempotencyKey = crypto.randomUUID()
        resumable.sessionId = ''
      }
      resumable.file = file
      resumable.status = 'queued'
      resumable.error = ''
      continue
    }
    const key = crypto.randomUUID()
    tasks.value.push({ key, idempotencyKey: key, file, filename: file.name, size: file.size, sha256: '', sessionId: '', status: 'queued', progress: 0, createdAt: new Date().toISOString(), note: null, duplicate: null, error: '', abort: null })
  }
  void drainQueue()
}

async function onInput(event: Event) {
  const element = event.target as HTMLInputElement
  if (element.files?.length) addFiles(element.files)
  element.value = ''
}

function onDrop(event: DragEvent) {
  dragging.value = false
  if (event.dataTransfer?.files.length) addFiles(event.dataTransfer.files)
}

async function drainQueue() {
  while (activeUploads.value < MAX_PARALLEL) {
    const task = tasks.value.find(item => item.status === 'queued' && item.file)
    if (!task) return
    activeUploads.value += 1
    void uploadTask(task).finally(() => { activeUploads.value -= 1; void drainQueue() })
  }
}

async function uploadTask(task: FileTask) {
  const file = task.file
  if (!file) { task.status = 'paused'; return }
  task.error = ''; task.abort = new AbortController()
  try {
    task.status = 'hashing'
    task.sha256 = await sha256(file)
    if (isCancelled(task)) return

    let session: Session | null = null
    const localId = readLocalSessions()[task.idempotencyKey]
    if (localId) {
      try { session = await request<Session>(`/v1/file-uploads/sessions/${localId}`) } catch (cause) {
        session = null
        if ((cause as Error & { status?: number }).status === 410) {
          dropLocalSession(task.idempotencyKey)
          task.idempotencyKey = crypto.randomUUID()
        }
      }
    }
    if (!session) {
      const resumable = await request<{ items: Session[] }>('/v1/file-uploads/sessions')
      session = resumable.items.find(item => ['uploading', 'completing', 'completed'].includes(item.status) && item.sha256 === task.sha256 && item.size_bytes === file.size && item.filename === file.name) || null
    }
    if (session && ['failed', 'expired', 'cancelled'].includes(session.status)) {
      dropLocalSession(task.idempotencyKey)
      task.idempotencyKey = crypto.randomUUID()
      task.sessionId = ''
      session = null
    }

    if (!session) {
      const extension = file.name.split('.').pop()?.toLowerCase()
      const convertLegacy = ['doc', 'xls'].includes(extension || '')
        ? await askForConfirmation({ message: '此旧版 Office 文件需要转换为 DOCX/XLSX，原件会保留供下载。继续上传并转换吗？', title: '转换旧版 Office 文件', confirmLabel: '转换并上传' })
        : false
      if (['doc', 'xls'].includes(extension || '') && !convertLegacy) { task.status = 'cancelled'; return }
      try {
        session = await request<Session>('/v1/file-uploads/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Idempotency-Key': task.idempotencyKey },
          body: JSON.stringify({ filename: file.name, size_bytes: file.size, sha256: task.sha256, notebook_id: props.notebookId, convert_legacy: convertLegacy }),
          signal: task.abort.signal,
        })
      } catch (cause) {
        const error = cause as Error & { status?: number; payload?: { detail?: { code?: string; title?: string; filename?: string; note_id?: string } } }
        const detail = error.payload?.detail
        if (error.status === 409 && detail?.code === 'duplicate_file') {
          task.duplicate = { id: detail.note_id || '', title: detail.title || detail.filename || '已有文件' }
          task.status = 'duplicate'; emit('updated'); return
        }
        throw cause
      }
    }
    if (!session) throw new Error('无法创建上传会话，请稍后重试')
    const sessionId = session.id
    task.sessionId = sessionId
    localStorage.setItem(dismissedKey(), JSON.stringify(readDismissedSessions().filter(id => id !== sessionId)))
    writeLocalSession(task.idempotencyKey, sessionId)
    if (session.status === 'completed') {
      task.note = session.note || null; task.status = 'extracting'; await pollRecognition(task); return
    }
    if (session.status === 'duplicate') {
      task.duplicate = session.duplicate || null; task.status = 'duplicate'; dropLocalSession(task.idempotencyKey); return
    }
    if (session.status === 'completing') {
      task.status = 'verifying'
      const result = await completeSession(session, task.abort.signal)
      if (result.status === 'duplicate') {
        task.duplicate = result.duplicate || null; task.status = 'duplicate'; task.progress = 100
        dropLocalSession(task.idempotencyKey); emit('updated'); return
      }
      if (result.status !== 'completed' || !result.note) throw new Error('文件仍在保存，请稍后重试查询上传状态')
      task.note = result.note; task.progress = 100; task.status = 'extracting'
      emit('updated')
      await pollRecognition(task)
      return
    }
    session = await request<Session>(`/v1/file-uploads/sessions/${session.id}`)
    if (session.status === 'completed') {
      task.note = session.note || null; task.progress = 100; task.status = 'extracting'
      await pollRecognition(task); return
    }
    if (session.status !== 'uploading') throw new Error(session.last_error || '上传会话已失效，请重新选择文件重试')
    const finishedParts = new Set(session.uploaded_parts.map(part => part.part_number))
    task.status = 'uploading'
    for (let part = 1; part <= session.part_count; part += 1) {
      if (isCancelled(task)) return
      if (finishedParts.has(part)) continue
      const start = (part - 1) * session.part_size
      const end = Math.min(file.size, start + session.part_size)
      let sent = false
      let lastError: unknown
      for (let attempt = 0; attempt < 3 && !sent; attempt += 1) {
        try {
          const target = await request<{ url: string }>(`/v1/file-uploads/sessions/${session.id}/parts/${part}/url`, { method: 'POST', signal: task.abort.signal })
          const uploaded = await fetch(target.url, { method: 'PUT', body: file.slice(start, end), signal: task.abort.signal })
          if (!uploaded.ok) throw new Error(`分块上传失败（${uploaded.status}）`)
          const etag = uploaded.headers.get('ETag')
          if (!etag) throw new Error('对象存储未返回分块校验值')
          await request(`/v1/file-uploads/sessions/${session.id}/parts/${part}/receipt`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ etag, size_bytes: end - start }), signal: task.abort.signal,
          })
          sent = true
          task.progress = Math.floor((finishedParts.size + 1) / session.part_count * 100)
          finishedParts.add(part)
        } catch (cause) { lastError = cause }
      }
      if (!sent) throw lastError instanceof Error ? lastError : new Error('分块上传失败')
    }
    task.status = 'verifying'
    const result = await completeSession(session, task.abort.signal)
    if (result.status === 'duplicate') {
      task.duplicate = result.duplicate || null; task.status = 'duplicate'; task.progress = 100
      dropLocalSession(task.idempotencyKey); emit('updated'); return
    }
    if (!result.note) throw new Error('文件已上传，但服务端仍在完成保存；稍后可在恢复列表中查看')
    task.note = result.note; task.progress = 100; task.status = 'extracting'
    emit('updated')
    await pollRecognition(task)
  } catch (cause) {
    if (task.status === 'cancelled' || task.abort?.signal.aborted) return
    task.status = 'error'
    task.error = cause instanceof Error ? cause.message : '上传失败，请重试'
  } finally { task.abort = null }
}

async function pollRecognition(task: FileTask) {
  if (!task.sessionId) return
  for (let attempt = 0; attempt < 90; attempt += 1) {
    try {
      const session = await request<Session>(`/v1/file-uploads/sessions/${task.sessionId}`)
      if (session.status === 'failed') {
        task.status = 'error'
        task.error = session.last_error || '文件上传未完成，请重新选择文件重试'
        emit('updated')
        return
      }
      task.note = session.note || task.note
      const extraction = session.note?.file?.extraction_status
      const extractionDone = extraction && ['ready', 'partial', 'empty', 'unsupported', 'needs_vision', 'error', 'preserved'].includes(extraction)
      const currentFile = session.note?.file?.is_current_version !== false
      const indexingDone = ['ready', 'error', 'superseded'].includes(session.note?.index_status || '')
      if (extractionDone && (!currentFile || indexingDone)) {
        task.note = session.note || task.note
        task.status = currentFile && (extraction === 'error' || extraction === 'needs_vision' || extraction === 'partial' || session.note?.index_status === 'error') ? 'error' : 'complete'
        task.error = task.status === 'error' ? session.note?.file?.extraction_error || '文件已保存，可重试识别或向量索引' : ''
        task.progress = 100
        if (task.status === 'complete') dropLocalSession(task.idempotencyKey)
        emit('updated')
        return
      }
    } catch { /* 可通过同一会话恢复状态。 */ }
    await new Promise(resolve => setTimeout(resolve, 1500))
  }
  task.status = 'error'
  task.error = '后台仍在处理，点击重试查询最新状态'
  task.progress = 100
  emit('updated')
}

function restartUpload(task: FileTask) {
  dropLocalSession(task.idempotencyKey)
  task.idempotencyKey = crypto.randomUUID()
  task.sessionId = ''
  task.note = null
  task.duplicate = null
  task.error = ''
  task.progress = 0
  if (task.file) {
    task.status = 'queued'
    void drainQueue()
  } else {
    task.status = 'paused'
    input.value?.click()
  }
}

async function retryTask(task: FileTask) {
  if (task.sessionId) {
    let session: Session | null = null
    try { session = await request<Session>(`/v1/file-uploads/sessions/${task.sessionId}`) }
    catch (cause) {
      if ((cause as Error & { status?: number }).status === 410) { restartUpload(task); return }
      task.status = 'error'
      task.error = cause instanceof Error ? cause.message : '暂时无法确认上传状态，请稍后重试'
      return
    }
    if (session?.status === 'failed' || session?.status === 'expired' || session?.status === 'cancelled') {
      restartUpload(task)
      return
    }
    if (session?.status === 'duplicate') {
      task.duplicate = session.duplicate || null; task.status = 'duplicate'; task.error = ''
      return
    }
    if (session?.status === 'uploading' || session?.status === 'completing') {
      if (!task.file) { input.value?.click(); return }
      task.status = 'queued'; task.error = ''
      void drainQueue()
      return
    }
    if (session?.status === 'completed' && session.note) {
      task.note = session.note
      task.progress = 100
      if (session.note.file?.is_current_version === false) {
        task.status = 'complete'; task.error = '已上传；此文件已被后续版本替换'
        return
      }
      const extraction = session.note.file?.extraction_status
      if (!extraction || extraction === 'pending' || session.note.index_status === 'pending') {
        task.status = 'extracting'; task.error = ''
        await pollRecognition(task)
        return
      }
      const needsRetry = ['error', 'needs_vision', 'partial'].includes(extraction) || session.note.index_status === 'error'
      if (needsRetry) {
        task.status = 'extracting'; task.error = ''
        try {
          const result = await request<{ note: NoteResult }>(`/v1/file-uploads/sessions/${task.sessionId}/retry-ingest`, { method: 'POST' })
          task.note = result.note
          await pollRecognition(task)
        } catch (cause) { task.status = 'error'; task.error = cause instanceof Error ? cause.message : '重试失败' }
        return
      }
      if (session.note.index_status === 'ready') {
        task.status = 'complete'; task.error = ''
        dropLocalSession(task.idempotencyKey)
        return
      }
      task.status = 'extracting'; task.error = ''
      await pollRecognition(task)
      return
    }
  }
  if (!task.file) { input.value?.click(); return }
  task.status = 'queued'; task.progress = 0
  await drainQueue()
}

async function cancelTask(task: FileTask) {
  task.status = 'cancelled'
  task.abort?.abort()
  if (task.sessionId) {
    try { await request(`/v1/file-uploads/sessions/${task.sessionId}`, { method: 'DELETE' }) } catch { /* 已完成的上传无法取消。 */ }
  }
  dropLocalSession(task.idempotencyKey)
}

function removeTask(task: FileTask) {
  if (task.sessionId) {
    const dismissed = new Set(readDismissedSessions())
    dismissed.add(task.sessionId)
    localStorage.setItem(dismissedKey(), JSON.stringify([...dismissed]))
  }
  tasks.value = tasks.value.filter(item => item.key !== task.key)
}

async function recognizeLink() {
  const url = linkUrl.value.trim()
  if (!url) return
  linkBusy.value = true; linkError.value = ''; linkNotice.value = ''
  try {
    const draft = await request<LinkDraft>('/v1/link-drafts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, notebook_id: props.notebookId }),
    })
    linkNotice.value = draft.fetch_status === 'ready' ? '网页正文已识别并保存为草稿' : `草稿已保存：${draft.fetch_error || '抓取失败，可手动补充正文'}`
    linkUrl.value = ''
    await loadLinkDrafts()
    emit('open-link-draft', draft)
  } catch (cause) { linkError.value = cause instanceof Error ? cause.message : '链接识别失败' }
  finally { linkBusy.value = false }
}

function statusText(task: FileTask) {
  if (task.status === 'queued') return '排队中'
  if (task.status === 'hashing') return '校验文件'
  if (task.status === 'uploading') return `上传中 ${task.progress}%`
  if (task.status === 'verifying') return '校验并保存'
  if (task.status === 'extracting') {
    const extraction = task.note?.file?.extraction_status
    if (extraction === 'pending') return task.note?.index_status === 'ready' ? '文件已保存 · 识别处理中，向量已有结果' : '文件已保存 · 内容识别处理中'
    if (extraction && ['ready', 'empty', 'unsupported'].includes(extraction) && task.note?.index_status === 'pending') return '内容已提取 · 正在生成向量'
    return '生成图片描述并索引'
  }
  if (task.status === 'paused') return '已暂停 · 重新选择文件以续传'
  if (task.status === 'duplicate') return '内容重复'
  if (task.status === 'error') {
    if (!task.note) return task.sessionId ? '上传状态待确认 · 点击重试' : '上传失败 · 重新选择文件重试'
    if (task.note.file?.is_current_version === false) return '文件已被后续版本替换'
    if (task.note.file?.extraction_status === 'needs_vision') return '文件已保存 · 本地视觉模型不可用'
    if (task.note.file?.extraction_status === 'partial') return task.note.index_status === 'ready' ? '部分页面缺少描述 · 向量已建立' : '部分页面缺少描述'
    if (task.note.file?.extraction_status === 'error') return '文件已保存 · 内容识别失败'
    if (task.note.index_status === 'error') return '文件已保存 · 向量索引失败'
    if (task.note.file?.extraction_status === 'pending' && task.note.index_status === 'ready') return '文件已保存 · 识别待完成，向量已有结果'
    return '文件已保存 · 处理未完成，可重试'
  }
  if (task.status === 'cancelled') return '已取消'
  const extraction = task.note?.file?.extraction_status
  if (task.note?.file?.is_current_version === false) return '已上传 · 文件已被后续版本替换'
  if (extraction === 'needs_vision') return '原件已保存 · 本地视觉模型不可用，请检查 Ollama'
  if (extraction === 'partial') return '部分页面缺少图像描述'
  if (extraction === 'error') return '图像描述失败，可稍后重试'
  if (extraction === 'unsupported') return '原件已保存 · 此格式暂不支持检索'
  if (task.note?.index_status === 'error') return '文件已保存 · 向量索引失败'
  if (task.note?.index_status === 'ready' && task.note.indexed_chunks !== undefined) return `索引完成 · ${task.note.indexed_chunks} 个向量块`
  return '完成'
}

function formatSize(bytes: number) { return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }
function getExtension(filename: string) { return filename.split('.').pop()?.toLowerCase() || '' }
function localDateKey(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
function formatCreatedAt(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未知' : new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
function clearFilters() { titleQuery.value = ''; dateFrom.value = ''; dateTo.value = ''; fileType.value = 'all' }
function isCancelled(task: FileTask) { return task.status === 'cancelled' }

watch(() => props.visible, visible => { if (visible) { void loadSessions(); void loadLinkDrafts() } })
watch(tasks, persistPendingTasks, { deep: true })
onMounted(() => { restorePendingTasks(); void loadSessions(); void loadLinkDrafts() })
</script>

<template>
  <div v-show="visible" class="upload-panel-backdrop" @click.self="!hasActive && emit('close')">
    <section class="upload-panel" role="dialog" aria-modal="true" aria-label="上传文件或识别链接">
      <header class="upload-panel-head"><h2>添加内容</h2><button class="upload-close" aria-label="关闭" @click="emit('close')">×</button></header>
      <div class="upload-panel-tabs" role="tablist" aria-label="导入方式">
        <button role="tab" :aria-selected="mode === 'files'" :class="{ active: mode === 'files' }" @click="mode = 'files'">文件上传</button>
        <button role="tab" :aria-selected="mode === 'link'" :class="{ active: mode === 'link' }" @click="mode = 'link'; void loadLinkDrafts()">链接识别</button>
      </div>

      <div v-if="mode === 'files'" class="upload-panel-body">
        <input ref="input" class="upload-native-input" type="file" :accept="supported" multiple @change="onInput" />
        <button class="upload-dropzone" :class="{ dragging }" type="button" @click="input?.click()" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="onDrop">
          <span class="upload-drop-icon" aria-hidden="true">↑</span><strong>拖放或选择文件</strong><small>MD、DOCX、XLSX、PDF、PNG、DOC、XLS · 单个文件最大 25 MiB</small>
        </button>
        <section class="upload-records" aria-label="上传记录">
          <div class="upload-records-heading"><div><h3>上传记录</h3><span>{{ filteredTasks.length }} 条记录</span></div><button v-if="titleQuery || dateFrom || dateTo || fileType !== 'all'" class="upload-filter-reset" type="button" @click="clearFilters">清除筛选</button></div>
          <div class="upload-record-filters">
            <label class="record-title-search"><span class="visually-hidden">按文件名搜索</span><input v-model="titleQuery" type="search" placeholder="搜索文件名" /></label>
            <label class="record-date-filter"><span class="visually-hidden">开始日期</span><input v-model="dateFrom" type="date" :max="dateTo || undefined" aria-label="开始日期" /><span>至</span><input v-model="dateTo" type="date" :min="dateFrom || undefined" aria-label="结束日期" /></label>
            <label class="record-type-filter"><span class="visually-hidden">文件类型</span><select v-model="fileType" aria-label="按文件类型筛选"><option value="all">全部类型</option><option value="md">MD</option><option value="docx">DOCX</option><option value="xlsx">XLSX</option><option value="pdf">PDF</option><option value="png">PNG</option><option value="image">图片</option><option value="doc">DOC</option><option value="xls">XLS</option></select></label>
          </div>
        </section>
        <div v-if="pagedTasks.length" class="upload-task-list">
          <article v-for="task in pagedTasks" :key="task.key" class="upload-task">
            <div class="upload-task-main"><div class="upload-task-name" :title="task.filename">{{ task.filename }}</div><div class="upload-task-meta"><span>{{ formatSize(task.size) }}</span><span class="upload-status" :class="`status-${task.status}`">{{ statusText(task) }}</span><time :datetime="task.createdAt">{{ formatCreatedAt(task.createdAt) }}</time></div><div v-if="['uploading', 'verifying', 'extracting'].includes(task.status)" class="upload-progress"><span :style="{ width: `${task.progress}%` }"></span></div><small v-if="task.error" class="upload-task-error">{{ task.error }}</small></div>
            <div class="upload-task-actions">
              <button v-if="task.note?.id" class="upload-task-link" @click="emit('open-note', task.note!.id)">打开</button>
              <button v-else-if="task.duplicate?.id" class="upload-task-link" @click="emit('open-note', task.duplicate!.id)">查看</button>
              <button v-if="['error', 'paused'].includes(task.status)" class="upload-task-action upload-task-icon-action" :aria-label="task.status === 'paused' ? '续传' : '重试'" :title="task.status === 'paused' ? '续传' : '重试'" @click="retryTask(task)"><AppIcon name="refresh" /></button>
              <button v-else-if="['queued', 'hashing', 'uploading', 'verifying'].includes(task.status)" class="upload-task-action" @click="cancelTask(task)">取消</button>
              <button v-if="!['queued', 'hashing', 'uploading', 'verifying'].includes(task.status)" class="upload-task-action upload-task-icon-action" aria-label="删除记录" title="删除记录" @click="removeTask(task)"><AppIcon name="trash" /></button>
            </div>
          </article>
        </div>
        <div v-else class="upload-empty">{{ tasks.length ? '没有符合条件的记录' : '暂无上传记录' }}</div>
        <nav v-if="filteredTasks.length > PAGE_SIZE" class="upload-pagination" aria-label="上传记录分页"><span>第 {{ currentPage }} / {{ pageCount }} 页</span><div><button type="button" :disabled="currentPage <= 1" @click="currentPage -= 1">上一页</button><button type="button" :disabled="currentPage >= pageCount" @click="currentPage += 1">下一页</button></div></nav>
      </div>

      <div v-else class="upload-panel-body link-mode-body">
        <form class="link-recognition-form" @submit.prevent="recognizeLink"><input v-model="linkUrl" type="url" required placeholder="https://example.com/article" aria-label="网页链接" /><button class="upload-primary" :disabled="linkBusy">{{ linkBusy ? '识别中…' : '识别链接' }}</button></form>
        <p v-if="linkError" class="upload-task-error" role="alert">{{ linkError }}</p><p v-if="linkNotice" class="upload-panel-hint" role="status">{{ linkNotice }}</p>
        <div class="upload-queue-head"><strong>已识别草稿</strong><button type="button" class="upload-task-action upload-task-icon-action link-draft-refresh" aria-label="刷新草稿列表" title="刷新" @click="void loadLinkDrafts()"><AppIcon name="refresh" /></button></div>
        <div v-if="!linkDrafts.length" class="upload-empty">暂无网页草稿</div>
        <div v-for="item in linkDrafts" :key="item.id" class="link-draft-row"><div><strong>{{ item.title }}</strong><small>{{ item.fetch_status === 'ready' ? '正文已抓取' : item.fetch_error || '待补充正文' }}</small></div><div class="link-draft-actions"><button type="button" class="upload-task-link" @click="emit('open-link-draft', item)"><AppIcon name="edit" />编辑</button><button type="button" class="upload-task-icon-action link-draft-delete" :aria-label="`删除${item.title}`" title="删除草稿" @click="void deleteLinkDraft(item)"><AppIcon name="trash" /></button></div></div>
      </div>
      <footer v-if="hasActive || tasks.some(item => item.status === 'queued')" class="upload-panel-foot">关闭面板后任务继续；关闭网页后可重新选择文件续传。</footer>
    </section>
  </div>
</template>

<style scoped>
.upload-panel-backdrop{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;padding:24px;background:rgba(32,30,27,.42);backdrop-filter:blur(5px)}.upload-panel{width:min(680px,100%);max-height:min(86vh,900px);overflow:hidden;display:flex;flex-direction:column;border:1px solid #e7e0d7;border-radius:18px;background:#fffdf9;box-shadow:0 24px 80px #19150f2e;color:#302d29}.upload-panel-head{display:flex;align-items:center;justify-content:space-between;padding:23px 26px 15px}.upload-panel-head h2{margin:0;font-family:Georgia,serif;font-size:26px;font-weight:500}.upload-close{width:34px;height:34px;border:0;border-radius:50%;background:#f5f1ea;color:#514b45;font-size:24px;cursor:pointer}.upload-panel-tabs{display:flex;gap:6px;padding:0 26px 15px;border-bottom:1px solid #eee8df}.upload-panel-tabs button{padding:9px 15px;border:0;border-radius:8px;background:transparent;color:#756c62;font:inherit;font-size:13px;cursor:pointer}.upload-panel-tabs button.active{background:#eaf2ee;color:#255c4f;font-weight:650}.upload-panel-body{overflow:auto;padding:20px 26px;min-height:0}.upload-native-input{display:none}.upload-dropzone{width:100%;min-height:158px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;border:1px dashed #b9aa9c;border-radius:13px;background:#faf7f1;color:#514a43;font:inherit;cursor:pointer;transition:.15s}.upload-dropzone.dragging,.upload-dropzone:hover{border-color:#347967;background:#f0f6f2}.upload-drop-icon{width:33px;height:33px;display:grid;place-items:center;border-radius:50%;background:#e5eee8;color:#2f725f;font-size:22px}.upload-dropzone strong{font-size:14px}.upload-dropzone span:not(.upload-drop-icon){font-size:12px;color:#756c62}.upload-dropzone small{margin-top:4px;color:#988d80;font-size:10px}.upload-task-list{display:grid;gap:8px;margin-top:14px}.upload-task{display:flex;align-items:center;gap:12px;padding:12px;border:1px solid #eee9e2;border-radius:10px;background:#fff}.upload-task-main{min-width:0;flex:1}.upload-task-name{overflow:hidden;color:#413c36;font-size:12px;font-weight:600;text-overflow:ellipsis;white-space:nowrap}.upload-task-main small,.link-draft-row small{display:block;margin-top:4px;color:#8a8177;font-size:10px}.upload-progress{height:3px;margin-top:8px;overflow:hidden;border-radius:3px;background:#eeeae3}.upload-progress span{display:block;height:100%;background:#40816d;transition:width .2s}.upload-task-error{display:block;margin-top:5px;color:#a7473c;font-size:10px}.upload-task-actions{display:flex;align-items:center;gap:10px}.upload-task-action,.upload-task-link{padding:4px 0;border:0;background:transparent;color:#72685f;font:inherit;font-size:11px;cursor:pointer}.upload-task-link{color:#28735f;font-weight:600}.upload-panel-hint{margin:12px 0 0;color:#81766b;font-size:11px}.upload-panel-foot{display:flex;align-items:center;justify-content:flex-start;padding:12px 26px;border-top:1px solid #eee8df;color:#8b8177;font-size:11px}.link-recognition-form{display:flex;gap:8px}.link-recognition-form input{min-width:0;flex:1;height:40px;padding:0 12px;border:1px solid #ded6cd;border-radius:8px;background:white;font:inherit;font-size:12px}.upload-primary{padding:0 15px;border:0;border-radius:8px;background:#276d5e;color:white;font:inherit;font-size:12px;cursor:pointer}.upload-primary:disabled{opacity:.55}.link-draft-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:11px 12px;border-bottom:1px solid #eee9e2}.link-draft-row strong{font-size:12px}.link-draft-row>div{min-width:0;overflow:hidden}.link-draft-row strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}@media(max-width:600px){.upload-panel-backdrop{padding:10px}.upload-panel{max-height:94vh;border-radius:14px}.upload-panel-head,.upload-panel-body{padding-right:17px;padding-left:17px}.upload-panel-tabs{padding-right:17px;padding-left:17px}.upload-panel-foot{padding:12px 17px}.link-recognition-form{flex-direction:column}.link-recognition-form button{height:40px}}
.upload-records{display:grid;gap:12px;margin-top:22px}
.upload-records-heading{display:flex;align-items:center;justify-content:space-between}
.upload-records-heading>div{display:flex;align-items:baseline;gap:9px}
.upload-records-heading h3{margin:0;color:#39342f;font-size:15px;font-weight:650}
.upload-records-heading span{color:#9a8d81;font-size:11px}
.upload-filter-reset{padding:4px 0;border:0;background:transparent;color:#28735f;font:inherit;font-size:11px;cursor:pointer}
.upload-record-filters{display:grid;grid-template-columns:minmax(140px,1fr) auto 120px;gap:8px}
.record-title-search,.record-date-filter,.record-type-filter{display:flex;align-items:center;min-width:0;height:37px;padding:0 10px;border:1px solid #e7e0d7;border-radius:8px;background:#fff;color:#84796f}
.record-title-search:focus-within,.record-date-filter:focus-within,.record-type-filter:focus-within{border-color:#6b9a88;box-shadow:0 0 0 3px #40816d17}
.record-title-search input,.record-date-filter input,.record-type-filter select{width:100%;min-width:0;height:100%;padding:0;border:0;outline:0;background:transparent;color:#403a34;font:inherit;font-size:11px}
.record-title-search input::placeholder{color:#a29488}
.record-date-filter{gap:6px;padding:0 7px}
.record-date-filter span{flex:none;color:#a29488;font-size:10px}
.record-date-filter input{width:113px;font-size:10px}
.record-type-filter select{cursor:pointer}
.upload-task-list{gap:8px;margin-top:12px}
.upload-task{min-height:72px;padding:12px 14px;border-color:#eee7de;border-radius:11px;transition:border-color .16s ease,background .16s ease}
.upload-task:hover{border-color:#d9e4dd;background:#fffefa}
.upload-task-main{display:grid;gap:7px}
.upload-task-name{font-size:12px;line-height:1.45}
.upload-task-meta{display:flex;align-items:center;flex-wrap:wrap;gap:8px;color:#8a8177;font-size:10px}
.upload-task-meta time{margin-left:auto;font-variant-numeric:tabular-nums;white-space:nowrap}
.upload-status{padding:3px 7px;border-radius:999px;background:#eaf2ee;color:#286b59;font-weight:650;line-height:1.2}
.upload-status.status-error{background:#f9e9e5;color:#a7473c}
.upload-status.status-paused,.upload-status.status-queued,.upload-status.status-cancelled{background:#f2eee8;color:#786b5f}
.upload-status.status-hashing,.upload-status.status-uploading,.upload-status.status-verifying,.upload-status.status-extracting{background:#e8f0f2;color:#416a75}
.upload-status.status-duplicate{background:#f6efdf;color:#8a6b2f}
.upload-progress{height:4px;margin-top:1px}
.upload-task-actions{flex:none;gap:12px}
.upload-task-icon-action{width:24px;height:24px;display:grid;place-items:center;padding:3px;border-radius:6px;color:#746b62}
.upload-task-icon-action:hover{background:#f3eee8;color:#315f50}
.upload-task-icon-action :deep(svg){width:16px;height:16px}
.upload-pagination{display:flex;align-items:center;justify-content:space-between;margin-top:14px;color:#8b8177;font-size:11px}
.upload-pagination>div{display:flex;gap:6px}
.upload-pagination button{min-height:32px;padding:0 10px;border:1px solid #e7e0d7;border-radius:7px;background:#fff;color:#514a43;font:inherit;cursor:pointer}
.upload-pagination button:hover:not(:disabled){border-color:#8aaf9e;color:#286b59}
.upload-pagination button:disabled{opacity:.42;cursor:not-allowed}
.upload-empty{display:grid;place-items:center;min-height:90px;margin-top:12px;border:1px dashed #e8e0d6;border-radius:10px;color:#9a8d81;font-size:12px}
.upload-queue-head{display:flex;align-items:center;justify-content:space-between;margin-top:18px}.upload-queue-head strong{font-size:13px}.link-draft-refresh{margin-left:auto}.link-draft-actions{display:flex;flex:none;align-items:center;gap:12px}.link-draft-actions .upload-task-link{display:flex;align-items:center;gap:4px}.link-draft-actions .upload-task-link svg{width:13px;height:13px}.link-draft-delete{display:grid;width:26px;height:26px;place-items:center;padding:4px;border:0;border-radius:6px;background:transparent;color:#8a8177;cursor:pointer}.link-draft-delete:hover{background:#f7e9e5;color:#a7473c}.link-draft-delete svg{width:16px;height:16px}
.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:600px){.upload-record-filters{grid-template-columns:minmax(0,1fr) 112px}.record-title-search{grid-column:1/-1}.record-date-filter{grid-column:1}.record-date-filter input{width:calc(50% - 13px)}.record-type-filter{grid-column:2}.upload-task{align-items:flex-start}.upload-task-meta time{margin-left:0}.upload-task-actions{gap:8px}.upload-task-action,.upload-task-link{font-size:10px}}
</style>
