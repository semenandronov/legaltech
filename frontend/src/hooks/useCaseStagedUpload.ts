import { useEffect, useState } from 'react'
import {
  getCaseStagedUploadSnapshot,
  subscribeCaseStagedUpload,
  type CaseStagedUploadSnapshot,
} from '@/lib/caseStagedUploadCoordinator'

export function useCaseStagedUpload(caseId: string | undefined) {
  const [snapshot, setSnapshot] = useState<CaseStagedUploadSnapshot | null>(() =>
    caseId ? getCaseStagedUploadSnapshot(caseId) : null,
  )

  useEffect(() => {
    if (!caseId) {
      setSnapshot(null)
      return
    }
    return subscribeCaseStagedUpload(caseId, setSnapshot)
  }, [caseId])

  return {
    snapshot,
    isUploading: snapshot?.phase === 'uploading',
    isError: snapshot?.phase === 'error',
    pendingRows: snapshot?.pendingRows ?? [],
    statusMessage: snapshot?.statusMessage ?? '',
    errorMessage: snapshot?.errorMessage,
  }
}
