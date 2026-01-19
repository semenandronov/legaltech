import { useState, useEffect } from 'react'
import {
  Drawer,
  Box,
  Typography,
  IconButton,
  Chip,
  Divider,
  Skeleton,
  Stack,
  Tooltip,
} from '@mui/material'
import {
  Description as DescriptionIcon,
  Download as DownloadIcon,
  ContentCopy as CopyIcon,
  Check as CheckIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  OpenInNew as MaximizeIcon,
} from '@mui/icons-material'
import { SourceInfo } from '@/services/api'
import PDFViewer from '@/components/Documents/PDFViewer'
import { DocumentHighlighter, useCitationHighlights } from '@/components/Documents/DocumentHighlighter'
import { TextHighlighter } from '@/components/TabularReview/TextHighlighter'
import { getFileHtml } from '@/services/fileHtmlApi'
import { getDocumentContent } from '@/services/api'

interface DocumentPreviewSheetProps {
  isOpen: boolean
  onClose: () => void
  source: SourceInfo | null
  caseId: string
  allSources?: SourceInfo[]
  onNavigate?: (source: SourceInfo) => void
}

const DocumentPreviewSheet = ({
  isOpen,
  onClose,
  source,
  caseId,
  allSources = [],
  onNavigate
}: DocumentPreviewSheetProps) => {
  const [copied, setCopied] = useState(false)
  const [documentContent, setDocumentContent] = useState<string | null>(null)
  const [documentText, setDocumentText] = useState<string | null>(null) // Текстовый контент для подсветки
  const [documentHtml, setDocumentHtml] = useState<string | null>(null) // HTML контент для DOCX
  const [loading, setLoading] = useState(false)
  const [fileInfo, setFileInfo] = useState<{ id: string; file_type: string; filename: string } | null>(null)
  const [fileUrl, setFileUrl] = useState<string | null>(null)

  const currentIndex = source ? allSources.findIndex(s => s.file === source.file) : -1
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex < allSources.length - 1
  
  // Преобразуем source в highlights для DocumentHighlighter (для текстовых документов)
  const highlights = useCitationHighlights(source && source.char_start !== undefined && source.char_end !== undefined ? [source] : [])

  useEffect(() => {
    if (source && isOpen) {
      loadDocumentInfo()
    }
  }, [source, isOpen])


  const loadDocumentInfo = async () => {
    if (!source) return
    
    setLoading(true)
    setFileInfo(null)
    setDocumentContent(null)
    setDocumentText(null)
    setDocumentHtml(null)
    
    try {
      // Get list of files to find file by filename or id
      const filesResponse = await fetch(`/api/cases/${caseId}/files`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      })
      
      if (!filesResponse.ok) {
        setDocumentContent('Ошибка загрузки списка документов')
        return
      }
      
      const filesData = await filesResponse.json()
      
      // Try to find file: first by source_id (if available), then by filename, then by id
      let file = null
      if ((source as any).source_id) {
        file = filesData.documents?.find((f: any) => f.id === (source as any).source_id)
      }
      if (!file && source.file) {
        file = filesData.documents?.find((f: any) => f.filename === source.file || f.id === source.file)
      }
      
      if (file) {
        // Found file - open it completely, just like on Documents page
        setFileInfo({
          id: file.id,
          file_type: file.file_type || 'txt',
          filename: file.filename
        })
        
        // Загружаем контент для подсветки в зависимости от типа файла
        await loadDocumentContentForHighlight(file.id, file.file_type || 'txt', source)
      } else {
        // File not found - show preview text if available
        setDocumentContent(source.text_preview || 'Документ не найден')
      }
    } catch (error) {
      console.error('Error loading document:', error)
      setDocumentContent('Ошибка загрузки документа')
    } finally {
      setLoading(false)
    }
  }
  
  // Загрузка контента документа для подсветки
  const loadDocumentContentForHighlight = async (
    fileId: string, 
    fileType: string, 
    source: SourceInfo
  ) => {
    // Проверяем, есть ли координаты для подсветки
    const hasCoordinates = source.char_start !== undefined && source.char_end !== undefined
    const hasQuote = !!source.quote
    
    if (!hasCoordinates && !hasQuote) {
      // Нет данных для подсветки - пропускаем
      return
    }
    
    try {
      // Определяем тип файла
      const isTextFile = ['txt', 'html', 'md', 'json', 'xml', 'csv'].includes(fileType.toLowerCase())
      const isDocx = fileType.toLowerCase() === 'docx'
      
      if (isTextFile && hasCoordinates) {
        // Текстовые документы - загружаем текст для точной подсветки по координатам
        try {
          const textBlob = await getDocumentContent(caseId, fileId)
          const text = await textBlob.text()
          setDocumentText(text)
        } catch (error) {
          console.warn('Failed to load text content for highlighting:', error)
        }
      } else if (isDocx && hasQuote) {
        // DOCX - загружаем HTML версию для подсветки по тексту
        try {
          const htmlResponse = await getFileHtml(caseId, fileId, false)
          setDocumentHtml(htmlResponse.html)
        } catch (error) {
          console.warn('Failed to load HTML content for DOCX highlighting:', error)
        }
      }
    } catch (error) {
      console.warn('Error loading document content for highlighting:', error)
    }
  }

  useEffect(() => {
    // Загружаем файл и создаем blob URL для не-PDF файлов
    // ИСПРАВЛЕНИЕ: Используем /content endpoint вместо /download для inline отображения
    if (isOpen && fileInfo && fileInfo.file_type !== 'pdf' && fileInfo.id && caseId) {
      const loadFile = async () => {
        try {
          const baseUrl = import.meta.env.VITE_API_URL || ''
          // Используем /content endpoint вместо /download для inline отображения
          const url = baseUrl 
            ? `${baseUrl}/api/cases/${caseId}/files/${fileInfo.id}/content`
            : `/api/cases/${caseId}/files/${fileInfo.id}/content`
          
          const response = await fetch(url, {
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('access_token')}`
            }
          })
          
          if (response.ok) {
            const blob = await response.blob()
            const blobUrl = window.URL.createObjectURL(blob)
            setFileUrl(blobUrl)
          }
        } catch (error) {
          console.error('Ошибка при загрузке файла:', error)
        }
      }
      
      loadFile()
      
      // Cleanup: revoke blob URL при размонтировании или смене файла
      return () => {
        setFileUrl(prevUrl => {
          if (prevUrl) {
            window.URL.revokeObjectURL(prevUrl)
          }
          return null
        })
      }
    } else {
      // Очищаем blob URL при смене на PDF или отсутствии файла
      setFileUrl(prevUrl => {
        if (prevUrl) {
          window.URL.revokeObjectURL(prevUrl)
        }
        return null
      })
    }
  }, [isOpen, fileInfo?.id, fileInfo?.file_type, caseId])

  const handleCopy = async () => {
    if (documentContent) {
      await navigator.clipboard.writeText(documentContent)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handlePrev = () => {
    if (hasPrev && onNavigate) {
      onNavigate(allSources[currentIndex - 1])
    }
  }

  const handleNext = () => {
    if (hasNext && onNavigate) {
      onNavigate(allSources[currentIndex + 1])
    }
  }


  if (!source) return null

  return (
    <Drawer
      anchor="right"
      open={isOpen}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: { xs: '100%', sm: '500px', lg: '600px' },
        },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
        }}
      >
        {/* Header */}
        <Box
          sx={{
            p: 2,
            borderBottom: '1px solid',
            borderColor: 'divider',
            bgcolor: 'action.hover',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, mb: 2 }}>
            <DescriptionIcon color="primary" sx={{ mt: 0.5 }} />
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography
                variant="h6"
                sx={{
                  fontWeight: 600,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {source.file}
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap' }}>
                {source.page && (
                  <Chip
                    label={`Стр. ${source.page}`}
                    size="small"
                    variant="outlined"
                  />
                )}
                {source.similarity_score !== undefined && (
                  <Chip
                    label={`${Math.round(source.similarity_score * 100)}% релевантность`}
                    size="small"
                    color={source.similarity_score > 0.7 ? 'primary' : 'default'}
                    variant="outlined"
                  />
                )}
              </Stack>
            </Box>
          </Box>
          
          {/* Citation Quote Block - Harvey/Perplexity style */}
          {source.quote && (
            <Box
              sx={{
                mt: 2,
                p: 2,
                bgcolor: 'rgba(254, 240, 138, 0.3)', // Light yellow
                borderLeft: '4px solid #fbbf24', // Yellow accent
                borderRadius: '0 8px 8px 0',
              }}
            >
              <Typography
                variant="caption"
                sx={{
                  display: 'block',
                  mb: 0.5,
                  fontWeight: 600,
                  color: 'text.secondary',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                📌 Цитата из документа
              </Typography>
              <Typography
                variant="body2"
                sx={{
                  fontStyle: 'italic',
                  color: 'text.primary',
                  lineHeight: 1.6,
                }}
              >
                "{source.quote.length > 300 ? source.quote.substring(0, 300) + '...' : source.quote}"
              </Typography>
              {source.char_start !== undefined && source.char_end !== undefined && (
                <Typography
                  variant="caption"
                  sx={{ display: 'block', mt: 1, color: 'text.secondary' }}
                >
                  Позиция: символы {source.char_start} — {source.char_end}
                </Typography>
              )}
            </Box>
          )}

          {/* Navigation & Actions */}
          <Divider sx={{ my: 1.5 }} />
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <Stack direction="row" spacing={0.5} alignItems="center">
              <IconButton
                size="small"
                onClick={handlePrev}
                disabled={!hasPrev}
              >
                <ChevronLeftIcon />
              </IconButton>
              <Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>
                {currentIndex + 1} / {allSources.length}
              </Typography>
              <IconButton
                size="small"
                onClick={handleNext}
                disabled={!hasNext}
              >
                <ChevronRightIcon />
              </IconButton>
            </Stack>

            <Stack direction="row" spacing={0.5}>
              <Tooltip title="Копировать">
                <IconButton size="small" onClick={handleCopy}>
                  {copied ? (
                    <CheckIcon color="success" fontSize="small" />
                  ) : (
                    <CopyIcon fontSize="small" />
                  )}
                </IconButton>
              </Tooltip>
              <Tooltip title="Скачать">
                <IconButton
                  size="small"
                  component="a"
                  href={fileInfo ? `/api/cases/${caseId}/files/${fileInfo.id}/download` : `#`}
                  download
                >
                  <DownloadIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Открыть в полном окне">
                <IconButton
                  size="small"
                  component="a"
                  href={`/cases/${caseId}/chat?file=${encodeURIComponent(source.file)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <MaximizeIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>
          </Box>
        </Box>

        {/* Content */}
        <Box
          sx={{
            flex: 1,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {loading ? (
            <Box sx={{ p: 2 }}>
              <Stack spacing={1}>
                <Skeleton variant="text" width="100%" />
                <Skeleton variant="text" width="75%" />
                <Skeleton variant="text" width="50%" />
              </Stack>
            </Box>
          ) : fileInfo && fileInfo.file_type === 'pdf' ? (
            // PDF viewer - like on Documents page, with highlighting support
            <Box sx={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              {/* Подсказка для поиска цитаты в PDF */}
              {source.quote && (
                <Box
                  sx={{
                    p: 1.5,
                    bgcolor: 'info.light',
                    color: 'info.contrastText',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    fontSize: '0.75rem',
                  }}
                >
                  <SearchIcon fontSize="small" />
                  <Typography variant="caption">
                    Используйте поиск (Ctrl+F) для нахождения цитаты в документе
                  </Typography>
                </Box>
              )}
              <Box sx={{ flex: 1, overflow: 'hidden' }}>
                <PDFViewer
                  fileId={fileInfo.id}
                  caseId={caseId}
                  filename={fileInfo.filename}
                  initialPage={source.page} // Переход на страницу из citation
                  showTabs={false}
                  showAbout={false}
                />
              </Box>
            </Box>
          ) : fileInfo && documentHtml && fileInfo.file_type === 'docx' ? (
            // DOCX - отображаем HTML с подсветкой
            <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
              {source.quote ? (
                <TextHighlighter
                  text={documentHtml}
                  highlightText={source.quote}
                  className="whitespace-pre-wrap text-sm"
                />
              ) : (
                <Box
                  component="div"
                  dangerouslySetInnerHTML={{ __html: documentHtml }}
                  sx={{
                    fontSize: '0.875rem',
                    fontFamily: 'inherit',
                  }}
                />
              )}
            </Box>
          ) : fileInfo && documentText && ['txt', 'html', 'md', 'json', 'xml', 'csv'].includes(fileInfo.file_type.toLowerCase()) ? (
            // Текстовые документы - отображаем с подсветкой по координатам
            <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
              {source.char_start !== undefined && source.char_end !== undefined && highlights.length > 0 ? (
                <DocumentHighlighter
                  text={documentText}
                  highlights={highlights}
                  className="whitespace-pre-wrap text-sm"
                />
              ) : (
                <Box
                  component="pre"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    fontSize: '0.875rem',
                    fontFamily: 'monospace',
                    m: 0,
                  }}
                >
                  {documentText}
                </Box>
              )}
            </Box>
          ) : fileInfo && fileUrl ? (
            // For non-PDF files, use object tag instead of iframe to avoid CSP issues
            <Box sx={{ flex: 1, overflow: 'hidden' }}>
              <object
                data={fileUrl}
                type={fileInfo.file_type === 'docx' ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' : 'text/plain'}
                style={{
                  width: '100%',
                  height: '100%',
                  border: 'none',
                  flex: 1
                }}
              >
                <Box sx={{ p: 2, textAlign: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    Браузер не поддерживает отображение этого типа файла.
                    <br />
                    <a 
                      href={`/api/cases/${caseId}/files/${fileInfo.id}/download`}
                      download
                      style={{ color: 'primary.main', textDecoration: 'underline' }}
                    >
                      Скачать файл
                    </a>
                  </Typography>
                </Box>
              </object>
            </Box>
          ) : fileInfo ? (
            // Loading file
            <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                Загрузка документа...
              </Typography>
            </Box>
          ) : (
            <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography variant="body2" color="text.secondary">
                Загрузка информации о документе...
              </Typography>
            </Box>
          )}
        </Box>
      </Box>
    </Drawer>
  )
}

export default DocumentPreviewSheet

