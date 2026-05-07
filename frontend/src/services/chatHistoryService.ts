import { getApiUrl, type SourceInfo } from './api'
import { logger } from '@/lib/logger'

/** Блок структурированного ответа (Phase 2), как в SSE `answer_blocks`. */
export type StoredAnswerBlockItem = {
  block_id: string
  markdown_text: string
  citation_ids: string[]
}

export type ParsedStoredSourceReferences = {
  citations?: Array<Record<string, unknown>>
  answerBlocks?: StoredAnswerBlockItem[]
}

/**
 * Разбор source_references из БД: legacy JSON-массив или объект { citations, answer_blocks }.
 */
export function parseStoredSourceReferences(raw: unknown): ParsedStoredSourceReferences {
  if (raw == null) return {}
  let data: unknown = raw
  if (typeof raw === 'string') {
    try {
      data = JSON.parse(raw)
    } catch {
      return {}
    }
  }
  if (Array.isArray(data)) {
    return { citations: data as Array<Record<string, unknown>> }
  }
  if (data && typeof data === 'object') {
    const o = data as Record<string, unknown>
    const c = o.citations
    const ab = o.answer_blocks ?? o.answerBlocks
    let answerBlocks: StoredAnswerBlockItem[] | undefined
    if (Array.isArray(ab) && ab.length > 0) {
      answerBlocks = ab.map((b: unknown) => {
        const row = b as Record<string, unknown>
        const ids = row.citation_ids
        return {
          block_id: String(row.block_id ?? ''),
          markdown_text: String(row.markdown_text ?? ''),
          citation_ids: Array.isArray(ids) ? ids.map((x) => String(x)) : [],
        }
      })
    }
    return {
      citations: Array.isArray(c) ? (c as Array<Record<string, unknown>>) : undefined,
      answerBlocks,
    }
  }
  return {}
}

function parseBboxRegions(raw: unknown): SourceInfo['bbox_regions'] {
  if (!Array.isArray(raw) || raw.length === 0) return undefined
  const out: NonNullable<SourceInfo['bbox_regions']> = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    const x0 = o.x0
    const y0 = o.y0
    const x1 = o.x1
    const y1 = o.y1
    if (
      typeof x0 === 'number' &&
      typeof y0 === 'number' &&
      typeof x1 === 'number' &&
      typeof y1 === 'number'
    ) {
      out.push({ x0, y0, x1, y1 })
    }
  }
  return out.length ? out : undefined
}

/** Единый маппинг цитаты API/SSE → SourceInfo (чат по делу и глобальный ассистент). */
export function citationRecordToSourceInfo(c: Record<string, unknown>): SourceInfo {
  const file = String(c.file_name ?? c.file ?? '')
  const pr = c.page ?? c.source_page
  const page = typeof pr === 'number' && !Number.isNaN(pr) ? pr : undefined
  const q = c.quote
  const qa = c.quote_anchor
  return {
    citation_id: typeof c.citation_id === 'string' ? c.citation_id : undefined,
    file,
    title: file || undefined,
    page,
    text_preview:
      (typeof qa === 'string' ? qa : undefined) ||
      (typeof q === 'string' ? q : undefined),
    quote_anchor: typeof qa === 'string' ? qa : undefined,
    source_id: typeof c.source_id === 'string' ? c.source_id : undefined,
    quote: typeof q === 'string' ? q : undefined,
    chunk_id: typeof c.chunk_id === 'string' ? c.chunk_id : undefined,
    char_start: typeof c.char_start === 'number' ? c.char_start : undefined,
    char_end: typeof c.char_end === 'number' ? c.char_end : undefined,
    context_before: typeof c.context_before === 'string' ? c.context_before : undefined,
    context_after: typeof c.context_after === 'string' ? c.context_after : undefined,
    bbox: (c.bbox && typeof c.bbox === 'object' ? c.bbox : undefined) as SourceInfo['bbox'],
    bbox_regions: parseBboxRegions(c.bbox_regions),
    page_bbox: (c.page_bbox && typeof c.page_bbox === 'object' ? c.page_bbox : undefined) as SourceInfo['page_bbox'],
    url: typeof c.url === 'string' ? c.url : '',
    source_type: typeof c.source_type === 'string' ? c.source_type : 'document',
  }
}

export interface HistoryReasoningStep {
  phase: string
  step: number
  totalSteps: number
  content: string
}

