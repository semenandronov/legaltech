"use client"

import React, { useState, useEffect } from "react"
import {
  Box,
  Typography,
  List,
  ListItem,
  ListItemText,
  Button,
  Chip,
  Stack,
  Divider,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Paper,
  IconButton,
  Tooltip,
} from "@mui/material"
import {
  History as HistoryIcon,
  Restore as RestoreIcon,
  CompareArrows as CompareIcon,
  Close as CloseIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
} from "@mui/icons-material"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { formatDistanceToNow } from "date-fns"
import { ru } from "date-fns/locale"

interface CellHistoryRecord {
  id: string
  cell_value: string | null
  verbatim_extract: string | null
  reasoning: string | null
  source_references: any
  confidence_score: number | null
  source_page: number | null
  source_section: string | null
  status: string
  changed_by: string | null
  change_type: string
  previous_cell_value: string | null
  change_reason: string | null
  created_at: string
}

interface CellHistoryPanelProps {
  reviewId: string
  fileId: string
  columnId: string
  columnLabel: string
  open: boolean
  onClose: () => void
  onRevert?: () => void
}

export const CellHistoryPanel: React.FC<CellHistoryPanelProps> = ({
  reviewId,
  fileId,
  columnId,
  columnLabel,
  open,
  onClose,
  onRevert,
}) => {
  const [history, setHistory] = useState<CellHistoryRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [showRevertDialog, setShowRevertDialog] = useState(false)
  const [revertHistoryId, setRevertHistoryId] = useState<string | null>(null)
  const [revertReason, setRevertReason] = useState("")
  const [reverting, setReverting] = useState(false)

  useEffect(() => {
    if (open) {
      loadHistory()
    }
  }, [open, reviewId, fileId, columnId])

  const loadHistory = async () => {
    setLoading(true)
    try {
      const data = await tabularReviewApi.getCellHistory(reviewId, fileId, columnId, 50)
      setHistory(data)
    } catch (error) {
      console.error("Error loading cell history:", error)
    } finally {
      setLoading(false)
    }
  }

  const handleRevert = async (historyId: string) => {
    setRevertHistoryId(historyId)
    setShowRevertDialog(true)
  }

  const confirmRevert = async () => {
    if (!revertHistoryId) return

    setReverting(true)
    try {
      await tabularReviewApi.revertCell(
        reviewId,
        fileId,
        columnId,
        revertHistoryId,
        revertReason || undefined
      )
      setShowRevertDialog(false)
      setRevertHistoryId(null)
      setRevertReason("")
      loadHistory()
      if (onRevert) {
        onRevert()
      }
    } catch (error) {
      console.error("Error reverting cell:", error)
      alert("Ошибка при откате версии")
    } finally {
      setReverting(false)
    }
  }

  const getChangeTypeColor = (changeType: string): "default" | "primary" | "success" | "warning" | "error" => {
    switch (changeType) {
      case "created":
        return "success"
      case "updated":
        return "primary"
      case "reverted":
        return "warning"
      case "deleted":
        return "error"
      default:
        return "default"
    }
  }

  const getChangeTypeLabel = (changeType: string): string => {
    switch (changeType) {
      case "created":
        return "Создано"
      case "updated":
        return "Обновлено"
      case "reverted":
        return "Откат"
      case "deleted":
        return "Удалено"
      default:
        return changeType
    }
  }


  return (
    <>
      <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
        <DialogTitle>
          <Stack direction="row" spacing={2} alignItems="center">
            <HistoryIcon />
            <Box>
              <Typography variant="h6">История изменений</Typography>
              <Typography variant="body2" color="text.secondary">
                {columnLabel}
              </Typography>
            </Box>
            <Box sx={{ ml: "auto" }}>
              <IconButton onClick={onClose} size="small">
                <CloseIcon />
              </IconButton>
            </Box>
          </Stack>
        </DialogTitle>
        <DialogContent>
          {loading ? (
            <Typography>Загрузка...</Typography>
          ) : history.length === 0 ? (
            <Typography color="text.secondary">История изменений пуста</Typography>
          ) : (
            <List>
              {history.map((record, index) => (
                <React.Fragment key={record.id}>
                  <ListItem
                    sx={{
                      flexDirection: "column",
                      alignItems: "stretch",
                      bgcolor: index === 0 ? "action.hover" : "transparent",
                    }}
                  >
                    <Stack direction="row" spacing={2} alignItems="center" sx={{ width: "100%" }}>
                      <Chip
                        label={getChangeTypeLabel(record.change_type)}
                        color={getChangeTypeColor(record.change_type)}
                        size="small"
                      />
                      <Typography variant="body2" sx={{ flex: 1 }}>
                        {formatDate(record.created_at)}
                      </Typography>
                      {index === 0 && (
                        <Chip label="Текущая версия" color="success" size="small" />
                      )}
                      {index !== 0 && (
                        <Button
                          size="small"
                          startIcon={<RestoreIcon />}
                          onClick={() => handleRevert(record.id)}
                          variant="outlined"
                        >
                          Откатить
                        </Button>
                      )}
                      <IconButton
                        size="small"
                        onClick={() => setExpandedId(expandedId === record.id ? null : record.id)}
                      >
                        {expandedId === record.id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                      </IconButton>
                    </Stack>

                    <Box sx={{ mt: 1, width: "100%" }}>
                      <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                        Значение:
                      </Typography>
                      <Paper sx={{ p: 1, bgcolor: "background.default" }}>
                        <Typography variant="body2">
                          {record.cell_value || <em style={{ color: "#999" }}>Пусто</em>}
                        </Typography>
                      </Paper>
                    </Box>

                    {expandedId === record.id && (
                      <Box sx={{ mt: 2, width: "100%" }}>
                        {record.previous_cell_value && (
                          <Box sx={{ mb: 2 }}>
                            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                              Предыдущее значение:
                            </Typography>
                            <Paper sx={{ p: 1, bgcolor: "background.default" }}>
                              <Typography variant="body2" sx={{ color: "error.main" }}>
                                {record.previous_cell_value}
                              </Typography>
                            </Paper>
                          </Box>
                        )}

                        {record.reasoning && (
                          <Box sx={{ mb: 2 }}>
                            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                              Обоснование:
                            </Typography>
                            <Paper sx={{ p: 1, bgcolor: "background.default" }}>
                              <Typography variant="body2">{record.reasoning}</Typography>
                            </Paper>
                          </Box>
                        )}

                        {record.confidence_score !== null && (
                          <Box sx={{ mb: 2 }}>
                            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                              Уверенность: {Math.round(record.confidence_score * 100)}%
                            </Typography>
                          </Box>
                        )}

                        {record.source_page && (
                          <Typography variant="body2" color="text.secondary">
                            Страница: {record.source_page}
                            {record.source_section && `, Раздел: ${record.source_section}`}
                          </Typography>
                        )}

                        {record.change_reason && (
                          <Box sx={{ mt: 1 }}>
                            <Typography variant="body2" color="text.secondary">
                              Причина изменения: {record.change_reason}
                            </Typography>
                          </Box>
                        )}

                        {record.changed_by && (
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                            Изменил: {record.changed_by}
                          </Typography>
                        )}
                      </Box>
                    )}
                  </ListItem>
                  {index < history.length - 1 && <Divider />}
                </React.Fragment>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Закрыть</Button>
        </DialogActions>
      </Dialog>

      {/* Revert Confirmation Dialog */}
      <Dialog open={showRevertDialog} onClose={() => setShowRevertDialog(false)}>
        <DialogTitle>Откатить к этой версии?</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            multiline
            rows={3}
            label="Причина отката (необязательно)"
            value={revertReason}
            onChange={(e) => setRevertReason(e.target.value)}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowRevertDialog(false)} disabled={reverting}>
            Отмена
          </Button>
          <Button onClick={confirmRevert} variant="contained" disabled={reverting}>
            {reverting ? "Откат..." : "Откатить"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

