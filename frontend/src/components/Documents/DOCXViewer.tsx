import React, { useState, useEffect, useRef } from 'react'
import { renderAsync } from 'docx-preview'
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
  const containerRef = useRef<HTMLDivElement>(null)
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

      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DOCXViewer.tsx:66',message:'loadDOCX started',data:{fileId,caseId,filename:_filename},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
      // #endregion

      // Clear previous content
      if (containerRef.current) {
        containerRef.current.innerHTML = ''
      }

      const baseUrl = import.meta.env.VITE_API_URL || ''
      const url = baseUrl 
        ? `${baseUrl}/api/cases/${caseId}/files/${fileId}/content`
        : `/api/cases/${caseId}/files/${fileId}/content`

      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DOCXViewer.tsx:81',message:'Before fetch',data:{url,hasContainer:!!containerRef.current},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
      // #endregion

      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      })

      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DOCXViewer.tsx:87',message:'After fetch',data:{status:response.status,statusText:response.statusText,ok:response.ok,contentType:response.headers.get('content-type')},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'A'})}).catch(()=>{});
      // #endregion

      if (!response.ok) {
        throw new Error(`Failed to load document: ${response.statusText}`)
      }

      const blob = await response.blob()

      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DOCXViewer.tsx:94',message:'Blob created',data:{blobSize:blob.size,blobType:blob.type,hasContainer:!!containerRef.current},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'B'})}).catch(()=>{});
      // #endregion

      const urlObj = URL.createObjectURL(blob)
      setDocxUrl(urlObj)

      // Render DOCX document
      if (containerRef.current) {
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DOCXViewer.tsx:99',message:'Before renderAsync',data:{containerExists:!!containerRef.current,containerInnerHTML:containerRef.current?.innerHTML?.substring(0,50)},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
        // #endregion

        await renderAsync(blob, containerRef.current, undefined, {
          className: 'docx-wrapper',
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          ignoreFonts: false,
          breakPages: true,
          experimental: false,
          trimXmlDeclaration: true,
          useBase64URL: false,
        })

        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DOCXViewer.tsx:111',message:'After renderAsync success',data:{containerInnerHTML:containerRef.current?.innerHTML?.substring(0,100),containerChildren:containerRef.current?.children?.length},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'D'})}).catch(()=>{});
        // #endregion
      } else {
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DOCXViewer.tsx:115',message:'Container ref is null',data:{},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'C'})}).catch(()=>{});
        // #endregion
      }
    } catch (err: any) {
      console.error('Error loading DOCX:', err)
      
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DOCXViewer.tsx:120',message:'Error caught',data:{errorMessage:err?.message,errorName:err?.name,errorStack:err?.stack?.substring(0,200)},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'E'})}).catch(()=>{});
      // #endregion

      setError(err.message || 'Ошибка при загрузке документа')
      if (onError) {
        onError(err)
      }
    } finally {
      setLoading(false)

      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/2db1e09b-2b5d-4ee0-85d8-a551f942254c',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'DOCXViewer.tsx:129',message:'loadDOCX finished',data:{loading:false},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'F'})}).catch(()=>{});
      // #endregion
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
    if (!query.trim()) {
      return
    }
    
    // Simple text search in the rendered document
    if (containerRef.current) {
      const content = containerRef.current.textContent || ''
      const regex = new RegExp(query, 'gi')
      const matches = content.match(regex)
      
      if (matches && matches.length > 0) {
        // Highlight matches (simple implementation)
        // Note: docx-preview doesn't have built-in search, so this is a basic text search
        const walker = document.createTreeWalker(
          containerRef.current,
          NodeFilter.SHOW_TEXT,
          null
        )
        
        const textNodes: Text[] = []
        let node
        while (node = walker.nextNode()) {
          textNodes.push(node as Text)
        }
        
        textNodes.forEach(textNode => {
          if (textNode.textContent && regex.test(textNode.textContent)) {
            const parent = textNode.parentElement
            if (parent && !parent.classList.contains('highlighted')) {
              const highlighted = document.createElement('mark')
              highlighted.style.backgroundColor = 'yellow'
              highlighted.textContent = textNode.textContent
              textNode.parentNode?.replaceChild(highlighted, textNode)
            }
          }
        })
      }
    }
  }

  const handleClearSearch = () => {
    setSearchQuery('')
    // Reload document to clear highlights
    if (containerRef.current) {
      loadDOCX()
    }
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

  if (!docxUrl) {
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
            ref={containerRef}
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

