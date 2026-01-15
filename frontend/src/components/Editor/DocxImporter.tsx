import React, { useRef, useState } from 'react'
import { Upload, FileText, Loader2, FolderOpen } from 'lucide-react'
import { Button } from '@/components/UI/Button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/UI/dialog'
import { toast } from 'sonner'
import mammoth from 'mammoth'
import { getFileHtml } from '../../services/fileHtmlApi'

interface DocxImporterProps {
  isOpen: boolean
  onClose: () => void
  onImport: (html: string) => void
  caseId?: string  // Optional: for importing from uploaded files
  fileId?: string  // Optional: for importing specific uploaded file
}

export const DocxImporter: React.FC<DocxImporterProps> = ({
  isOpen,
  onClose,
  onImport,
  caseId,
  fileId,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [loading, setLoading] = useState(false)
  
  const handleImportFromFile = async () => {
    if (!caseId || !fileId) {
      toast.error('Не указаны параметры для импорта из загруженного файла')
      return
    }

    try {
      setLoading(true)
      const htmlResponse = await getFileHtml(caseId, fileId, false)
      onImport(htmlResponse.html)
      toast.success('Документ успешно импортирован из загруженного файла')
      onClose()
    } catch (error: any) {
      console.error('Error importing from uploaded file:', error)
      toast.error(error.message || 'Ошибка при импорте из загруженного файла')
    } finally {
      setLoading(false)
    }
  }

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    if (!file.name.endsWith('.docx')) {
      toast.error('Пожалуйста, выберите файл .docx')
      return
    }

    try {
      setLoading(true)
      const arrayBuffer = await file.arrayBuffer()
      
      // Convert DOCX to HTML using mammoth
      const result = await mammoth.convertToHtml({ arrayBuffer })
      const html = result.value

      // Handle warnings
      if (result.messages.length > 0) {
        console.warn('DOCX conversion warnings:', result.messages)
        toast.warning('Некоторые элементы могут быть потеряны при конвертации')
      }

      onImport(html)
      toast.success('Документ успешно импортирован')
      onClose()
      
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    } catch (error: any) {
      console.error('Error importing DOCX:', error)
      toast.error(error.message || 'Ошибка при импорте DOCX файла')
    } finally {
      setLoading(false)
    }
  }

  const handleClick = () => {
    fileInputRef.current?.click()
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="w-5 h-5" />
            Импорт DOCX
          </DialogTitle>
          <DialogDescription>
            Выберите файл .docx для импорта в редактор. Форматирование будет сохранено.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <input
            ref={fileInputRef}
            type="file"
            accept=".docx"
            onChange={handleFileSelect}
            className="hidden"
            disabled={loading}
          />

          {/* Import from uploaded file */}
          {caseId && fileId && (
            <div className="border-2 border-dashed rounded-lg p-6 text-center bg-muted/50">
              <FolderOpen className="w-10 h-10 mx-auto mb-3 text-muted-foreground" />
              <p className="text-sm text-muted-foreground mb-3">
                Импорт из загруженного файла
              </p>
              <Button
                onClick={handleImportFromFile}
                disabled={loading}
                variant="outline"
                size="sm"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Импорт...
                  </>
                ) : (
                  <>
                    <FolderOpen className="w-4 h-4 mr-2" />
                    Импортировать из файла
                  </>
                )}
              </Button>
            </div>
          )}

          {/* Divider if both options available */}
          {caseId && fileId && (
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-background px-2 text-muted-foreground">или</span>
              </div>
            </div>
          )}

          {/* Import from local file */}
          <div className="border-2 border-dashed rounded-lg p-8 text-center">
            <Upload className="w-12 h-12 mx-auto mb-4 text-muted-foreground" />
            <p className="text-sm text-muted-foreground mb-4">
              Выберите файл .docx для импорта
            </p>
            <Button
              onClick={handleClick}
              disabled={loading}
              variant="outline"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Импорт...
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4 mr-2" />
                  Выбрать файл
                </>
              )}
            </Button>
          </div>

          <div className="text-xs text-muted-foreground">
            <p>Поддерживаемые форматы: .docx, .pdf, .xlsx, .txt</p>
            <p className="mt-1">Примечание: Сложное форматирование может быть упрощено при импорте.</p>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button onClick={onClose} variant="outline" disabled={loading}>
            Отмена
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

