"use client"

import React, { useState, useCallback } from "react"
import {
  Box,
  Drawer,
  Typography,
  Button,
  Stack,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Chip,
  Divider,
  IconButton,
  Checkbox,
  FormControlLabel,
  Slider,
  RadioGroup,
  Radio,
  FormLabel,
} from "@mui/material"
import {
  FilterList as FilterIcon,
  Close as CloseIcon,
  Clear as ClearIcon,
} from "@mui/icons-material"
import { TabularColumn } from "@/services/tabularReviewApi"

export interface AdvancedFilters {
  // Status filters
  cellStatuses: string[] // pending, processing, completed, reviewed
  documentStatuses: string[] // not_reviewed, reviewed, flagged, pending_clarification
  
  // Confidence filter
  confidenceMin: number | null
  confidenceMax: number | null
  
  // Comments filter
  hasComments: boolean | null // null = all, true = with comments, false = without comments
  hasUnresolvedComments: boolean | null
  
  // Locking filter
  isLocked: boolean | null // null = all, true = locked, false = unlocked
  
  // Column type filter
  columnTypes: string[] // text, bulleted_list, number, currency, yes_no, date, tag, multiple_tags, verbatim, manual_input
  
  // Date filters
  createdAfter: string | null
  createdBefore: string | null
  updatedAfter: string | null
  updatedBefore: string | null
  
  // Text search in specific columns
  columnTextFilters: Record<string, string> // columnId -> search text
  
  // Logic operator
  logicOperator: "AND" | "OR" // How to combine multiple filters
}

const defaultFilters: AdvancedFilters = {
  cellStatuses: [],
  documentStatuses: [],
  confidenceMin: null,
  confidenceMax: null,
  hasComments: null,
  hasUnresolvedComments: null,
  isLocked: null,
  columnTypes: [],
  createdAfter: null,
  createdBefore: null,
  updatedAfter: null,
  updatedBefore: null,
  columnTextFilters: {},
  logicOperator: "AND",
}

interface AdvancedFiltersPanelProps {
  open: boolean
  onClose: () => void
  filters: AdvancedFilters
  onFiltersChange: (filters: AdvancedFilters) => void
  columns: TabularColumn[]
}

