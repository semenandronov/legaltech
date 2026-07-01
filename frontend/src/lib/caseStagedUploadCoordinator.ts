import {
  uploadStagedFilesToCase,
  type PostCreateUploadPayload,
  type UploadStagedFilesResult,
} from './casePostCreateUpload'
import { buildPostCreatePendingRows, type PostCreatePendingRow } from './postCreatePendingFiles'
import type { FilesResponse } from '../services/api'

export type CaseStagedUploadPhase = 'uploading' | 'done' | 'error'

export type CaseStagedUploadSnapshot = {
  phase: CaseStagedUploadPhase
  statusMessage: string
  pendingRows: PostCreatePendingRow[]
  responses: FilesResponse[]
  driveErrors: string[]
  errorMessage?: string
}

type UploadListener = (snapshot: CaseStagedUploadSnapshot) => void

type InflightUpload = {
  snapshot: CaseStagedUploadSnapshot
  listeners: Set<UploadListener>
  promise: Promise<UploadStagedFilesResult>
}

const inflightByCaseId = new Map<string, InflightUpload>()
const appliedResultCaseIds = new Set<string>()

function notify(job: InflightUpload) {
  for (const listener of job.listeners) {
    listener(job.snapshot)
  }
}

function buildUploadingSnapshot(payload: PostCreateUploadPayload): CaseStagedUploadSnapshot {
  const pendingRows = buildPostCreatePendingRows(payload)
  const fileCount = pendingRows.length
  return {
    phase: 'uploading',
    statusMessage:
      fileCount === 1 ? 'Загрузка файла…' : `Загрузка файлов (0 из ${fileCount})…`,
    pendingRows,
    responses: [],
    driveErrors: [],
  }
}

/**
 * Стартует загрузку staged-файлов в дело. Повторный вызов для того же caseId
 * возвращает уже идущую задачу (устойчиво к React StrictMode и remount).
 */
export function startCaseStagedUpload(
  caseId: string,
  payload: PostCreateUploadPayload,
): CaseStagedUploadSnapshot {
  const existing = inflightByCaseId.get(caseId)
  if (existing) return existing.snapshot

  const job: InflightUpload = {
    snapshot: buildUploadingSnapshot(payload),
    listeners: new Set(),
    promise: Promise.resolve({ responses: [], driveErrors: [] }),
  }

  job.promise = uploadStagedFilesToCase(caseId, payload, {
    onStep: (message) => {
      job.snapshot = { ...job.snapshot, statusMessage: message }
      notify(job)
    },
  })
    .then((result) => {
      job.snapshot = {
        phase: 'done',
        statusMessage: '',
        pendingRows: [],
        responses: result.responses,
        driveErrors: result.driveErrors,
      }
      notify(job)
      return result
    })
    .catch((error: unknown) => {
      const message = error instanceof Error ? error.message : 'Не удалось загрузить файлы'
      job.snapshot = {
        ...job.snapshot,
        phase: 'error',
        statusMessage: '',
        pendingRows: job.snapshot.pendingRows.map((row) => ({
          ...row,
          status: 'error',
          errorDetail: message,
        })),
        errorMessage: message,
      }
      notify(job)
      throw error
    })

  inflightByCaseId.set(caseId, job)
  return job.snapshot
}

export function getCaseStagedUploadSnapshot(caseId: string): CaseStagedUploadSnapshot | null {
  return inflightByCaseId.get(caseId)?.snapshot ?? null
}

export function subscribeCaseStagedUpload(
  caseId: string,
  listener: UploadListener,
): () => void {
  const job = inflightByCaseId.get(caseId)
  if (!job) return () => {}

  listener(job.snapshot)
  job.listeners.add(listener)
  return () => {
    job.listeners.delete(listener)
  }
}

export function awaitCaseStagedUpload(caseId: string): Promise<UploadStagedFilesResult | null> {
  const job = inflightByCaseId.get(caseId)
  if (!job) return Promise.resolve(null)
  return job.promise
}

export function clearCaseStagedUpload(caseId: string): void {
  const job = inflightByCaseId.get(caseId)
  if (!job) return
  job.listeners.clear()
  inflightByCaseId.delete(caseId)
}

/** Гарантирует однократное применение результата на странице дела (StrictMode-safe). */
export function consumeCaseStagedUploadResult(
  caseId: string,
  onResult: (result: UploadStagedFilesResult) => void,
): boolean {
  const job = inflightByCaseId.get(caseId)
  if (!job || job.snapshot.phase !== 'done') return false
  if (appliedResultCaseIds.has(caseId)) return false

  appliedResultCaseIds.add(caseId)
  onResult({
    responses: job.snapshot.responses,
    driveErrors: job.snapshot.driveErrors,
  })
  clearCaseStagedUpload(caseId)
  window.setTimeout(() => appliedResultCaseIds.delete(caseId), 60_000)
  return true
}

export function resetCaseStagedUploadCoordinatorForTests(): void {
  inflightByCaseId.clear()
  appliedResultCaseIds.clear()
}
