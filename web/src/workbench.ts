export type ReportKind = 'daily' | 'weekly'

export type WorkbenchDigest = {
  id: string
  kind: ReportKind
  title: string
  excerpt: string
  topics: string[]
  status: 'pending' | 'processing' | 'ready' | 'failed'
  note_id: string | null
  note_active: boolean
  note_archived: boolean
  period_start: string
  period_end: string
  scheduled_at: string
  updated_at: string
}
