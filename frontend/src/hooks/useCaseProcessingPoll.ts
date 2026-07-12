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
  incoming: Array<{
    id: string
    filename: string
    processing_status?: string
    status?: string
    error?: string | null
    progress?: FileProcessingStatus['progress']
  }>,
): FileProcessingStatus[] {
  const map = new Map(prev.map((f) => [f.id, f]))
  for (const f of incoming) {
    map.set(f.id, {
      id: f.id,
      filename: f.filename,
      status: ((f.status || f.processing_status) as FileProcessingStatus['status']) || 'pending',
      error: f.error ?? null,
      progress: f.progress ?? null,
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
}

/**
 * Единый polling статусов обработки файлов дела после upload/import.
 */
export function useCaseProcessingPoll(
  caseId: string | null,
  options: UseCaseProcessingPollOptions = {},
) {
  const { pollIntervalMs = DEFAULT_POLL_MS, onAllDone } = options
  const onAllDoneRef = useRef(onAllDone)
  onAllDoneRef.current = onAllDone

  const [processingFiles, setProcessingFiles] = useState<FileProcessingStatus[]>([])
  const [allDone, setAllDone] = useState(false)
  const [anyProcessing, setAnyProcessing] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

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
    },
    [],
  )

  const fetchStatus = useCallback(async (): Promise<boolean> => {
    if (!caseId) return false
    const status = await getProcessingStatus(caseId)
    applyStatus(status.files, status.all_done, status.any_processing)
    if (status.all_done) {
      stopPolling()
      onAllDoneRef.current?.(caseId)
    }
    return status.all_done
  }, [applyStatus, caseId, stopPolling])

  const startPolling = useCallback(() => {
    if (!caseId) return
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
