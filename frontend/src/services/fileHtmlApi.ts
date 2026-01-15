import apiClient, { extractErrorMessage } from './api'

const BASE_URL = import.meta.env.VITE_API_URL || ''

export interface FileHtmlResponse {
  html: string
  cached: boolean
  file_id: string
  filename: string
}

/**
 * Get HTML representation of a file
 * 
 * @param caseId - Case identifier
 * @param fileId - File identifier
 * @param forceRefresh - Force refresh HTML cache even if cached
 * @returns HTML content and cache status
 */
export async function getFileHtml(
  caseId: string,
  fileId: string,
  forceRefresh: boolean = false
): Promise<FileHtmlResponse> {
  try {
    const response = await apiClient.get<FileHtmlResponse>(
      `${BASE_URL}/api/cases/${caseId}/files/${fileId}/html`,
      {
        params: {
          force_refresh: forceRefresh,
        },
      }
    )
    return response.data
  } catch (error) {
    throw new Error(extractErrorMessage(error))
  }
}

