import { useCallback, useEffect, useRef, useState } from 'react'
import {
  FileProcessingStatus,
  FilesResponse,
  getProcessingStatus,
  UploadedFile,
} from '../services/api'

const DEFAULT_POLL_MS = 3000

function mergeProcessingFiles(
  prev: FileProcessingStatus[],
  incoming: Array<Partial<FileProcessingStatus> & { id: string; filename: string }>,
): FileProcessingStatus[] {
  const map = new Map(prev.map((f) => [f.id, f]))
  for (const f of incoming) {
    const prevRow = map.get(f.id)
    map.set(f.id, {
      id: f.id,
      filename: f.filename || prevRow?.filename || '',
      status:
        ((f.status || (f as { processing_status?: string }).processing_status) as FileProcessingStatus['status']) ||
        prevRow?.status ||
        'pending',
      error: f.error ?? prevRow?.error ?? null,
      progress: f.progress ?? prevRow?.progress ?? null,
      folder_id: f.folder_id !== undefined ? f.folder_id : prevRow?.folder_id,
      dd_doc_type: f.dd_doc_type !== undefined ? f.dd_doc_type : prevRow?.dd_doc_type,
      dd_doc_type_label:
        f.dd_doc_type_label !== undefined ? f.dd_doc_type_label : prevRow?.dd_doc_type_label,
      dd_doc_type_short_label:
        f.dd_doc_type_short_label !== undefined
          ? f.dd_doc_type_short_label
          : prevRow?.dd_doc_type_short_label,
      dd_doc_type_confidence:
        f.dd_doc_type_confidence !== undefined
          ? f.dd_doc_type_confidence
          : prevRow?.dd_doc_type_confidence,
      dd_doc_type_source:
        f.dd_doc_type_source !== undefined ? f.dd_doc_type_source : prevRow?.dd_doc_type_source,
      dd_needs_review:
        f.dd_needs_review !== undefined ? f.dd_needs_review : prevRow?.dd_needs_review,
    })
  }
  return Array.from(map.values())
}

function uploadedToProcessing(files: UploadedFile[]): FileProcessingStatus[] {
  return files.map((f) => ({
    id: f.id,
    filename: f.filename,
    status: 'pending' as const,
  }))
}

export type UseCaseProcessingPollOptions = {
  pollIntervalMs?: number
  /** Вызывается один раз, когда все файлы в статусе ready/error/cancelled */
  onAllDone?: (caseId: string) => void
  /** Каждый успешный poll — чтобы UI подтягивал типы/папки по мере готовности */
  onStatus?: (files: FileProcessingStatus[], meta: { allDone: boolean; anyProcessing: boolean }) => void
}

/**
 * Единый polling статусов обработки файлов дела после upload/import.
 */
export function useCaseProcessingPoll(
  caseId: string | null,
  options: UseCaseProcessingPollOptions = {},
) {
  const { pollIntervalMs = DEFAULT_POLL_MS, onAllDone, onStatus } = options
  const onAllDoneRef = useRef(onAllDone)
  onAllDoneRef.current = onAllDone
  const onStatusRef = useRef(onStatus)
  onStatusRef.current = onStatus

  const [processingFiles, setProcessingFiles] = useState<FileProcessingStatus[]>([])
  const [allDone, setAllDone] = useState(false)
  const [anyProcessing, setAnyProcessing] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const allDoneFiredRef = useRef(false)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const applyStatus = useCallback(
    (files: FileProcessingStatus[], done: boolean, processing: boolean) => {
      setProcessingFiles(files)
      setAllDone(done)
      setAnyProcessing(processing)
      onStatusRef.current?.(files, { allDone: done, anyProcessing: processing })
    },
    [],
  )

  const fetchStatus = useCallback(async (): Promise<boolean> => {
    if (!caseId) return false
    const status = await getProcessingStatus(caseId)
    const merged = mergeProcessingFiles([], status.files)
    applyStatus(merged, status.all_done, status.any_processing)
    if (status.all_done) {
      stopPolling()
      if (!allDoneFiredRef.current) {
        allDoneFiredRef.current = true
        onAllDoneRef.current?.(caseId)
      }
    }
    return status.all_done
  }, [applyStatus, caseId, stopPolling])

  const startPolling = useCallback(() => {
    if (!caseId) return
    allDoneFiredRef.current = false
    stopPolling()
    void fetchStatus()
    pollRef.current = setInterval(() => {
      void fetchStatus()
    }, pollIntervalMs)
  }, [caseId, fetchStatus, pollIntervalMs, stopPolling])

  /** После upload/import: добавить файлы в UI-статус и запустить polling. */
  const ingestUploadResponse = useCallback(
    (response: FilesResponse) => {
      const fromApi = response.files ?? []
      if (fromApi.length > 0) {
        setProcessingFiles((prev) =>
          mergeProcessingFiles(prev, uploadedToProcessing(fromApi)),
        )
      }
      setAllDone(false)
      setAnyProcessing(true)
      allDoneFiredRef.current = false
      startPolling()
    },
    [startPolling],
  )

  const processingMap: Record<string, string> = {}
  for (const f of processingFiles) {
    processingMap[f.id] = f.status
  }

  useEffect(() => {
    if (!caseId) {
      setProcessingFiles([])
      setAllDone(false)
      setAnyProcessing(false)
      allDoneFiredRef.current = false
      stopPolling()
      return
    }
    void fetchStatus().then((done) => {
      if (!done) startPolling()
    })
    return stopPolling
  }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps

  return {
    processingFiles,
    setProcessingFiles,
    processingMap,
    allDone,
    anyProcessing,
    startPolling,
    stopPolling,
    fetchStatus,
    ingestUploadResponse,
    mergeProcessingFiles,
  }
}

export function processingStatusLabel(
  status?: FileProcessingStatus['status'],
  staged?: boolean,
  progress?: FileProcessingStatus['progress'] | null,
): string {
  if (staged) return 'Будет загружен при создании дела'
  switch (status) {
    case 'ready':
      return 'Готово'
    case 'processing': {
      const pct = typeof progress?.percent === 'number' ? ` ${progress.percent}%` : ''
      const msg = progress?.message?.trim()
      if (msg) return `${msg}${pct}`
      return `Обработка…${pct}`
    }
    case 'pending':
      return 'В очереди'
    case 'error':
      return 'Ошибка'
    case 'cancelled':
      return 'Отменено'
    case undefined:
      return 'Ожидает загрузки'
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}
