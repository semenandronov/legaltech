"use client"

import { useState, useEffect, useMemo } from "react"
import {
  Popover,
  Box,
  Typography,
  Button,
  IconButton,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  ListItemText,
  Checkbox,
  Stack,
} from "@mui/material"
import { Close as CloseIcon, Add as AddIcon } from "@mui/icons-material"
import type { TabularColumn, TabularRow } from "@/services/tabularReviewApi"
import type { ColumnValueFilterCondition } from "./AdvancedFiltersPanel"

const EMPTY_VALUE_KEY = ""
const EMPTY_VALUE_LABEL = "—"

function normalizeCellValue(val: string | null | undefined): string {
  return val == null || val === "" ? EMPTY_VALUE_KEY : String(val).trim()
}

function computeValueCounts(
  rows: TabularRow[],
  columnId: string
): { value: string; count: number }[] {
  const map = new Map<string, number>()
  for (const row of rows) {
    const raw = row.cells[columnId]?.cell_value ?? null
    const key = normalizeCellValue(raw)
    map.set(key, (map.get(key) ?? 0) + 1)
  }
  const result = Array.from(map.entries())
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count)
  return result
}

function displayValue(value: string): string {
  return value === EMPTY_VALUE_KEY ? EMPTY_VALUE_LABEL : value
}

const popoverProps = {
  anchorReference: "anchorEl" as const,
  anchorOrigin: { vertical: "bottom" as const, horizontal: "left" as const },
  transformOrigin: { vertical: "top" as const, horizontal: "left" as const },
  slotProps: {
    root: { disableScrollLock: true },
    backdrop: { sx: { backgroundColor: "transparent" } },
  },
  PaperProps: {
    sx: { minWidth: 420, maxWidth: 520, p: 2, borderRadius: 2, boxShadow: 2 },
  },
}

const emptyCondition = (): ColumnValueFilterCondition => ({
  columnId: "",
  operator: "equals",
  selectedValues: [],
})

export interface FilterPopoverProps {
  open: boolean
  anchorEl: HTMLElement | null
  onClose: () => void
  columns: TabularColumn[]
  rows: TabularRow[]
  valueFilters: ColumnValueFilterCondition[]
  onApply: (filters: ColumnValueFilterCondition[]) => void
}

export function FilterPopover({
  open,
  anchorEl,
  onClose,
  columns,
  rows,
  valueFilters,
  onApply,
}: FilterPopoverProps) {
  const [conditions, setConditions] = useState<ColumnValueFilterCondition[]>([])

  useEffect(() => {
    if (open) {
      setConditions(
        valueFilters.length > 0
          ? valueFilters.map((c) => ({ ...c, selectedValues: [...c.selectedValues] }))
          : [emptyCondition()]
      )
    }
  }, [open, valueFilters])

  const updateCondition = (index: number, patch: Partial<ColumnValueFilterCondition>) => {
    setConditions((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], ...patch }
      return next
    })
  }

  const addFilter = () => {
    setConditions((prev) => [...prev, emptyCondition()])
  }

  const removeCondition = (index: number) => {
    setConditions((prev) => prev.filter((_, i) => i !== index))
  }

  const handleApply = () => {
    const valid = conditions.filter(
      (c) => c.columnId && c.selectedValues.length > 0
    )
    onApply(valid)
    onClose()
  }

  return (
    <Popover
      open={open}
      anchorEl={anchorEl}
      onClose={onClose}
      {...popoverProps}
    >
      <Box sx={{ pb: 1 }}>
        {/* Header */}
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            mb: 2,
          }}
        >
          <Typography variant="subtitle1" fontWeight={600}>
            Filter
          </Typography>
          <IconButton
            size="small"
            onClick={onClose}
            aria-label="Close"
            sx={{ mr: -0.5 }}
          >
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>

        {/* Condition rows */}
        <Stack spacing={2}>
          {conditions.map((cond, index) => (
            <ConditionRow
              key={index}
              condition={cond}
              columns={columns}
              rows={rows}
              onChange={(patch) => updateCondition(index, patch)}
              onRemove={() => removeCondition(index)}
              canRemove={conditions.length > 1}
              onApply={handleApply}
            />
          ))}
        </Stack>

        {/* Add filter */}
        <Button
          startIcon={<AddIcon />}
          onClick={addFilter}
          size="small"
          sx={{ mt: 2 }}
          aria-label="Add filter"
        >
          Add filter
        </Button>
      </Box>
    </Popover>
  )
}

interface ConditionRowProps {
  condition: ColumnValueFilterCondition
  columns: TabularColumn[]
  rows: TabularRow[]
  onChange: (patch: Partial<ColumnValueFilterCondition>) => void
  onRemove: () => void
  canRemove: boolean
  onApply: () => void
}

function ConditionRow({
  condition,
  columns,
  rows,
  onChange,
  onRemove,
  canRemove,
  onApply,
}: ConditionRowProps) {
  const valueCounts = useMemo(
    () =>
      condition.columnId
        ? computeValueCounts(rows, condition.columnId)
        : [],
    [rows, condition.columnId]
  )

  return (
    <Box
      sx={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "flex-start",
        gap: 1,
      }}
    >
      <FormControl size="small" sx={{ minWidth: 140 }}>
        <InputLabel id={`col-${condition.columnId}`}>Select column</InputLabel>
        <Select
          labelId={`col-${condition.columnId}`}
          value={condition.columnId || ""}
          label="Select column"
          onChange={(e) =>
            onChange({
              columnId: e.target.value as string,
              selectedValues: [],
            })
          }
        >
          {columns.map((c) => (
            <MenuItem key={c.id} value={c.id}>
              {c.column_label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <FormControl size="small" sx={{ minWidth: 100 }}>
        <InputLabel>Operator</InputLabel>
        <Select value="equals" label="Operator" disabled>
          <MenuItem value="equals">Equals</MenuItem>
        </Select>
      </FormControl>

      <FormControl size="small" sx={{ minWidth: 180 }}>
        <InputLabel id={`vals-${condition.columnId}`}>Select values</InputLabel>
        <Select
          labelId={`vals-${condition.columnId}`}
          multiple
          value={condition.selectedValues}
          label="Select values"
          onChange={(e) => {
            const v = e.target.value
            onChange({
              selectedValues: typeof v === "string" ? v.split(",") : v,
            })
          }}
          renderValue={(selected) =>
            (selected as string[]).length
              ? (selected as string[])
                  .map((s) => displayValue(s))
                  .join(", ")
              : "Select values"
          }
          disabled={!condition.columnId}
        >
          {valueCounts.map(({ value, count }) => (
            <MenuItem key={value === EMPTY_VALUE_KEY ? "__empty" : value} value={value}>
              <Checkbox
                checked={condition.selectedValues.indexOf(value) > -1}
                size="small"
              />
              <ListItemText
                primary={`${displayValue(value)} (${count})`}
                primaryTypographyProps={{ variant: "body2" }}
              />
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <Button
        variant="contained"
        size="small"
        onClick={onApply}
        aria-label="Apply"
        sx={{ alignSelf: "center" }}
      >
        Apply
      </Button>

      {canRemove && (
        <IconButton
          size="small"
          onClick={onRemove}
          aria-label="Remove condition"
          sx={{ alignSelf: "center" }}
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      )}
    </Box>
  )
}
