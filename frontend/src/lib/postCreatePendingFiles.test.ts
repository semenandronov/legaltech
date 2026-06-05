import { describe, expect, it } from 'vitest'
import {
  buildPostCreatePendingRows,
  formatCaseDocumentCountLabel,
  pendingRowMatchesUploaded,
  removePendingRowsForUploads,
} from './postCreatePendingFiles'
import type { PostCreateUploadPayload } from './casePostCreateUpload'

describe('postCreatePendingFiles', () => {
  it('builds rows from staged payload', () => {
    const payload: PostCreateUploadPayload = {
      locals: [{ kind: 'local', key: 'l1', file: new File(['x'], 'local.pdf') }],
      drives: [
        {
          kind: 'drive',
          key: 'd1',
          driveFileId: 'g1',
          name: 'drive.docx',
          mimeType: 'application/vnd.google-apps.document',
          accessToken: 'tok',
        },
      ],
    }
    const rows = buildPostCreatePendingRows(payload)
    expect(rows).toHaveLength(2)
    expect(rows[0].filename).toBe('local.pdf')
    expect(rows[1].source).toBe('drive')
  })

  it('matches drive export rename by stem', () => {
    const row = {
      stagingKey: 'd1',
      filename: 'Доверенность.gdoc',
      source: 'drive' as const,
      status: 'uploading' as const,
    }
    expect(
      pendingRowMatchesUploaded(row, {
        id: 'f1',
        filename: 'Доверенность.pdf',
        file_type: 'pdf',
      }),
    ).toBe(true)
  })

  it('removes pending when upload returns file', () => {
    const prev = [
      {
        stagingKey: 'a',
        filename: 'a.pdf',
        source: 'local' as const,
        status: 'uploading' as const,
      },
    ]
    const next = removePendingRowsForUploads(prev, [
      { id: '1', filename: 'a.pdf', file_type: 'pdf' },
    ])
    expect(next).toHaveLength(0)
  })

  it('shows uploading label in header', () => {
    const label = formatCaseDocumentCountLabel(0, 0, [
      { stagingKey: 'a', filename: 'x.pdf', source: 'local', status: 'uploading' },
    ], true)
    expect(label).toContain('загрузка')
  })
})