export const AdvancedFiltersPanel: React.FC<AdvancedFiltersPanelProps> = ({
  open,
  onClose,
  filters,
  onFiltersChange,
  columns,
}) => {
  const [localFilters, setLocalFilters] = useState<AdvancedFilters>(filters)

  const handleFilterChange = useCallback((key: keyof AdvancedFilters, value: any) => {
    setLocalFilters((prev) => ({
      ...prev,
      [key]: value,
    }))
  }, [])

  const handleApply = useCallback(() => {
    onFiltersChange(localFilters)
    onClose()
  }, [localFilters, onFiltersChange, onClose])

  const handleReset = useCallback(() => {
    setLocalFilters(defaultFilters)
    onFiltersChange(defaultFilters)
  }, [onFiltersChange])

  const handleClear = useCallback(() => {
    setLocalFilters(defaultFilters)
  }, [])

  const getActiveFiltersCount = useCallback(() => {
    let count = 0
    if (localFilters.cellStatuses.length > 0) count++
    if (localFilters.documentStatuses.length > 0) count++
    if (localFilters.confidenceMin !== null || localFilters.confidenceMax !== null) count++
    if (localFilters.hasComments !== null) count++
    if (localFilters.hasUnresolvedComments !== null) count++
    if (localFilters.isLocked !== null) count++
    if (localFilters.columnTypes.length > 0) count++
    if (localFilters.createdAfter || localFilters.createdBefore) count++
    if (localFilters.updatedAfter || localFilters.updatedBefore) count++
    if (Object.keys(localFilters.columnTextFilters).length > 0) count++
    return count
  }, [localFilters])

  const activeFiltersCount = getActiveFiltersCount()

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: { width: 400, p: 3 },
      }}
    >
      <Stack spacing={3}>
        {/* Header */}
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Typography variant="h6">Расширенные фильтры</Typography>
          <IconButton onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Box>

        {activeFiltersCount > 0 && (
          <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
            <Chip
              label={`${activeFiltersCount} активных фильтров`}
              size="small"
              color="primary"
            />
            <Button
              size="small"
              startIcon={<ClearIcon />}
              onClick={handleClear}
            >
              Очистить
            </Button>
          </Box>
        )}

        <Divider />

        {/* Logic Operator */}
        <FormControl fullWidth>
          <FormLabel>Логический оператор</FormLabel>
          <RadioGroup
            row
            value={localFilters.logicOperator}
            onChange={(e) => handleFilterChange("logicOperator", e.target.value)}
          >
            <FormControlLabel value="AND" control={<Radio />} label="И (AND)" />
            <FormControlLabel value="OR" control={<Radio />} label="ИЛИ (OR)" />
          </RadioGroup>
        </FormControl>

        <Divider />

        {/* Cell Status Filter */}
        <FormControl fullWidth>
          <InputLabel>Статус ячеек</InputLabel>
          <Select
            multiple
            value={localFilters.cellStatuses}
            onChange={(e) => handleFilterChange("cellStatuses", e.target.value)}
            renderValue={(selected) => (
              <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                {selected.map((value) => (
                  <Chip key={value} label={value} size="small" />
                ))}
              </Box>
            )}
          >
            <MenuItem value="pending">Pending</MenuItem>
            <MenuItem value="processing">Processing</MenuItem>
            <MenuItem value="completed">Completed</MenuItem>
            <MenuItem value="reviewed">Reviewed</MenuItem>
          </Select>
        </FormControl>

        {/* Document Status Filter */}
        <FormControl fullWidth>
          <InputLabel>Статус документов</InputLabel>
          <Select
            multiple
            value={localFilters.documentStatuses}
            onChange={(e) => handleFilterChange("documentStatuses", e.target.value)}
            renderValue={(selected) => (
              <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                {selected.map((value) => (
                  <Chip key={value} label={value} size="small" />
                ))}
              </Box>
            )}
          >
            <MenuItem value="not_reviewed">Not Reviewed</MenuItem>
            <MenuItem value="reviewed">Reviewed</MenuItem>
            <MenuItem value="flagged">Flagged</MenuItem>
            <MenuItem value="pending_clarification">Pending Clarification</MenuItem>
          </Select>
        </FormControl>

        <Divider />

        {/* Confidence Filter */}
        <Box>
          <Typography gutterBottom>Уверенность (Confidence Score)</Typography>
          <Stack spacing={2} direction="row" sx={{ mb: 1 }} alignItems="center">
            <TextField
              type="number"
              label="Мин"
              size="small"
              value={localFilters.confidenceMin ?? ""}
              onChange={(e) =>
                handleFilterChange(
                  "confidenceMin",
                  e.target.value ? parseFloat(e.target.value) : null
                )
              }
              inputProps={{ min: 0, max: 1, step: 0.01 }}
              sx={{ width: 100 }}
            />
            <Typography>-</Typography>
            <TextField
              type="number"
              label="Макс"
              size="small"
              value={localFilters.confidenceMax ?? ""}
              onChange={(e) =>
                handleFilterChange(
                  "confidenceMax",
                  e.target.value ? parseFloat(e.target.value) : null
                )
              }
              inputProps={{ min: 0, max: 1, step: 0.01 }}
              sx={{ width: 100 }}
            />
          </Stack>
          <Slider
            value={[
              localFilters.confidenceMin ?? 0,
              localFilters.confidenceMax ?? 1,
            ]}
            onChange={(_, newValue) => {
              const [min, max] = newValue as number[]
              handleFilterChange("confidenceMin", min)
              handleFilterChange("confidenceMax", max)
            }}
            min={0}
            max={1}
            step={0.01}
            valueLabelDisplay="auto"
            valueLabelFormat={(value) => `${Math.round(value * 100)}%`}
          />
        </Box>

        <Divider />

        {/* Comments Filter */}
        <FormControl fullWidth>
          <InputLabel>Комментарии</InputLabel>
          <Select
            value={
              localFilters.hasComments === null
                ? "all"
                : localFilters.hasComments
                ? "with"
                : "without"
            }
            onChange={(e) => {
              const value = e.target.value
              handleFilterChange(
                "hasComments",
                value === "all" ? null : value === "with"
              )
            }}
          >
            <MenuItem value="all">Все</MenuItem>
            <MenuItem value="with">С комментариями</MenuItem>
            <MenuItem value="without">Без комментариев</MenuItem>
          </Select>
        </FormControl>

        <FormControlLabel
          control={
            <Checkbox
              checked={localFilters.hasUnresolvedComments === true}
              onChange={(e) =>
                handleFilterChange(
                  "hasUnresolvedComments",
                  e.target.checked ? true : null
                )
              }
            />
          }
          label="Только с нерешенными комментариями"
        />

        <Divider />

        {/* Locking Filter */}
        <FormControl fullWidth>
          <InputLabel>Блокировка</InputLabel>
          <Select
            value={
              localFilters.isLocked === null
                ? "all"
                : localFilters.isLocked
                ? "locked"
                : "unlocked"
            }
            onChange={(e) => {
              const value = e.target.value
              handleFilterChange(
                "isLocked",
                value === "all" ? null : value === "locked"
              )
            }}
          >
            <MenuItem value="all">Все</MenuItem>
            <MenuItem value="locked">Заблокированные</MenuItem>
            <MenuItem value="unlocked">Незаблокированные</MenuItem>
          </Select>
        </FormControl>

        <Divider />

        {/* Column Type Filter */}
        <FormControl fullWidth>
          <InputLabel>Тип колонки</InputLabel>
          <Select
            multiple
            value={localFilters.columnTypes}
            onChange={(e) => handleFilterChange("columnTypes", e.target.value)}
            renderValue={(selected) => (
              <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                {selected.map((value) => (
                  <Chip key={value} label={value} size="small" />
                ))}
              </Box>
            )}
          >
            <MenuItem value="text">Text</MenuItem>
            <MenuItem value="bulleted_list">Bulleted List</MenuItem>
            <MenuItem value="number">Number</MenuItem>
            <MenuItem value="currency">Currency</MenuItem>
            <MenuItem value="yes_no">Yes/No</MenuItem>
            <MenuItem value="date">Date</MenuItem>
            <MenuItem value="tag">Tag</MenuItem>
            <MenuItem value="multiple_tags">Multiple Tags</MenuItem>
            <MenuItem value="verbatim">Verbatim</MenuItem>
            <MenuItem value="manual_input">Manual Input</MenuItem>
          </Select>
        </FormControl>

        <Divider />

        {/* Date Filters */}
        <Typography variant="subtitle2">Дата создания</Typography>
        <Stack spacing={2} direction="row">
          <TextField
            type="date"
            label="После"
            size="small"
            value={localFilters.createdAfter ?? ""}
            onChange={(e) => handleFilterChange("createdAfter", e.target.value || null)}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
          <TextField
            type="date"
            label="До"
            size="small"
            value={localFilters.createdBefore ?? ""}
            onChange={(e) => handleFilterChange("createdBefore", e.target.value || null)}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
        </Stack>

        <Typography variant="subtitle2">Дата обновления</Typography>
        <Stack spacing={2} direction="row">
          <TextField
            type="date"
            label="После"
            size="small"
            value={localFilters.updatedAfter ?? ""}
            onChange={(e) => handleFilterChange("updatedAfter", e.target.value || null)}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
          <TextField
            type="date"
            label="До"
            size="small"
            value={localFilters.updatedBefore ?? ""}
            onChange={(e) => handleFilterChange("updatedBefore", e.target.value || null)}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
        </Stack>

        <Divider />

        {/* Column Text Filters */}
        {columns.length > 0 && (
          <Box>
            <Typography variant="subtitle2" gutterBottom>
              Поиск в колонках
            </Typography>
            <Stack spacing={2}>
              {columns.slice(0, 5).map((column) => (
                <TextField
                  key={column.id}
                  label={column.column_label}
                  size="small"
                  value={localFilters.columnTextFilters[column.id] || ""}
                  onChange={(e) =>
                    handleFilterChange("columnTextFilters", {
                      ...localFilters.columnTextFilters,
                      [column.id]: e.target.value || undefined,
                    })
                  }
                  fullWidth
                />
              ))}
            </Stack>
          </Box>
        )}

        <Divider />

        {/* Actions */}
        <Stack spacing={2} direction="row">
          <Button variant="outlined" onClick={handleReset} fullWidth>
            Сбросить все
          </Button>
          <Button variant="contained" onClick={handleApply} fullWidth>
            Применить
          </Button>
        </Stack>
      </Stack>
    </Drawer>
  )
}

