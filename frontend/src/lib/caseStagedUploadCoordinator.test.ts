import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  getCaseStagedUploadSnapshot,
  resetCaseStagedUploadCoordinatorForTests,
  startCaseStagedUpload,
  subscribeCaseStagedUpload,
} from './caseStagedUploadCoordinator'
import * as casePostCreateUpload from './casePostCreateUpload'

describe('caseStagedUploadCoordinator', () => {
  afterEach(() => {
    resetCaseStagedUploadCoordinatorForTests()
    vi.restoreAllMocks()
  })

  it('deduplicates upload per caseId', async () => {
    const uploadSpy = vi.spyOn(casePostCreateUpload, 'uploadStagedFilesToCase').mockResolvedValue({
      responses: [{ files: [], total: 0 }],
      driveErrors: [],
    })

    const payload = {
      locals: [{ kind: 'local' as const, key: 'k1', file: new File(['x'], 'a.pdf') }],
      drives: [],
    }

    const first = startCaseStagedUpload('case-1', payload)
    const second = startCaseStagedUpload('case-1', payload)

    expect(first.pendingRows).toHaveLength(1)
    expect(second).toBe(first)
    expect(uploadSpy).toHaveBeenCalledTimes(1)

    await vi.waitFor(() => {
      expect(getCaseStagedUploadSnapshot('case-1')?.phase).toBe('done')
    })
  })

  it('notifies subscribers across remounts', async () => {
    vi.spyOn(casePostCreateUpload, 'uploadStagedFilesToCase').mockImplementation(
      async (_caseId, _payload, callbacks) => {
        callbacks?.onStep?.('Загрузка 1 из 1: doc.pdf', 50)
        return { responses: [{ files: [{ id: 'f1', filename: 'doc.pdf', file_type: 'pdf' }], total: 1 }], driveErrors: [] }
      },
    )

    const payload = {
      locals: [{ kind: 'local' as const, key: 'k1', file: new File(['x'], 'doc.pdf') }],
      drives: [],
    }

    startCaseStagedUpload('case-2', payload)

    const messages: string[] = []
    const unsubscribe = subscribeCaseStagedUpload('case-2', (snapshot) => {
      if (snapshot.statusMessage) messages.push(snapshot.statusMessage)
    })

    await vi.waitFor(() => {
      expect(getCaseStagedUploadSnapshot('case-2')?.phase).toBe('done')
    })

    expect(messages.length).toBeGreaterThan(0)
    unsubscribe()
  })
})
