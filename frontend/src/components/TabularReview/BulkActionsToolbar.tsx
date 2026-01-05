"use client"

import React from "react"
import {
  Box,
  Button,
  Stack,
  Typography,
  Divider,
} from "@mui/material"
import {
  CheckCircle as CheckCircleIcon,
  Delete as DeleteIcon,
  PlayArrow as PlayArrowIcon,
} from "@mui/icons-material"

interface BulkActionsToolbarProps {
  selectedCount: number
  onMarkAsReviewed?: () => void
  onReRunExtraction?: () => void
  onDelete?: () => void
  onClearSelection?: () => void
}

export const BulkActionsToolbar: React.FC<BulkActionsToolbarProps> = ({
  selectedCount,
  onMarkAsReviewed,
  onReRunExtraction,
  onDelete,
  onClearSelection,
}) => {
  if (selectedCount === 0) {
    return null
  }

  return (
    <Box
      sx={{
        position: "sticky",
        top: 0,
        zIndex: 10,
        bgcolor: "background.paper",
        borderBottom: 1,
        borderColor: "divider",
        py: 1.5,
        px: 2,
      }}
    >
      <Stack direction="row" spacing={2} alignItems="center">
        <Typography variant="body2" sx={{ fontWeight: 600, color: "primary.main" }}>
          {selectedCount} {selectedCount === 1 ? "строка выбрана" : "строк выбрано"}
        </Typography>

        <Divider orientation="vertical" flexItem />

        <Button
          size="small"
          variant="outlined"
          startIcon={<CheckCircleIcon />}
          onClick={onMarkAsReviewed}
          disabled={!onMarkAsReviewed}
        >
          Отметить как проверено
        </Button>

        <Button
          size="small"
          variant="outlined"
          startIcon={<PlayArrowIcon />}
          onClick={onReRunExtraction}
          disabled={!onReRunExtraction}
        >
          Перезапустить извлечение
        </Button>

        <Button
          size="small"
          variant="outlined"
          color="error"
          startIcon={<DeleteIcon />}
          onClick={onDelete}
          disabled={!onDelete}
        >
          Удалить
        </Button>

        <Box sx={{ ml: "auto" }}>
          <Button
            size="small"
            variant="text"
            onClick={onClearSelection}
          >
            Снять выделение
          </Button>
        </Box>
      </Stack>
    </Box>
  )
}

