import { getApiUrl } from './api'
import { logger } from '@/lib/logger'

export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: Array<{
    file?: string
    title?: string
    url?: string
    page?: number
    text_preview?: string
    similarity_score?: number
  }>
  created_at?: string
}

const HISTORY_STORAGE_KEY = 'chat_history_'

/**
 * Загружает историю чата из API
 */
export async function loadChatHistory(caseId: string): Promise<HistoryMessage[]> {
  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch(getApiUrl(`/api/assistant/chat/${caseId}/history`), {
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


