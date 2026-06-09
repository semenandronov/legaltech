"use client"

import React, { useState, useEffect } from "react"
import {
  Box,
  TextField,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  ToggleButton,
  ToggleButtonGroup,
  Stack,
} from "@mui/material"
import {
  Check as CheckIcon,
  Close as CloseIcon,
} from "@mui/icons-material"
import { TabularCell, TabularColumn } from "@/services/tabularReviewApi"

interface InlineCellEditorProps {
  cell: TabularCell
  column: TabularColumn
  onSave: (value: string) => Promise<void>
  onCancel: () => void
  initialValue?: string
}

function normalizeYesNoEditorValue(raw: string): string {
  const v = (raw || "").trim()
  if (!v) return ""
  if (v === "Yes" || v.toLowerCase() === "yes") return "Да"
  if (v === "No" || v.toLowerCase() === "no") return "Нет"
  if (v === "Unknown" || v.toUpperCase() === "N/A" || v === "Н/Д") return "N/A"
  return v
}

export const InlineCellEditor: React.FC<InlineCellEditorProps> = ({
  cell,
  column,
  onSave,
  onCancel,
  initialValue,
}) => {
  const rawInitial = initialValue ?? cell?.cell_value ?? ""
  const [value, setValue] = useState<string>(
    column.column_type === "yes_no" ? normalizeYesNoEditorValue(rawInitial) : rawInitial
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const next = initialValue ?? cell?.cell_value ?? ""
    setValue(column.column_type === "yes_no" ? normalizeYesNoEditorValue(next) : next)
  }, [cell, initialValue, column.column_type])

  const handleSave = async () => {
    if (saving) return

    setError(null)
    setSaving(true)

    try {
      await onSave(value)
    } catch (err: any) {
      setError(err.message || "Failed to save")
      setSaving(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSave()
    } else if (e.key === "Escape") {
      e.preventDefault()
      onCancel()
    }
  }

  const renderInput = () => {
    switch (column.column_type) {
      case "text":
      case "verbatim":
        return (
          <TextField
            multiline
            rows={3}
            fullWidth
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Введите ${column.column_label.toLowerCase()}…`}
            variant="outlined"
            size="small"
            autoFocus
            error={!!error}
            helperText={error}
          />
        )

      case "number":
        return (
          <TextField
            fullWidth
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Число без валюты (например: 1 000 или 12,5)"
            variant="outlined"
            size="small"
            autoFocus
            error={!!error}
            helperText={error}
          />
        )

      case "currency":
        return (
          <TextField
            fullWidth
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Сумма с валютой как в документе (например: 150 000 руб. или 1 000 USD)"
            variant="outlined"
            size="small"
            autoFocus
            error={!!error}
            helperText={error}
          />
        )

      case "date":
        return (
          <TextField
            type="date"
            fullWidth
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            variant="outlined"
            size="small"
            InputLabelProps={{ shrink: true }}
            autoFocus
            error={!!error}
            helperText={error}
          />
        )

      case "yes_no":
        return (
          <ToggleButtonGroup
            value={value}
            exclusive
            onChange={(_, newValue) => newValue !== null && setValue(newValue)}
            fullWidth
            size="small"
          >
            <ToggleButton value="Да">Да</ToggleButton>
            <ToggleButton value="Нет">Нет</ToggleButton>
            <ToggleButton value="N/A">N/A</ToggleButton>
          </ToggleButtonGroup>
        )

      case "tag": {
        const options = column.column_config?.options || []
        return (
          <FormControl fullWidth size="small">
            <InputLabel>{column.column_label}</InputLabel>
            <Select
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKeyDown}
              label={column.column_label}
              autoFocus
            >
              {options.map((option: { label: string; color?: string }) => (
                <MenuItem key={option.label} value={option.label}>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                    <Box
                      sx={{
                        width: 12,
                        height: 12,
                        borderRadius: "50%",
                        backgroundColor: option.color || "#3B82F6",
                      }}
                    />
                    {option.label}
                  </Box>
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )
      }

      default:
        return (
          <TextField
            fullWidth
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Введите ${column.column_label.toLowerCase()}…`}
            variant="outlined"
            size="small"
            autoFocus
            error={!!error}
            helperText={error}
          />
        )
    }
  }

  return (
    <Box
      sx={{
        p: 1,
        border: "1px solid",
        borderColor: "primary.main",
        borderRadius: 1,
        bgcolor: "background.paper",
        minWidth: 200,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <Stack spacing={1}>
        {renderInput()}

        <Stack direction="row" spacing={1} justifyContent="flex-end">
          <Button
            size="small"
            variant="outlined"
            onClick={onCancel}
            disabled={saving}
            startIcon={<CloseIcon />}
          >
            Отмена
          </Button>
          <Button
            size="small"
            variant="contained"
            onClick={handleSave}
            disabled={saving}
            startIcon={<CheckIcon />}
          >
            {saving ? "Сохранение…" : "Сохранить"}
          </Button>
        </Stack>
      </Stack>
    </Box>
  )
}
