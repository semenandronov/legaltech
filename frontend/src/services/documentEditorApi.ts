import apiClient, { extractErrorMessage, getApiUrl } from './api'

const BASE_URL = import.meta.env.VITE_API_URL || ''

export interface Document {
  id: string
  case_id: string
  user_id: string
  title: string
  content: string
  content_plain?: string
  metadata?: Record<string, any>
  version: number
  created_at: string
  updated_at: string
}

export interface RiskItem {
  id: string
  quote: string
  from: number
  to: number
  level: 'high' | 'medium' | 'low'
  description: string
}

export interface AIAssistResponse {
  result: string
  suggestions: string[]
  risks?: RiskItem[]
}

export interface SelectionRange {
  from: number
  to: number
}

export interface StructuredEdit {
  id: string
  new_text: string
  original_text?: string
  node_id?: string
  selection_range?: SelectionRange
  context_before?: string
  context_after?: string
  found_in_document: boolean
  replace_all?: boolean
}

export interface DocumentChatResponse {
  answer: string
  citations: Array<{ file: string; file_id: string }>
  suggestions: string[]
  edited_content?: string
  structured_edits?: StructuredEdit[]
}

export interface DocumentVersion {
  id: string
  document_id: string
  content: string
  version: number
  created_at: string
  created_by?: string
}

/**
 * Create a new document
 */
