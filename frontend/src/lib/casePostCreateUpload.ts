import {
  addFilesToCase,
  importFilesFromGoogleDrive,
  type FilesResponse,
} from '../services/api'
import {
  groupDriveByToken,
  type StagedDriveFile,
  type StagedLocalFile,
} from './caseFileStaging'

export type PostCreateUploadPayload = {
  locals: StagedLocalFile[]
  drives: StagedDriveFile[]
}

/** React Router location.state после «Создать дело» на /cases/new */
export type CaseOverviewLocationState = {
  postCreateUpload?: PostCreateUploadPayload
}

export type UploadStagedFilesCallbacks = {
  onStep?: (message: string, progressPercent?: number) => void
}

export type UploadStagedFilesResult = {
  responses: FilesResponse[]
  driveErrors: string[]
}

/**
 * Загрузка staged-файлов в уже созданное дело (локальные + Google Drive).
 */
export async function uploadStagedFilesToCase(
  caseId: string,
  { locals, drives }: PostCreateUploadPayload,
  callbacks: UploadStagedFilesCallbacks = {},
): Promise<UploadStagedFilesResult> {
  const { onStep } = callbacks
  const totalSteps = locals.length + groupDriveByToken(drives).size
  const responses: FilesResponse[] = []
  const driveErrors: string[] = []
  let step = 0

  for (const item of locals) {
    step += 1
    onStep?.(`Загрузка ${step} из ${totalSteps}: ${item.file.name}`, 0)
    const result = await addFilesToCase(caseId, [item.file], (percent) => {
      onStep?.(`Загрузка ${step} из ${totalSteps}: ${item.file.name}`, percent)
    })
    responses.push(result)
  }

  for (const [token, driveFiles] of groupDriveByToken(drives)) {
    step += 1
    onStep?.(
      `Импорт из Google Drive (${driveFiles.length} файл.) — шаг ${step} из ${totalSteps}`,
    )
    const result = await importFilesFromGoogleDrive(caseId, {
      access_token: token,
      files: driveFiles.map((f) => ({
        id: f.driveFileId,
        name: f.name,
        mime_type: f.mimeType,
      })),
    })
    responses.push(result)
    const errs = result.errors ?? []
    for (const e of errs) {
      driveErrors.push(`${e.name}: ${e.detail}`)
    }
  }

  return { responses, driveErrors }
}
