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
  IconButton,
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

export const InlineCellEditor: React.FC<InlineCellEditorProps> = ({
  cell,
  column,
  onSave,
  onCancel,
  initialValue,
}) => {
  const [value, setValue] = useState<string>(initialValue || cell?.cell_value || "")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setValue(initialValue || cell?.cell_value || "")
  }, [cell, initialValue])

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

  // Render based on column type
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
            placeholder={`Enter ${column.column_label.toLowerCase()}...`}
            variant="outlined"
            size="small"
            autoFocus
            error={!!error}
            helperText={error}
          />
        )

      case "bulleted_list":
        return (
          <TextField
            multiline
            rows={4}
            fullWidth
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Enter items, one per line (will be formatted as bullets)..."
            variant="outlined"
            size="small"
            autoFocus
            error={!!error}
            helperText={error}
          />
        )

      case "number":
      case "currency":
        return (
          <TextField
            type="number"
            fullWidth
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Enter ${column.column_label.toLowerCase()}...`}
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
            <ToggleButton value="Yes">Yes</ToggleButton>
            <ToggleButton value="No">No</ToggleButton>
            <ToggleButton value="Unknown">Unknown</ToggleButton>
          </ToggleButtonGroup>
        )

      case "tag":
      case "multiple_tags":
        const options = column.column_config?.options || []
        const isMultiple = column.column_type === "multiple_tags"
        
        if (isMultiple) {
          // For multiple tags, use a text field with comma-separated values
          return (
            <TextField
              fullWidth
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Enter tags separated by commas. Available: ${options.map((o: any) => o.label).join(", ")}`}
              variant="outlined"
              size="small"
              autoFocus
              error={!!error}
              helperText={error || `Available options: ${options.map((o: any) => o.label).join(", ")}`}
            />
          )
        } else {
          // Single tag - use select
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
                {options.map((option: any) => (
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
            placeholder={`Enter ${column.column_label.toLowerCase()}...`}
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
            Cancel
          </Button>
          <Button
            size="small"
            variant="contained"
            onClick={handleSave}
            disabled={saving}
            startIcon={<CheckIcon />}
          >
            {saving ? "Saving..." : "Save"}
          </Button>
        </Stack>
      </Stack>
    </Box>
  )
}

