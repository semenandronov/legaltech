"use client"

import React, { useState, useEffect } from "react"
import {
  Box,
  Typography,
  Stack,
  Chip,
  Button,
  List,
  ListItem,
  ListItemText,
  IconButton,
  Divider,
  CircularProgress,
} from "@mui/material"
import {
  Close as CloseIcon,
  Refresh as RefreshIcon,
  CheckCircle as CheckCircleIcon,
  Warning as WarningIcon,
} from "@mui/icons-material"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { toast } from "sonner"

interface ReviewQueueItem {
  id: string
  file_id: string
  column_id: string
  cell_id: string
  priority: number
  reason: string
  is_reviewed: boolean
  reviewed_by?: string | null
  reviewed_at?: string | null
  created_at: string
}

interface ReviewQueueStats {
  total_items: number
  by_reason: Record<string, number>
  by_priority: Record<number, number>
  high_priority_count: number
}

interface ReviewQueuePanelProps {
  reviewId: string
  open: boolean
  onClose: () => void
  onItemClick?: (fileId: string, columnId: string) => void
}

export const ReviewQueuePanel: React.FC<ReviewQueuePanelProps> = ({
  reviewId,
  open,
  onClose,
  onItemClick,
}) => {
  const [items, setItems] = useState<ReviewQueueItem[]>([])
  const [stats, setStats] = useState<ReviewQueueStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)

  const loadQueue = async () => {
    if (!reviewId) return
    
    setLoading(true)
    try {
      const data = await tabularReviewApi.getReviewQueue(reviewId, false)
      setItems(data.items)
      setStats(data.stats)
    } catch (error: any) {
      toast.error("Ошибка загрузки очереди: " + (error.message || ""))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && reviewId) {
      loadQueue()
    }
  }, [open, reviewId])

  const handleRebuild = async () => {
    setRebuilding(true)
    try {
      await tabularReviewApi.rebuildReviewQueue(reviewId)
      toast.success("Очередь обновлена")
      await loadQueue()
    } catch (error: any) {
      toast.error("Ошибка обновления очереди: " + (error.message || ""))
    } finally {
      setRebuilding(false)
    }
  }

  const handleMarkReviewed = async (itemId: string) => {
    try {
      await tabularReviewApi.markQueueItemReviewed(reviewId, itemId)
      toast.success("Элемент отмечен как проверенный")
      await loadQueue()
    } catch (error: any) {
      toast.error("Ошибка: " + (error.message || ""))
    }
  }

  const getPriorityColor = (priority: number) => {
    if (priority === 1) return "error"
    if (priority === 2) return "warning"
    return "default"
  }

  const getReasonLabel = (reason: string) => {
    const labels: Record<string, string> = {
      conflict: "Конфликт",
      low_confidence: "Низкая уверенность",
      critical_column: "Критичная колонка",
      always_review_type: "Обязательная проверка",
      empty_or_na: "Пустое/N/A",
      pending: "Ожидает обработки",
    }
    return reason.split(", ").map(r => labels[r] || r).join(", ")
  }

  if (!open) return null

  return (
    <Box
      sx={{
        width: 400,
        borderLeft: 1,
        borderColor: "divider",
        bgcolor: "background.paper",
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
    >
      {/* Header */}
      <Box
        sx={{
          p: 2,
          borderBottom: 1,
          borderColor: "divider",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Stack direction="row" spacing={1} alignItems="center">
          <WarningIcon color="warning" />
          <Typography variant="h6">Review Queue</Typography>
          {stats && (
            <Chip
              label={stats.total_items}
              size="small"
              color={stats.total_items > 0 ? "warning" : "success"}
            />
          )}
        </Stack>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Stats */}
      {stats && (
        <Box sx={{ p: 2, borderBottom: 1, borderColor: "divider", bgcolor: "action.hover" }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
            Всего элементов: {stats.total_items}
          </Typography>
          {stats.high_priority_count > 0 && (
            <Chip
              label={`Высокий приоритет: ${stats.high_priority_count}`}
              size="small"
              color="error"
              sx={{ mr: 1 }}
            />
          )}
        </Box>
      )}

      {/* Actions */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: "divider" }}>
        <Stack direction="row" spacing={1}>
          <Button
            size="small"
            variant="outlined"
            startIcon={rebuilding ? <CircularProgress size={16} /> : <RefreshIcon />}
            onClick={handleRebuild}
            disabled={rebuilding}
            sx={{ textTransform: "none" }}
          >
            Обновить
          </Button>
        </Stack>
      </Box>

      {/* Queue Items */}
      <Box sx={{ flex: 1, overflow: "auto" }}>
        {loading ? (
          <Box sx={{ display: "flex", justifyContent: "center", p: 4 }}>
            <CircularProgress size={24} />
          </Box>
        ) : items.length === 0 ? (
          <Box sx={{ p: 4, textAlign: "center" }}>
            <CheckCircleIcon sx={{ fontSize: 48, color: "success.main", mb: 2 }} />
            <Typography variant="body2" color="text.secondary">
              Очередь пуста. Все элементы проверены!
            </Typography>
          </Box>
        ) : (
          <List>
            {items.map((item, idx) => (
              <React.Fragment key={item.id}>
                <ListItem
                  sx={{
                    bgcolor: item.is_reviewed ? "action.hover" : "background.paper",
                    cursor: "pointer",
                    "&:hover": {
                      bgcolor: "action.hover",
                    },
                  }}
                  onClick={() => {
                    if (!item.is_reviewed && onItemClick) {
                      onItemClick(item.file_id, item.column_id)
                    }
                  }}
                  secondaryAction={
                    !item.is_reviewed ? (
                      <IconButton
                        edge="end"
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleMarkReviewed(item.id)
                        }}
                      >
                        <CheckCircleIcon fontSize="small" color="success" />
                      </IconButton>
                    ) : null
                  }
                >
                  <ListItemText
                    primary={
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Chip
                          label={`P${item.priority}`}
                          size="small"
                          color={getPriorityColor(item.priority)}
                        />
                        <Typography variant="body2" fontWeight={item.is_reviewed ? 400 : 600}>
                          {getReasonLabel(item.reason)}
                        </Typography>
                      </Stack>
                    }
                    secondary={
                      <Typography variant="caption" color="text.secondary">
                        File: {item.file_id.slice(0, 8)}... | Column: {item.column_id.slice(0, 8)}...
                      </Typography>
                    }
                  />
                </ListItem>
                {idx < items.length - 1 && <Divider />}
              </React.Fragment>
            ))}
          </List>
        )}
      </Box>
    </Box>
  )
}

