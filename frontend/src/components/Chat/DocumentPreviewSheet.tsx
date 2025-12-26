import React, { useState, useEffect } from 'react'
import {
  Drawer,
  Box,
  Typography,
  IconButton,
  Button,
  Chip,
  Divider,
  Skeleton,
  Stack,
  Tooltip,
} from '@mui/material'
import {
  FileText as FileTextIcon,
  Download as DownloadIcon,
  ContentCopy as CopyIcon,
  Check as CheckIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  OpenInNew as MaximizeIcon,
} from '@mui/icons-material'
import { SourceInfo } from '@/services/api'

interface DocumentPreviewSheetProps {
  isOpen: boolean
  onClose: () => void
  source: SourceInfo | null
  caseId: string
  allSources?: SourceInfo[]
  onNavigate?: (source: SourceInfo) => void
}

const DocumentPreviewSheet: React.FC<DocumentPreviewSheetProps> = ({
  isOpen,
  onClose,
  source,
  caseId,
  allSources = [],
  onNavigate
}) => {
  const [copied, setCopied] = useState(false)
  const [documentContent, setDocumentContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const currentIndex = source ? allSources.findIndex(s => s.file === source.file) : -1
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex < allSources.length - 1

  useEffect(() => {
    if (source && isOpen) {
      loadDocumentContent()
    }
  }, [source, isOpen])

  const loadDocumentContent = async () => {
    if (!source) return
    
    setLoading(true)
    try {
      // Try to get document content from API
      const response = await fetch(`/api/cases/${caseId}/files/${encodeURIComponent(source.file)}/content`)
      if (response.ok) {
        const data = await response.json()
        setDocumentContent(data.content || source.text_preview || '')
      } else {
        // Fallback to text_preview
        setDocumentContent(source.text_preview || 'Содержимое документа недоступно для предпросмотра')
      }
    } catch (error) {
      setDocumentContent(source.text_preview || 'Ошибка загрузки содержимого')
    } finally {
      setLoading(false)
    }
  }

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
            <FileTextIcon color="primary" sx={{ mt: 0.5 }} />
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
                  href={`/api/cases/${caseId}/files/${encodeURIComponent(source.file)}/download`}
                  download
                >
                  <DownloadIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Открыть в полном окне">
                <IconButton
                  size="small"
                  component="a"
                  href={`/cases/${caseId}/workspace?file=${encodeURIComponent(source.file)}`}
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
            overflow: 'auto',
            p: 2,
          }}
        >
          {loading ? (
            <Stack spacing={1}>
              <Skeleton variant="text" width="100%" />
              <Skeleton variant="text" width="75%" />
              <Skeleton variant="text" width="50%" />
            </Stack>
          ) : (
            <>
              {source.text_preview && (
                <Paper
                  elevation={0}
                  sx={{
                    p: 2,
                    mb: 2,
                    bgcolor: 'primary.main',
                    opacity: 0.05,
                    border: '1px solid',
                    borderColor: 'primary.main',
                    borderRadius: 2,
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Box
                      sx={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        bgcolor: 'primary.main',
                        animation: 'pulse 2s infinite',
                      }}
                    />
                    <Typography variant="caption" fontWeight={500} color="primary.main">
                      Цитируемый фрагмент
                    </Typography>
                  </Box>
                  <Typography variant="body2" sx={{ lineHeight: 1.75 }}>
                    {source.text_preview}
                  </Typography>
                </Paper>
              )}

              {documentContent && documentContent !== source.text_preview && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Typography variant="caption" fontWeight={500} color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                    Полный текст документа:
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{
                      whiteSpace: 'pre-wrap',
                      lineHeight: 1.75,
                      color: 'text.secondary',
                    }}
                  >
                    {documentContent}
                  </Typography>
                </>
              )}
            </>
          )}
        </Box>
      </Box>
    </Drawer>
  )
}

export default DocumentPreviewSheet

