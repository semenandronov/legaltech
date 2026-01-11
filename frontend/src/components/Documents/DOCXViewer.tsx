import React, { useState, useEffect } from 'react'
import mammoth from 'mammoth'
import {
  Box,
  IconButton,
  TextField,
  InputAdornment,
  Stack,
  Typography,
  Paper,
  Divider,
  Chip,
  Skeleton,
} from '@mui/material'
import {
  ZoomIn as ZoomInIcon,
  ZoomOut as ZoomOutIcon,
  Search as SearchIcon,
  Close as CloseIcon,
  Download as DownloadIcon,
  Print as PrintIcon,
  Info as InfoIcon,
} from '@mui/icons-material'
import './Documents.css'

interface DOCXViewerProps {
  fileId: string
  caseId: string
  filename: string
  onError?: (error: Error) => void
  showAbout?: boolean
  metadata?: {
    file_type?: string
    created_at?: string
    file_size?: number
    [key: string]: any
  }
}

const DOCXViewer: React.FC<DOCXViewerProps> = ({
  fileId,
  caseId,
  filename: _filename,
  onError,
  showAbout = false,
  metadata,
}) => {
  const [htmlContent, setHtmlContent] = useState<string>('')
  const [docxUrl, setDocxUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scale, setScale] = useState(1.0)
  const [searchQuery, setSearchQuery] = useState('')
  const [showAboutPanel, setShowAboutPanel] = useState(showAbout)

  useEffect(() => {
    loadDOCX()
    return () => {
      // Cleanup: revoke object URL if it exists
      if (docxUrl && docxUrl.startsWith('blob:')) {
        URL.revokeObjectURL(docxUrl)
      }
    }
  }, [fileId, caseId])

  const loadDOCX = async () => {
    try {
      setLoading(true)
      setError(null)

      const baseUrl = import.meta.env.VITE_API_URL || ''
      const url = baseUrl 
        ? `${baseUrl}/api/cases/${caseId}/files/${fileId}/content`
        : `/api/cases/${caseId}/files/${fileId}/content`

      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      })

      if (!response.ok) {
        throw new Error(`Failed to load document: ${response.statusText}`)
      }

      const blob = await response.blob()
      const urlObj = URL.createObjectURL(blob)
      setDocxUrl(urlObj)

      // Convert DOCX to HTML using mammoth
      const arrayBuffer = await blob.arrayBuffer()
      const result = await mammoth.convertToHtml({ arrayBuffer })
      
      setHtmlContent(result.value)
      
      // Log warnings if any
      if (result.messages.length > 0) {
        console.warn('Mammoth conversion warnings:', result.messages)
      }
    } catch (err: any) {
      console.error('Error loading DOCX:', err)
      setError(err.message || 'Ошибка при загрузке документа')
      if (onError) {
        onError(err)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleZoomIn = () => {
    setScale(prev => Math.min(3, prev + 0.1))
  }

  const handleZoomOut = () => {
    setScale(prev => Math.max(0.5, prev - 0.1))
  }

  const handleSearch = (query: string) => {
    setSearchQuery(query)
    // Note: Search functionality can be enhanced in the future
    // For now, we just store the query
  }

  const handleClearSearch = () => {
    setSearchQuery('')
  }

  const handleDownload = () => {
    if (docxUrl) {
      const link = document.createElement('a')
      link.href = docxUrl
      link.download = _filename || 'document.docx'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    }
  }

  const handlePrint = () => {
    if (docxUrl) {
      window.open(docxUrl, '_blank')
    }
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', p: 3 }}>
        <Skeleton variant="rectangular" width="100%" height={400} sx={{ mb: 2 }} />
        <Typography variant="body2" color="text.secondary">Загрузка документа...</Typography>
      </Box>
    )
  }

  if (error) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', p: 3 }}>
        <Typography variant="h6" color="error" sx={{ mb: 1 }}>Ошибка загрузки документа</Typography>
        <Typography variant="body2" color="text.secondary">{error}</Typography>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
          Документ может быть недоступен или иметь неподдерживаемый формат.
        </Typography>
      </Box>
    )
  }

  if (!htmlContent) {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', p: 3 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>Документ не найден</Typography>
        <Typography variant="body2" color="text.secondary">Не удалось загрузить содержимое документа.</Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <Paper
        elevation={0}
        sx={{
          p: 1,
          borderBottom: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        {/* Search */}
        <TextField
          size="small"
          placeholder="Поиск в документе..."
          value={searchQuery}
          onChange={(e) => handleSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
            endAdornment: searchQuery ? (
              <InputAdornment position="end">
                <IconButton
                  size="small"
                  onClick={handleClearSearch}
                >
                  <CloseIcon fontSize="small" />
                </IconButton>
              </InputAdornment>
            ) : null,
          }}
          sx={{ width: 250 }}
        />

        <Box sx={{ flexGrow: 1 }} />

        {/* Zoom controls */}
        <Stack direction="row" spacing={0.5} alignItems="center">
          <IconButton size="small" onClick={handleZoomOut} aria-label="Уменьшить">
            <ZoomOutIcon />
          </IconButton>
          <Typography variant="body2" sx={{ minWidth: 50, textAlign: 'center' }}>
            {Math.round(scale * 100)}%
          </Typography>
          <IconButton size="small" onClick={handleZoomIn} aria-label="Увеличить">
            <ZoomInIcon />
          </IconButton>
        </Stack>

        <Divider orientation="vertical" flexItem sx={{ mx: 1 }} />

        {/* Actions */}
        <Stack direction="row" spacing={0.5}>
          {showAbout && (
            <IconButton
              size="small"
              onClick={() => setShowAboutPanel(!showAboutPanel)}
              color={showAboutPanel ? 'primary' : 'default'}
            >
              <InfoIcon />
            </IconButton>
          )}
          <IconButton size="small" onClick={handleDownload} aria-label="Скачать">
            <DownloadIcon />
          </IconButton>
          <IconButton size="small" onClick={handlePrint} aria-label="Печать">
            <PrintIcon />
          </IconButton>
        </Stack>
      </Paper>

      {/* Content area */}
      <Box sx={{ flex: 1, overflow: 'auto', position: 'relative', display: 'flex' }}>
        {/* DOCX Viewer */}
        <Box 
          sx={{ 
            flex: 1, 
            overflow: 'auto', 
            p: 3, 
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
            width: `${100 / scale}%`,
            height: `${100 / scale}%`,
          }}
        >
          <div 
            className="docx-wrapper"
            dangerouslySetInnerHTML={{ __html: htmlContent }}
            style={{
              backgroundColor: 'white',
              padding: '40px',
              maxWidth: '816px',
              margin: '0 auto',
              boxShadow: '0 0 10px rgba(0,0,0,0.1)',
            }}
          />
        </Box>

        {/* About/Metadata Panel */}
        {showAboutPanel && metadata && (
          <Paper
            elevation={0}
            sx={{
              width: 300,
              borderLeft: 1,
              borderColor: 'divider',
              p: 2,
              overflow: 'auto',
            }}
          >
            <Stack spacing={2}>
              <Typography variant="h6">О документе</Typography>
              <Divider />
              {metadata.file_type && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Тип файла
                  </Typography>
                  <Chip label={metadata.file_type.toUpperCase()} size="small" sx={{ mt: 0.5 }} />
                </Box>
              )}
              {metadata.created_at && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Дата создания
                  </Typography>
                  <Typography variant="body2">
                    {new Date(metadata.created_at).toLocaleDateString('ru-RU')}
                  </Typography>
                </Box>
              )}
              {metadata.file_size && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Размер файла
                  </Typography>
                  <Typography variant="body2">
                    {(metadata.file_size / 1024).toFixed(2)} KB
                  </Typography>
                </Box>
              )}
              {_filename && (
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Имя файла
                  </Typography>
                  <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                    {_filename}
                  </Typography>
                </Box>
              )}
            </Stack>
          </Paper>
        )}
      </Box>
    </Box>
  )
}

export default DOCXViewer
