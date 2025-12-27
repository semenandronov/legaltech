import Modal from "@/components/UI/Modal"
import { TabularCell, CellDetails } from "@/services/tabularReviewApi"
import {
  Box,
  Typography,
  Chip,
  LinearProgress,
  Stack,
  Divider,
} from '@mui/material'
import {
  Description as FileTextIcon,
  ErrorOutline as AlertCircleIcon,
  CheckCircleOutline as CheckCircleIcon,
} from '@mui/icons-material'

interface CellExpansionModalProps {
  isOpen: boolean
  onClose: () => void
  cell: TabularCell
  cellDetails: CellDetails | null
  fileName: string
  columnLabel: string
  loading: boolean
}

export function CellExpansionModal({
  isOpen,
  onClose,
  cell,
  cellDetails,
  fileName,
  columnLabel,
  loading,
}: CellExpansionModalProps) {
  const details = cellDetails || {
    id: "",
    cell_value: cell.cell_value,
    verbatim_extract: cell.verbatim_extract,
    reasoning: cell.reasoning,
    confidence_score: cell.confidence_score,
    source_page: cell.source_page,
    source_section: cell.source_section,
    status: cell.status,
  }

  const confidencePercentage = details.confidence_score !== null && details.confidence_score !== undefined
    ? Math.round(details.confidence_score * 100)
    : 0

  const confidenceColor = details.confidence_score !== null && details.confidence_score !== undefined
    ? details.confidence_score >= 0.9
      ? 'success'
      : details.confidence_score >= 0.7
      ? 'warning'
      : 'error'
    : 'primary'

  const statusColor = details.status === "completed" || details.status === "reviewed"
    ? 'success'
    : details.status === "processing"
    ? 'warning'
    : 'primary'

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={columnLabel} size="lg">
      <Stack spacing={3}>
        {/* Source Document */}
        <Box>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <FileTextIcon fontSize="small" color="action" />
            <Typography variant="caption" fontWeight={500} color="text.secondary">
              Источник
            </Typography>
          </Stack>
          <Typography variant="body2">{fileName}</Typography>
          {details.source_page && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              Страница: {details.source_page}
              {details.source_section && `, Раздел: ${details.source_section}`}
            </Typography>
          )}
        </Box>

        <Divider />

        {/* Answer */}
        <Box>
          <Typography variant="subtitle2" fontWeight={500} sx={{ mb: 1 }}>
            Ответ
          </Typography>
          <Box
            sx={{
              bgcolor: 'action.hover',
              borderRadius: 1,
              p: 2,
            }}
          >
            <Typography variant="body2">{details.cell_value || "N/A"}</Typography>
          </Box>
        </Box>

        {/* Verbatim Extract */}
        {details.verbatim_extract && (
          <Box>
            <Typography variant="subtitle2" fontWeight={500} sx={{ mb: 1 }}>
              Точная цитата (Verbatim)
            </Typography>
            <Box
              sx={{
                bgcolor: (theme) => theme.palette.mode === 'dark' 
                  ? 'rgba(33, 150, 243, 0.1)'
                  : 'rgba(33, 150, 243, 0.05)',
                borderRadius: 1,
                p: 2,
                border: 1,
                borderColor: (theme) => theme.palette.mode === 'dark'
                  ? 'rgba(33, 150, 243, 0.3)'
                  : 'rgba(33, 150, 243, 0.2)',
              }}
            >
              <Typography
                variant="body2"
                component="pre"
                sx={{
                  fontFamily: 'monospace',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  m: 0,
                }}
              >
                {details.verbatim_extract}
              </Typography>
            </Box>
          </Box>
        )}

        {/* Reasoning */}
        {details.reasoning && (
          <Box>
            <Typography variant="subtitle2" fontWeight={500} sx={{ mb: 1 }}>
              Объяснение (Reasoning)
            </Typography>
            <Box
              sx={{
                bgcolor: 'action.hover',
                borderRadius: 1,
                p: 2,
              }}
            >
              <Typography variant="body2" color="text.secondary">
                {details.reasoning}
              </Typography>
            </Box>
          </Box>
        )}

        {/* Confidence Score */}
        {details.confidence_score !== null && details.confidence_score !== undefined && (
          <Box>
            <Typography variant="subtitle2" fontWeight={500} sx={{ mb: 1 }}>
              Уверенность (Confidence)
            </Typography>
            <Stack direction="row" spacing={2} alignItems="center">
              <Box sx={{ flexGrow: 1 }}>
                <LinearProgress
                  variant="determinate"
                  value={confidencePercentage}
                  color={confidenceColor}
                  sx={{
                    height: 8,
                    borderRadius: 4,
                    bgcolor: 'action.hover',
                  }}
                />
              </Box>
              <Typography variant="body2" fontWeight={500}>
                {confidencePercentage}%
              </Typography>
              {details.confidence_score >= 0.9 ? (
                <Chip
                  icon={<CheckCircleIcon />}
                  label="Высокая"
                  color="success"
                  size="small"
                />
              ) : details.confidence_score >= 0.7 ? (
                <Chip
                  label="Средняя"
                  color="warning"
                  size="small"
                />
              ) : (
                <Chip
                  icon={<AlertCircleIcon />}
                  label="Низкая"
                  color="error"
                  size="small"
                />
              )}
            </Stack>
          </Box>
        )}

        {/* Status */}
        <Box>
          <Typography variant="subtitle2" fontWeight={500} sx={{ mb: 1 }}>
            Статус
          </Typography>
          <Chip
            label={
              details.status === "completed" || details.status === "reviewed"
                ? "Завершено"
                : details.status === "processing"
                ? "Обработка"
                : "Ожидание"
            }
            color={statusColor}
            size="small"
          />
        </Box>

        {loading && (
          <Box sx={{ textAlign: 'center', py: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Загрузка деталей...
            </Typography>
          </Box>
        )}
      </Stack>
    </Modal>
  )
}
