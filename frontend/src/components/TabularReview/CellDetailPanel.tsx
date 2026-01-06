"use client"

import React from "react"
import {
  Box,
  Typography,
  IconButton,
  Stack,
  Chip,
  Button,
  Paper,
} from "@mui/material"
import {
  Close as CloseIcon,
  Edit as EditIcon,
  Refresh as RefreshIcon,
  Link as LinkIcon,
  Warning as WarningIcon,
} from "@mui/icons-material"
import { CellDetails, SourceReference } from "@/services/tabularReviewApi"

interface CellDetailPanelProps {
  fileName: string
  columnLabel: string
  cellDetails: CellDetails | null
  onClose: () => void
  onEdit?: () => void
  onRefresh?: () => void
  onJumpToSource?: (reference: SourceReference) => void
  onResolveConflict?: () => void
}

export const CellDetailPanel: React.FC<CellDetailPanelProps> = ({
  fileName,
  columnLabel,
  cellDetails,
  onClose,
  onEdit,
  onRefresh,
  onJumpToSource,
  onResolveConflict,
}) => {
  if (!cellDetails) {
    return (
      <Box
        sx={{
          width: 400,
          borderLeft: 1,
          borderColor: "divider",
          bgcolor: "background.paper",
          p: 2,
        }}
      >
        <Typography variant="body2" color="text.secondary">
          Выберите ячейку для просмотра деталей
        </Typography>
      </Box>
    )
  }

  const confidencePercentage =
    cellDetails.confidence_score !== null && cellDetails.confidence_score !== undefined
      ? Math.round(cellDetails.confidence_score * 100)
      : 0

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
        overflow: "auto",
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
        <Typography variant="h6" noWrap sx={{ flex: 1, mr: 1 }}>
          {fileName}
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Jump to dropdown */}
      <Box sx={{ px: 2, py: 1, borderBottom: 1, borderColor: "divider" }}>
        <Button
          size="small"
          variant="outlined"
          startIcon={<LinkIcon />}
          fullWidth
          sx={{ textTransform: "none" }}
        >
          Jump to...
        </Button>
      </Box>

      {/* Content */}
      <Box sx={{ flex: 1, overflow: "auto", p: 2 }}>
        <Stack spacing={3}>
          {/* Column Name Section */}
          <Box>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="subtitle2" fontWeight={600}>
                {columnLabel}
              </Typography>
            </Stack>
          </Box>

          {/* Answer Section */}
          <Box>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Typography variant="subtitle2" fontWeight={500}>
                Answer
              </Typography>
              {onEdit && (
                <IconButton size="small" onClick={onEdit} sx={{ ml: "auto" }}>
                  <EditIcon fontSize="small" />
                </IconButton>
              )}
              {onRefresh && (
                <IconButton size="small" onClick={onRefresh}>
                  <RefreshIcon fontSize="small" />
                </IconButton>
              )}
            </Stack>
            <Paper
              elevation={0}
              sx={{
                bgcolor: "action.hover",
                p: 1.5,
                borderRadius: 1,
              }}
            >
              <Typography variant="body2">{cellDetails.cell_value || "N/A"}</Typography>
            </Paper>
          </Box>

          {/* Reasoning Section */}
          {cellDetails.reasoning && (
            <Box>
              <Typography variant="subtitle2" fontWeight={500} sx={{ mb: 1 }}>
                Reasoning
              </Typography>
              <Paper
                elevation={0}
                sx={{
                  bgcolor: "action.hover",
                  p: 1.5,
                  borderRadius: 1,
                }}
              >
                <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: "pre-wrap" }}>
                  {cellDetails.reasoning}
                </Typography>
              </Paper>

              {/* Source References */}
              {cellDetails.source_references && cellDetails.source_references.length > 0 && (
                <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: "wrap" }}>
                  {cellDetails.source_references.map((ref, idx) => (
                    <Chip
                      key={idx}
                      label={`[${idx + 1}]`}
                      size="small"
                      onClick={() => onJumpToSource?.(ref)}
                      sx={{ cursor: "pointer" }}
                    />
                  ))}
                </Stack>
              )}
            </Box>
          )}

          {/* Source References Section (if no reasoning but has references) */}
          {!cellDetails.reasoning && cellDetails.source_references && cellDetails.source_references.length > 0 && (
            <Box>
              <Typography variant="subtitle2" fontWeight={500} sx={{ mb: 1 }}>
                Source References
              </Typography>
              <Stack spacing={1}>
                {cellDetails.source_references.map((ref, idx) => (
                  <Paper
                    key={idx}
                    elevation={0}
                    sx={{
                      bgcolor: "action.hover",
                      p: 1.5,
                      borderRadius: 1,
                      cursor: onJumpToSource ? "pointer" : "default",
                      "&:hover": onJumpToSource
                        ? {
                            bgcolor: "action.selected",
                          }
                        : {},
                    }}
                    onClick={() => onJumpToSource?.(ref)}
                  >
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                      <Chip label={`[${idx + 1}]`} size="small" />
                      {ref.page && (
                        <Typography variant="caption" color="text.secondary">
                          Page {ref.page}
                        </Typography>
                      )}
                      {ref.section && (
                        <Typography variant="caption" color="text.secondary">
                          {ref.section}
                        </Typography>
                      )}
                    </Stack>
                    <Typography variant="body2" color="text.secondary">
                      {ref.text}
                    </Typography>
                  </Paper>
                ))}
              </Stack>
            </Box>
          )}

          {/* Conflict Section */}
          {cellDetails.status === 'conflict' && cellDetails.candidates && cellDetails.candidates.length > 1 && (
            <Box>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <WarningIcon color="warning" fontSize="small" />
                <Typography variant="subtitle2" fontWeight={500} color="warning.main">
                  Conflict Detected
                </Typography>
              </Stack>
              <Paper
                elevation={0}
                sx={{
                  bgcolor: "warning.light",
                  p: 1.5,
                  borderRadius: 1,
                  mb: 1,
                }}
              >
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  Multiple different values were found for this cell. Please review and select the correct one.
                </Typography>
                {onResolveConflict && (
                  <Button
                    variant="contained"
                    color="warning"
                    size="small"
                    onClick={onResolveConflict}
                    sx={{ textTransform: "none" }}
                  >
                    Resolve Conflict
                  </Button>
                )}
              </Paper>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
                Found {cellDetails.candidates.length} candidate values:
              </Typography>
              <Stack spacing={1}>
                {cellDetails.candidates.map((candidate, idx) => (
                  <Paper
                    key={idx}
                    elevation={0}
                    sx={{
                      bgcolor: "action.hover",
                      p: 1.5,
                      borderRadius: 1,
                      border: idx === 0 ? 2 : 1,
                      borderColor: idx === 0 ? "primary.main" : "divider",
                    }}
                  >
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                      <Chip
                        label={`Candidate ${idx + 1}`}
                        size="small"
                        color={idx === 0 ? "primary" : "default"}
                      />
                      <Chip
                        label={`${Math.round(candidate.confidence * 100)}%`}
                        size="small"
                        color={
                          candidate.confidence >= 0.9
                            ? "success"
                            : candidate.confidence >= 0.7
                            ? "warning"
                            : "error"
                        }
                      />
                    </Stack>
                    <Typography variant="body2" fontWeight={idx === 0 ? 600 : 400}>
                      {candidate.value}
                    </Typography>
                    {candidate.verbatim && (
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
                        "{candidate.verbatim}"
                      </Typography>
                    )}
                    {candidate.source_page && (
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
                        Page {candidate.source_page}
                      </Typography>
                    )}
                  </Paper>
                ))}
              </Stack>
            </Box>
          )}

          {/* Confidence Score */}
          {cellDetails.confidence_score !== null && cellDetails.confidence_score !== undefined && (
            <Box>
              <Typography variant="subtitle2" fontWeight={500} sx={{ mb: 1 }}>
                Confidence
              </Typography>
              <Chip
                label={`${confidencePercentage}%`}
                color={
                  cellDetails.confidence_score >= 0.9
                    ? "success"
                    : cellDetails.confidence_score >= 0.7
                    ? "warning"
                    : "error"
                }
                size="small"
              />
            </Box>
          )}
        </Stack>
      </Box>
    </Box>
  )
}



