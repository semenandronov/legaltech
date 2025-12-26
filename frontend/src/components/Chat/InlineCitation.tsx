import React, { useState } from 'react'
import { Chip, Tooltip, Box, Typography, Stack } from '@mui/material'
import { FileText as FileTextIcon, OpenInNew as ExternalLinkIcon } from '@mui/icons-material'
import { SourceInfo } from '../../services/api'
import './Chat.css'

interface InlineCitationProps {
  index: number
  sources: SourceInfo[]
  onClick?: (source: SourceInfo) => void
}

const InlineCitation: React.FC<InlineCitationProps> = ({
  index,
  sources,
  onClick
}) => {
  const source = sources[index - 1] // Citations are 1-indexed

  if (!source) {
    return (
      <Chip
        label={`[${index}]`}
        size="small"
        variant="outlined"
        sx={{ opacity: 0.6 }}
      />
    )
  }

  // Format short document name
  const formatShortName = (filename: string): string => {
    let name = filename.replace(/\.[^/.]+$/, '') // Remove extension
    // Take meaningful part - last segment if it contains date/type
    const parts = name.split(/[_\-]/)
    if (parts.length > 2) {
      // Try to get date and type (e.g., "20170619_Opredelenie")
      const dateMatch = parts.find(p => /^\d{8}$/.test(p))
      const typeMatch = parts.find(p => p.length > 5 && !/^\d+$/.test(p))
      if (dateMatch && typeMatch) {
        return `${typeMatch.substring(0, 12)}`
      }
    }
    return name.substring(0, 15)
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (onClick) {
      onClick(source)
    }
  }

  const shortName = formatShortName(source.file)
  const pageInfo = source.page ? ` стр.${source.page}` : ''

  return (
    <Tooltip
      title={
        <Box>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <FileTextIcon fontSize="small" />
            <Typography variant="body2" fontWeight={600}>
              {source.file}
            </Typography>
          </Stack>
          {source.page && (
            <Typography variant="caption" color="primary.main" sx={{ display: 'block', mb: 0.5 }}>
              Страница {source.page}
            </Typography>
          )}
          {source.similarity_score !== undefined && (
            <Typography variant="caption" color="success.main" sx={{ display: 'block', mb: 1 }}>
              Релевантность: {Math.round(source.similarity_score * 100)}%
            </Typography>
          )}
          {source.text_preview && (
            <Typography
              variant="caption"
              sx={{
                display: 'block',
                mb: 1,
                p: 1,
                bgcolor: 'rgba(0, 0, 0, 0.2)',
                borderRadius: 1,
                maxHeight: '100px',
                overflow: 'auto',
              }}
            >
              {source.text_preview.length > 200
                ? source.text_preview.substring(0, 200) + '...'
                : source.text_preview}
            </Typography>
          )}
          <Typography variant="caption" color="primary.main" sx={{ display: 'block', textAlign: 'center' }}>
            Нажмите, чтобы открыть документ →
          </Typography>
        </Box>
      }
      arrow
      placement="top"
    >
      <Chip
        icon={<FileTextIcon />}
        label={`${shortName}${pageInfo}`}
        size="small"
        onClick={handleClick}
        onDelete={() => {}}
        deleteIcon={<ExternalLinkIcon fontSize="small" />}
        sx={{
          cursor: 'pointer',
          '&:hover': {
            bgcolor: 'action.hover',
          },
        }}
        aria-label={`Открыть документ: ${source.file}`}
      />
    </Tooltip>
  )
}

export default InlineCitation