export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
  /** Сырые ссылки: массив цитат или объект { citations, answer_blocks } */
  source_references?: unknown
  sources?: Array<{
    file?: string
    title?: string
    url?: string
    page?: number
    text_preview?: string
    similarity_score?: number
  }>
  /** Сохранённые шаги reasoning (глобальный / чат по делу) */
  reasoning_steps?: HistoryReasoningStep[] | null
  created_at?: string
  session_id?: string
}

const HISTORY_STORAGE_KEY = 'chat_history_'

/** Приводит шаги из API к ThinkingStep для UI */
export function normalizeReasoningStepsFromApi(
  raw: unknown
): HistoryReasoningStep[] | undefined {
  if (!Array.isArray(raw) || raw.length === 0) return undefined
  const out: HistoryReasoningStep[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    const phase = typeof o.phase === 'string' ? o.phase : ''
    const content = typeof o.content === 'string' ? o.content : ''
    const step = typeof o.step === 'number' ? o.step : Number(o.step) || 1
    const totalSteps =
      typeof o.totalSteps === 'number'
        ? o.totalSteps
        : typeof o.total_steps === 'number'
          ? o.total_steps
          : 1
    if (phase) out.push({ phase, step, totalSteps, content })
  }
  return out.length ? out : undefined
}

/** Поля сообщения ассистента из записи истории (citations + answer_blocks). */
export function mapAssistantHistoryMessage(m: HistoryMessage): {
  role: 'user' | 'assistant'
  content: string
  reasoningSteps?: HistoryReasoningStep[]
  sources?: SourceInfo[]
  answerBlocks?: StoredAnswerBlockItem[]
} {
  const { citations, answerBlocks } = parseStoredSourceReferences(m.source_references)
  return {
    role: m.role,
    content: m.content,
    reasoningSteps: normalizeReasoningStepsFromApi(m.reasoning_steps),
    sources: citations?.length ? citations.map(citationRecordToSourceInfo) : undefined,
    answerBlocks: answerBlocks?.length ? answerBlocks : undefined,
  }
}

/**
 * Загружает историю чата из API
 */
export async function loadChatHistory(caseId: string, sessionId?: string): Promise<HistoryMessage[]> {
  try {
    const token = localStorage.getItem('access_token')
    const url = sessionId 
      ? getApiUrl(`/api/v2/assistant/chat/${caseId}/history?session_id=${sessionId}`)
      : getApiUrl(`/api/v2/assistant/chat/${caseId}/history`)
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const data = await response.json()
    const messages = data.messages || []

    // Сохраняем в localStorage как fallback
    saveChatHistoryLocally(caseId, messages)

    return messages
  } catch (error) {
    logger.error('Error loading chat history:', error)
    
    // Fallback: пытаемся загрузить из localStorage
    return restoreChatHistoryLocally(caseId)
  }
}

/**
 * Сохраняет историю чата в localStorage (fallback)
 */
export function saveChatHistoryLocally(caseId: string, messages: HistoryMessage[]): void {
  try {
    const key = `${HISTORY_STORAGE_KEY}${caseId}`
    localStorage.setItem(key, JSON.stringify({
      messages,
      timestamp: Date.now(),
    }))
  } catch (error) {
    logger.warn('Error saving chat history to localStorage:', error)
  }
}

/**
 * Восстанавливает историю чата из localStorage
 */
export function restoreChatHistoryLocally(caseId: string): HistoryMessage[] {
  try {
    const key = `${HISTORY_STORAGE_KEY}${caseId}`
    const stored = localStorage.getItem(key)
    
    if (!stored) {
      return []
    }

    const data = JSON.parse(stored)
    
    // Проверяем, не устарела ли история (старше 24 часов)
    const maxAge = 24 * 60 * 60 * 1000 // 24 часа
    if (data.timestamp && Date.now() - data.timestamp > maxAge) {
      localStorage.removeItem(key)
      return []
    }

    return data.messages || []
  } catch (error) {
    logger.warn('Error restoring chat history from localStorage:', error)
    return []
  }
}

/**
 * Очищает историю чата из localStorage
 */
export function clearChatHistoryLocally(caseId: string): void {
  try {
    const key = `${HISTORY_STORAGE_KEY}${caseId}`
    localStorage.removeItem(key)
  } catch (error) {
    logger.warn('Error clearing chat history from localStorage:', error)
  }
}


