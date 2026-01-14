import React, { useState, useEffect } from 'react'
import { History, RotateCcw, Eye, Check, X } from 'lucide-react'
import { Button } from '@/components/UI/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/UI/Card'
import { ScrollArea } from '@/components/UI/scroll-area'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/UI/dialog'
import { toast } from 'sonner'
import { listDocumentVersions, getDocumentVersion, restoreDocumentVersion, DocumentVersion } from '@/services/documentEditorApi'
import { format } from 'date-fns'
import { ru } from 'date-fns/locale'

interface VersionHistoryProps {
  documentId: string
  currentVersion: number
  onVersionRestored: (content: string) => void
  isOpen: boolean
  onClose: () => void
}

export const VersionHistory: React.FC<VersionHistoryProps> = ({
  documentId,
  currentVersion,
  onVersionRestored,
  isOpen,
  onClose,
}) => {
  const [versions, setVersions] = useState<DocumentVersion[]>([])
  const [loading, setLoading] = useState(false)
  const [previewVersion, setPreviewVersion] = useState<DocumentVersion | null>(null)
  const [showPreview, setShowPreview] = useState(false)
  const [restoring, setRestoring] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen && documentId) {
      loadVersions()
    }
  }, [isOpen, documentId])

  const loadVersions = async () => {
    try {
      setLoading(true)
      const data = await listDocumentVersions(documentId)
      // Sort by version number descending
      setVersions(data.sort((a, b) => b.version - a.version))
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при загрузке версий')
    } finally {
      setLoading(false)
    }
  }

  const handlePreview = async (version: number) => {
    try {
      const versionData = await getDocumentVersion(documentId, version)
      setPreviewVersion(versionData)
      setShowPreview(true)
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при загрузке версии')
    }
  }

  const handleRestore = async (version: number) => {
    if (!confirm(`Восстановить документ к версии ${version}? Текущие изменения будут сохранены как новая версия.`)) {
      return
    }

    try {
      setRestoring(version.toString())
      const restored = await restoreDocumentVersion(documentId, version)
      onVersionRestored(restored.content)
      toast.success(`Документ восстановлен к версии ${version}`)
      await loadVersions() // Reload versions
      onClose()
    } catch (error: any) {
      toast.error(error.message || 'Ошибка при восстановлении версии')
    } finally {
      setRestoring(null)
    }
  }

  return (
    <>
      <Dialog open={isOpen} onOpenChange={onClose}>
        <DialogContent className="max-w-2xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <History className="w-5 h-5" />
              История версий
            </DialogTitle>
          </DialogHeader>
          <ScrollArea className="max-h-[60vh]">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
              </div>
            ) : versions.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                Нет сохраненных версий
              </div>
            ) : (
              <div className="space-y-2">
                {versions.map((version) => (
                  <Card
                    key={version.id}
                    className={`${
                      version.version === currentVersion
                        ? 'border-blue-500 bg-blue-50'
                        : ''
                    }`}
                  >
                    <CardContent className="p-4">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-semibold">Версия {version.version}</span>
                            {version.version === currentVersion && (
                              <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                                Текущая
                              </span>
                            )}
                          </div>
                          <div className="text-sm text-muted-foreground">
                            {format(new Date(version.created_at), 'dd MMMM yyyy, HH:mm', {
                              locale: ru,
                            })}
                          </div>
                          {version.created_by && (
                            <div className="text-xs text-muted-foreground mt-1">
                              Автор: {version.created_by}
                            </div>
                          )}
                        </div>
                        <div className="flex gap-2">
                          <Button
                            onClick={() => handlePreview(version.version)}
                            size="sm"
                            variant="outline"
                            className="h-8"
                          >
                            <Eye className="w-4 h-4 mr-1" />
                            Просмотр
                          </Button>
                          {version.version !== currentVersion && (
                            <Button
                              onClick={() => handleRestore(version.version)}
                              size="sm"
                              variant="default"
                              className="h-8"
                              disabled={restoring === version.toString()}
                            >
                              {restoring === version.toString() ? (
                                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                              ) : (
                                <>
                                  <RotateCcw className="w-4 h-4 mr-1" />
                                  Восстановить
                                </>
                              )}
                            </Button>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </ScrollArea>
        </DialogContent>
      </Dialog>

      {/* Preview Dialog */}
      <Dialog open={showPreview} onOpenChange={setShowPreview}>
        <DialogContent className="max-w-4xl max-h-[90vh]">
          <DialogHeader>
            <DialogTitle>
              Просмотр версии {previewVersion?.version}
            </DialogTitle>
          </DialogHeader>
          <ScrollArea className="max-h-[70vh]">
            {previewVersion && (
              <div
                className="prose max-w-none p-4"
                dangerouslySetInnerHTML={{ __html: previewVersion.content }}
              />
            )}
          </ScrollArea>
          <div className="flex justify-end gap-2 mt-4">
            <Button
              onClick={() => {
                if (previewVersion) {
                  handleRestore(previewVersion.version)
                  setShowPreview(false)
                }
              }}
              variant="default"
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              Восстановить эту версию
            </Button>
            <Button onClick={() => setShowPreview(false)} variant="outline">
              Закрыть
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