export async function createDocument(
  caseId: string,
  title: string,
  content: string = '',
  metadata?: Record<string, any>
): Promise<Document> {
  try {
    const response = await apiClient.post<Document>(
      `${BASE_URL}/api/documents-editor/create`,
      {
        case_id: caseId,
        title,
        initial_content: content,
        metadata: metadata ?? undefined,
      }
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * Create a document in the editor from an uploaded case file.
 * If the file was already imported, returns the existing document.
 */
export async function createDocumentFromFile(
  fileId: string,
  caseId: string,
  title?: string
): Promise<Document> {
  try {
    const response = await apiClient.post<Document>(
      `${BASE_URL}/api/documents-editor/create-from-file/${fileId}`,
      { case_id: caseId, title }
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * Get a document by ID
 */
export async function getDocument(documentId: string): Promise<Document> {
  try {
    const response = await apiClient.get<Document>(
      `${BASE_URL}/api/documents-editor/${documentId}`
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * Update a document
 */
export async function updateDocument(
  documentId: string,
  content: string,
  title?: string,
  metadata?: Record<string, any>
): Promise<Document> {
  try {
    const response = await apiClient.put<Document>(
      `${BASE_URL}/api/documents-editor/${documentId}`,
      {
        content,
        title,
        metadata: metadata ?? undefined,
      }
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * Delete a document
 */
export async function deleteDocument(documentId: string): Promise<void> {
  try {
    await apiClient.delete(`${BASE_URL}/api/documents-editor/${documentId}`)
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * List documents for a case
 */
export async function listDocuments(caseId: string): Promise<Document[]> {
  try {
    const response = await apiClient.get<Document[]>(
      `${BASE_URL}/api/documents-editor/case/${caseId}`
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * AI assistance for document editing
 */
export async function aiAssist(
  documentId: string,
  command: string,
  selectedText: string = '',
  prompt: string = ''
): Promise<AIAssistResponse> {
  try {
    const response = await apiClient.post<AIAssistResponse>(
      `${BASE_URL}/api/documents-editor/${documentId}/ai-assist`,
      {
        command,
        selected_text: selectedText,
        prompt,
      }
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * Export document to DOCX
 */
export async function exportDocx(documentId: string): Promise<void> {
  try {
    const response = await apiClient.post(
      `${BASE_URL}/api/documents-editor/${documentId}/export/docx`,
      {},
      {
        responseType: 'blob',
      }
    )

    // Create download link
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `document-${documentId}.docx`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * Export document to PDF
 */
export async function exportPdf(documentId: string): Promise<void> {
  try {
    const response = await apiClient.post(
      `${BASE_URL}/api/documents-editor/${documentId}/export/pdf`,
      {},
      {
        responseType: 'blob',
      }
    )

    // Create download link
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `document-${documentId}.pdf`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * Chat over document - ask questions and get AI assistance
 */
export async function chatOverDocument(
  documentId: string,
  question: string,
  options?: {
    deepThink?: boolean
    legalResearch?: boolean
    currentContent?: string
    mode?: 'ask' | 'edit' | 'draft'
    selectedText?: string
    selectionRange?: SelectionRange | null
    attachedFileIds?: string[]
  }
): Promise<DocumentChatResponse> {
  try {
    const response = await apiClient.post<DocumentChatResponse>(
      `${BASE_URL}/api/documents-editor/${documentId}/chat`,
      buildChatRequestBody(question, options),
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

export interface DocumentChatStreamCallbacks {
  onTurnStarted?: (payload: {
    turnId: string
    intent: 'ask' | 'edit' | 'draft'
  }) => void
  onTurnCompleted?: (payload: {
    turnId: string
    intent: string
    artifactType: string
  }) => void
  onTextDelta?: (delta: string) => void
  /** Full answer replacement after sanitize (not append). */
  onContentSync?: (content: string) => void
  onStructuredEdits?: (edits: StructuredEdit[]) => void
  onCitations?: (citations: Array<{ file: string; file_id: string }>) => void
  onEditedContent?: (content: string) => void
}

export interface EditorChatWarmupResult {
  ok: boolean
  case_id: string
  document_id: string
  session_id: string
  thread_id: string
  checkpoint_has_values: boolean
  warmup_ms: number
  graph_compile_ms?: number
}

export async function warmupEditorChat(
  documentId: string,
  caseId: string,
  sessionId?: string,
): Promise<EditorChatWarmupResult> {
  const token = localStorage.getItem('access_token')
  const response = await fetch(
    getApiUrl(`/api/documents-editor/${documentId}/chat/warmup`),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Access-Token': token || '',
      },
      body: JSON.stringify({
        case_id: caseId,
        session_id: sessionId ?? null,
      }),
    },
  )
  if (!response.ok) {
    throw new Error(`Editor warmup failed: ${response.status}`)
  }
  return response.json()
}

export async function createEditorChatSession(
  documentId: string,
  caseId: string,
): Promise<{ session_id: string; document_id: string; case_id: string }> {
  const token = localStorage.getItem('access_token')
  const response = await fetch(
    getApiUrl(`/api/documents-editor/${documentId}/chat/new-session`),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Access-Token': token || '',
      },
      body: JSON.stringify({ case_id: caseId }),
    },
  )
  if (!response.ok) {
    throw new Error(`New editor session failed: ${response.status}`)
  }
  return response.json()
}

function buildChatRequestBody(
  question: string,
  options?: {
    deepThink?: boolean
    legalResearch?: boolean
    currentContent?: string
    mode?: 'ask' | 'edit' | 'draft'
    selectedText?: string
    selectionRange?: SelectionRange | null
    attachedFileIds?: string[]
    sessionId?: string
  },
) {
  return {
    question,
    session_id: options?.sessionId ?? null,
    deep_think: options?.deepThink ?? false,
    legal_research: options?.legalResearch ?? false,
    current_content: options?.currentContent ?? null,
    mode: options?.mode ?? 'ask',
    selected_text: options?.selectedText ?? null,
    selection_range: options?.selectionRange ?? null,
    attached_file_ids: options?.attachedFileIds?.length ? options.attachedFileIds : null,
  }
}

/**
 * SSE stream for document editor chat (LangGraph via EditorHandler).
 */
export async function streamDocumentChat(
  documentId: string,
  question: string,
  options: {
    deepThink?: boolean
    legalResearch?: boolean
    currentContent?: string
    mode?: 'ask' | 'edit' | 'draft'
    selectedText?: string
    selectionRange?: SelectionRange | null
    attachedFileIds?: string[]
    sessionId?: string
  } | undefined,
  callbacks: DocumentChatStreamCallbacks,
  signal?: AbortSignal,
): Promise<DocumentChatResponse> {
  const token = localStorage.getItem('access_token')
  const response = await fetch(
    getApiUrl(`/api/documents-editor/${documentId}/chat/stream`),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Access-Token': token || '',
      },
      body: JSON.stringify(buildChatRequestBody(question, options)),
      signal,
    },
  )

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`)
  }

  const reader = response.body?.getReader()
  const decoder = new TextDecoder()
  if (!reader) {
    throw new Error('No response body')
  }

  let answer = ''
  let structuredEdits: StructuredEdit[] = []
  let citations: Array<{ file: string; file_id: string }> = []
  let editedContent: string | undefined
  let buffer = ''
  const streamMode = options?.mode ?? 'ask'

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue
        try {
          const data = JSON.parse(line.slice(6))
          if (data.error) {
            throw new Error(String(data.error))
          }
          if (data.type === 'turn_started' && data.turn_id) {
            callbacks.onTurnStarted?.({
              turnId: String(data.turn_id),
              intent: (data.intent as 'ask' | 'edit' | 'draft') || streamMode,
            })
            continue
          }
          if (data.type === 'turn_completed' && data.turn_id) {
            callbacks.onTurnCompleted?.({
              turnId: String(data.turn_id),
              intent: String(data.intent ?? streamMode),
              artifactType: String(data.artifact_type ?? 'answer'),
            })
            continue
          }
          if (data.type === 'content_sync' && typeof data.content === 'string') {
            answer = data.content
            callbacks.onContentSync?.(data.content)
            continue
          }
          const delta = data.textDelta ?? data.text_delta
          if (delta) {
            answer += String(delta)
            callbacks.onTextDelta?.(String(delta))
          }
          const patchIntent = (data.intent as string | undefined) ?? streamMode
          if (data.structured_edits?.length && patchIntent === 'edit') {
            structuredEdits = data.structured_edits
            callbacks.onStructuredEdits?.(structuredEdits)
          }
          if (data.citations?.length) {
            citations = data.citations
            callbacks.onCitations?.(citations)
          }
          if (data.edited_content) {
            const content = String(data.edited_content)
            editedContent = content
            callbacks.onEditedContent?.(content)
          }
        } catch (e) {
          if (e instanceof SyntaxError) continue
          throw e
        }
      }
    }
  }

  const cleanAnswer = answer
    .replace(/```(?:html|edit|)\s*\n[\s\S]*?\n?```/gi, '')
    .replace(/```[\s\S]*?```/g, '')
    .trim()

  return {
    answer:
      cleanAnswer ||
      (streamMode === 'edit' && structuredEdits.length
        ? `Предлагаю ${structuredEdits.length} правку(-и).`
        : 'Изменения готовы.'),
    citations,
    suggestions: streamMode === 'edit' && structuredEdits.length ? ['Применить все правки'] : [],
    edited_content: editedContent,
    structured_edits: streamMode === 'edit' ? structuredEdits : [],
  }
}

/**
 * List versions for a document
 */
export async function listDocumentVersions(documentId: string): Promise<DocumentVersion[]> {
  try {
    const response = await apiClient.get<DocumentVersion[]>(
      `${BASE_URL}/api/documents-editor/${documentId}/versions`
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * Get a specific version of a document
 */
export async function getDocumentVersion(
  documentId: string,
  version: number
): Promise<DocumentVersion> {
  try {
    const response = await apiClient.get<DocumentVersion>(
      `${BASE_URL}/api/documents-editor/${documentId}/versions/${version}`
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

/**
 * Restore a document to a specific version
 */
export async function restoreDocumentVersion(
  documentId: string,
  version: number
): Promise<Document> {
  try {
    const response = await apiClient.post<Document>(
      `${BASE_URL}/api/documents-editor/${documentId}/restore/${version}`
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

export interface TemplateUploadResponse {
  content: string
  filename: string
  file_type: string
}

/**
 * Upload and convert a template file to HTML (temporary, not saved to DB)
 * Used for draft mode with local files
 */
export async function uploadTemplateFile(file: File): Promise<TemplateUploadResponse> {
  try {
    const formData = new FormData()
    formData.append('file', file)

    const response = await apiClient.post<TemplateUploadResponse>(
      `${BASE_URL}/api/documents-editor/upload-template`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

