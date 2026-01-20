import apiClient, { extractErrorMessage } from './api'

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

export interface AIAssistResponse {
  result: string
  suggestions: string[]
}

export interface StructuredEdit {
  id: string
  original_text: string
  new_text: string
  context_before: string
  context_after: string
  found_in_document: boolean
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
  content: string = ''
): Promise<Document> {
  try {
    const response = await apiClient.post<Document>(
      `${BASE_URL}/api/documents-editor/create`,
      {
        case_id: caseId,
        title,
        initial_content: content,
      }
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
  title?: string
): Promise<Document> {
  try {
    const response = await apiClient.put<Document>(
      `${BASE_URL}/api/documents-editor/${documentId}`,
      {
        content,
        title,
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
  question: string
): Promise<DocumentChatResponse> {
  try {
    const response = await apiClient.post<DocumentChatResponse>(
      `${BASE_URL}/api/documents-editor/${documentId}/chat`,
      {
        question,
      }
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
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

