import React, { useState, useEffect, useMemo } from 'react'
import {
  Box,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Checkbox,
  Chip,
  Typography,
  Stack,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Button,
  Paper,
} from '@mui/material'
import { DocumentItem, DocumentClassification, PrivilegeCheck } from '../../services/api'
import StatusIcon, { DocumentStatus } from '../Common/StatusIcon'
import ConfidenceBadge from '../Common/ConfidenceBadge'
import BatchActions from './BatchActions'

export interface DocumentWithMetadata extends DocumentItem {
  classification?: DocumentClassification
  privilegeCheck?: PrivilegeCheck
  confidence?: number
  status?: 'reviewed' | 'privileged' | 'rejected' | 'processing' | 'flagged' | 'bookmarked'
}

interface DocumentsListProps {
  documents: DocumentWithMetadata[]
  selectedDocuments: Set<string>
  onSelectDocument: (fileId: string, selected: boolean) => void
  onDocumentClick: (fileId: string) => void
  onBatchAction?: (action: string, fileIds: string[]) => void
  sortBy?: 'date' | 'name' | 'relevance'
  onSortChange?: (sortBy: 'date' | 'name' | 'relevance') => void
  loadMore?: () => void
  hasMore?: boolean
}

const DocumentsList: React.FC<DocumentsListProps> = React.memo(({
  documents,
  selectedDocuments,
  onSelectDocument,
  onDocumentClick,
  onBatchAction,
  sortBy = 'date',
  onSortChange,
  loadMore,
  hasMore = false
}) => {
  const [visibleRange, setVisibleRange] = useState(50)

  const getDocumentStatus = (doc: DocumentWithMetadata): DocumentStatus | undefined => {
    if (doc.privilegeCheck?.is_privileged || doc.classification?.is_privileged) {
      return 'privileged'
    }
    return doc.status as DocumentStatus | undefined
  }

  const visibleDocuments = useMemo(() => {
    return documents.slice(0, visibleRange)
  }, [documents, visibleRange])

  const selectedCount = selectedDocuments.size

  useEffect(() => {
    if (hasMore && visibleRange >= documents.length && loadMore) {
      loadMore()
    }
  }, [visibleRange, documents.length, hasMore, loadMore])

  return (
    <Box>
      {/* Header */}
      <Paper sx={{ p: 2, mb: 1 }}>
        <Stack direction="row" spacing={2} alignItems="center" justifyContent="space-between">
          <Typography variant="body2" color="text.secondary">
            {documents.length} matching filters
          </Typography>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>🎯 SORT</InputLabel>
            <Select
              value={sortBy}
              label="🎯 SORT"
              onChange={(e) => onSortChange?.(e.target.value as 'date' | 'name' | 'relevance')}
            >
              <MenuItem value="date">Date</MenuItem>
              <MenuItem value="name">A-Z</MenuItem>
              <MenuItem value="relevance">Rel%</MenuItem>
            </Select>
          </FormControl>
        </Stack>
      </Paper>

      {/* List */}
      <List sx={{ bgcolor: 'background.paper', borderRadius: 1, overflow: 'hidden' }}>
        {visibleDocuments.map((doc) => {
          const isSelected = selectedDocuments.has(doc.id)
          const confidence = doc.confidence || doc.classification?.confidence || 0
          const relevanceScore = doc.classification?.relevance_score || 0

          return (
            <ListItem
              key={doc.id}
              disablePadding
              secondaryAction={
                relevanceScore > 0 && (
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mr: 1 }}>
                    <Typography variant="caption" color="text.secondary">
                      {relevanceScore}%
                    </Typography>
                    <ConfidenceBadge confidence={confidence} showIcon={false} size="small" />
                  </Stack>
                )
              }
            >
              <ListItemButton
                selected={isSelected}
                onClick={() => onDocumentClick(doc.id)}
                sx={{
                  '&.Mui-selected': {
                    bgcolor: 'primary.light',
                    '&:hover': {
                      bgcolor: 'primary.light',
                    },
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 40 }}>
                  <Checkbox
                    edge="start"
                    checked={isSelected}
                    tabIndex={-1}
                    disableRipple
                    onClick={(e) => {
                      e.stopPropagation()
                      onSelectDocument(doc.id, !isSelected)
                    }}
                  />
                </ListItemIcon>
                <ListItemIcon sx={{ minWidth: 36 }}>
                  <StatusIcon status={getDocumentStatus(doc) || 'confirmed'} size="small" />
                </ListItemIcon>
                <ListItemText
                  primary={doc.filename}
                  secondary={
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
                      {doc.classification?.doc_type && (
                        <Chip label={doc.classification.doc_type} size="small" variant="outlined" />
                      )}
                      {doc.created_at && (
                        <Typography variant="caption" color="text.secondary">
                          {new Date(doc.created_at).toLocaleDateString('ru-RU')}
                        </Typography>
                      )}
                    </Stack>
                  }
                />
              </ListItemButton>
            </ListItem>
          )
        })}
      </List>

      {/* Load More */}
      {documents.length > visibleRange && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
          <Button
            variant="outlined"
            onClick={() => setVisibleRange(prev => prev + 50)}
          >
            ─── LOAD MORE (50) ───
          </Button>
        </Box>
      )}

      {/* Empty State */}
      {documents.length === 0 && (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            Нет документов, соответствующих фильтрам
          </Typography>
        </Paper>
      )}

      {/* Batch Actions */}
      <BatchActions
        selectedCount={selectedCount}
        onConfirmAll={() => onBatchAction?.('confirm', Array.from(selectedDocuments))}
        onRejectAll={() => onBatchAction?.('reject', Array.from(selectedDocuments))}
        onWithholdAll={() => onBatchAction?.('withhold', Array.from(selectedDocuments))}
        onAutoReview={() => onBatchAction?.('auto-review', Array.from(selectedDocuments))}
        onExportSelected={() => onBatchAction?.('export', Array.from(selectedDocuments))}
      />
    </Box>
  )
})

DocumentsList.displayName = 'DocumentsList'

export default DocumentsList
