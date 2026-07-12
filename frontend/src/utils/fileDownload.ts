/**
 * Production file download helpers for browser blob responses.
 *
 * Handles:
 * - detached <a> download (Safari / Chromium)
 * - Cyrillic / unsafe filenames
 * - API errors returned as JSON inside blob responses
 */

import axios, { type AxiosResponse } from 'axios'

const UNSAFE_FILENAME = /[\u0000-\u001f<>:"/\\|?*]+/g

export function sanitizeDownloadFilename(name: string, fallback = 'export'): string {
  const base = (name || fallback).replace(/\\/g, '/').split('/').pop() || fallback
  const cleaned = base
    .replace(UNSAFE_FILENAME, '_')
    .replace(/[. ]+$/g, '')
    .trim()
  return (cleaned || fallback).slice(0, 180)
}

/** Trigger a browser download for an in-memory Blob. */
export function downloadBlob(blob: Blob, filename: string): void {
  if (!(blob instanceof Blob) || blob.size <= 0) {
    throw new Error('Пустой файл экспорта')
  }
  const safeName = sanitizeDownloadFilename(filename)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = safeName
  link.rel = 'noopener'
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  // Safari can cancel the download if the object URL is revoked immediately.
  window.setTimeout(() => {
    URL.revokeObjectURL(url)
    link.remove()
  }, 1500)
}

function looksLikeJsonContentType(contentType: string | undefined): boolean {
  return Boolean(contentType && contentType.toLowerCase().includes('application/json'))
}

function messageFromJsonPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null
  const detail = (payload as { detail?: unknown; message?: unknown }).detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (!item || typeof item !== 'object') return ''
        const msg = (item as { msg?: unknown }).msg
        return typeof msg === 'string' ? msg : ''
      })
      .filter(Boolean)
    if (parts.length) return parts.join('; ')
  }
  const message = (payload as { message?: unknown }).message
  if (typeof message === 'string' && message.trim()) return message.trim()
  return null
}

async function messageFromBlob(blob: Blob): Promise<string | null> {
  const text = (await blob.text()).trim()
  if (!text) return null
  if (text.startsWith('{') || text.startsWith('[')) {
    try {
      return messageFromJsonPayload(JSON.parse(text))
    } catch {
      // fall through
    }
  }
  // Cap opaque HTML/text errors
  return text.slice(0, 300)
}

/**
 * Ensure an Axios blob response is a real file, not a JSON/HTML error body.
 * Call on successful responses (2xx) before downloading.
 */
export async function assertDownloadBlob(
  response: AxiosResponse<Blob>,
  expectedKinds: Array<'csv' | 'excel' | 'word' | 'octet'>,
): Promise<Blob> {
  const blob = response.data
  if (!(blob instanceof Blob)) {
    throw new Error('Сервер вернул некорректный ответ экспорта')
  }

  const contentType = String(response.headers?.['content-type'] || blob.type || '')
  if (looksLikeJsonContentType(contentType) || blob.type === 'application/json') {
    const message = (await messageFromBlob(blob)) || 'Ошибка экспорта'
    throw new Error(message)
  }

  // Empty body is never a valid spreadsheet/doc
  if (blob.size === 0) {
    throw new Error('Сервер вернул пустой файл')
  }

  // Detect JSON error bodies mislabeled as octet-stream / plain text
  const head = await blob.slice(0, 64).text()
  const trimmed = head.trim()
  if (trimmed.startsWith('{') && trimmed.includes('"detail"')) {
    const message = (await messageFromBlob(blob)) || 'Ошибка экспорта'
    throw new Error(message)
  }

  const lower = contentType.toLowerCase()
  const kindOk = expectedKinds.some((kind) => {
    switch (kind) {
      case 'csv':
        return lower.includes('text/csv') || lower.includes('application/csv') || lower.startsWith('text/plain')
      case 'excel':
        return (
          lower.includes('spreadsheetml') ||
          lower.includes('excel') ||
          lower.includes('octet-stream') ||
          lower === ''
        )
      case 'word':
        return (
          lower.includes('wordprocessingml') ||
          lower.includes('msword') ||
          lower.includes('octet-stream') ||
          lower === ''
        )
      case 'octet':
        return true
      default: {
        const _exhaustive: never = kind
        return _exhaustive
      }
    }
  })

  if (!kindOk && lower && !lower.includes('octet-stream')) {
    const message = (await messageFromBlob(blob)) || `Неожиданный тип файла: ${contentType}`
    throw new Error(message)
  }

  return blob
}

/** Parse Axios errors when responseType was 'blob'. */
export async function extractBlobErrorMessage(error: unknown, fallback = 'Не удалось экспортировать'): Promise<string> {
  if (!axios.isAxiosError(error)) {
    return error instanceof Error && error.message ? error.message : fallback
  }

  const data = error.response?.data
  if (data instanceof Blob) {
    const message = await messageFromBlob(data)
    if (message) return message
  } else {
    const message = messageFromJsonPayload(data)
    if (message) return message
  }

  if (error.response?.status === 401) return 'Сессия истекла — войдите снова'
  if (error.response?.status === 403) return 'Недостаточно прав для экспорта'
  if (error.response?.status === 404) return 'Данные для экспорта не найдены'
  if (typeof error.message === 'string' && error.message) return error.message
  return fallback
}
