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
  Chip,
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
    sx: {
      minWidth: 480,
      maxWidth: 560,
      p: 2.5,
      borderRadius: 2,
      boxShadow: "0 4px 20px rgba(0,0,0,0.08)",
      border: "1px solid #E5E7EB",
    },
  },
}

const selectSx = {
  borderRadius: "8px",
  bgcolor: "#FAFAFA",
  "& .MuiOutlinedInput-notchedOutline": { borderColor: "#E5E7EB" },
  "&:hover .MuiOutlinedInput-notchedOutline": { borderColor: "#D1D5DB" },
  "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
    borderColor: "#9CA3AF",
    borderWidth: "1.5px",
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
  const [appliedConditions, setAppliedConditions] = useState<ColumnValueFilterCondition[]>([])
  const [currentRows, setCurrentRows] = useState<ColumnValueFilterCondition[]>([emptyCondition()])

  useEffect(() => {
    if (open) {
      setAppliedConditions(
        valueFilters.length > 0
          ? valueFilters.map((c) => ({ ...c, selectedValues: [...c.selectedValues] }))
          : []
      )
      setCurrentRows([emptyCondition()])
    }
  }, [open, valueFilters])

  const updateCurrentRow = (index: number, patch: Partial<ColumnValueFilterCondition>) => {
    setCurrentRows((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], ...patch }
      return next
    })
  }

  const addFilterRow = () => {
    setCurrentRows((prev) => [...prev, emptyCondition()])
  }

  const removeCurrentRow = (index: number) => {
    setCurrentRows((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : [emptyCondition()]))
  }

  const handleApply = () => {
    const valid = currentRows.filter((c) => c.columnId && c.selectedValues.length > 0)
    if (valid.length === 0) return
    const nextApplied = [...appliedConditions, ...valid.map((c) => ({ ...c, selectedValues: [...c.selectedValues] }))]
    setAppliedConditions(nextApplied)
    onApply(nextApplied)
    setCurrentRows([emptyCondition()])
  }

  const removeApplied = (index: number) => {
    const next = appliedConditions.filter((_, i) => i !== index)
    setAppliedConditions(next)
    onApply(next)
  }

  return (
    <Popover
      open={open}
      anchorEl={anchorEl}
      onClose={onClose}
      {...popoverProps}
    >
      <Box sx={{ pb: 1 }}>
        {/* Заголовок слева, крестик справа */}
        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 2 }}>
          <Typography variant="subtitle1" fontWeight={700} sx={{ color: "#111827", fontSize: "1rem" }}>
            Фильтр по колонке
          </Typography>
          <IconButton size="small" onClick={onClose} aria-label="Закрыть" sx={{ color: "#6B7280", p: 0.5 }}>
            <CloseIcon sx={{ fontSize: 20 }} />
          </IconButton>
        </Box>

        {/* Строки фильтра: колонка — Равно — Выберите значения — x */}
        <Stack spacing={1.5} sx={{ mb: 2 }}>
          {currentRows.map((cond, index) => (
            <FilterRow
              key={index}
              rowIndex={index}
              condition={cond}
              columns={columns}
              rows={rows}
              onChange={(patch) => updateCurrentRow(index, patch)}
              onRemove={() => removeCurrentRow(index)}
              selectSx={selectSx}
            />
          ))}
        </Stack>

        {/* Кнопки внизу: слева Добавить фильтр, справа Применить */}
        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 1 }}>
          <Button
            startIcon={<AddIcon sx={{ fontSize: 18 }} />}
            onClick={addFilterRow}
            size="medium"
            aria-label="Добавить фильтр"
            sx={{
              borderRadius: "8px",
              textTransform: "none",
              color: "#6B7280",
              bgcolor: "#F3F4F6",
              "&:hover": { bgcolor: "#E5E7EB", color: "#374151" },
            }}
          >
            Добавить фильтр
          </Button>
          <Button
            variant="contained"
            size="medium"
            onClick={handleApply}
            disabled={!currentRows.some((c) => c.columnId && c.selectedValues.length > 0)}
            aria-label="Применить"
            sx={{
              borderRadius: "8px",
              textTransform: "none",
              bgcolor: "#374151",
              "&:hover": { bgcolor: "#1F2937" },
            }}
          >
            Применить
          </Button>
        </Box>

        {/* Применённые фильтры — чипы внизу */}
        {appliedConditions.length > 0 && (
          <Box sx={{ mt: 2, pt: 2, borderTop: "1px solid #E5E7EB" }}>
            <Typography variant="caption" sx={{ color: "#6B7280", display: "block", mb: 1 }}>
              Применённые фильтры
            </Typography>
            <Stack direction="row" flexWrap="wrap" gap={0.75} useFlexGap>
              {appliedConditions.map((cond, index) => {
                const col = columns.find((c) => c.id === cond.columnId)
                const label = col ? col.column_label : cond.columnId
                const valuesStr = cond.selectedValues.map((v) => displayValue(v)).join(", ")
                return (
                  <Chip
                    key={index}
                    size="small"
                    label={`${label} = ${valuesStr}`}
                    onDelete={() => removeApplied(index)}
                    sx={{ borderRadius: "8px" }}
                  />
                )
              })}
            </Stack>
          </Box>
        )}
      </Box>
    </Popover>
  )
}

interface FilterRowProps {
  rowIndex: number
  condition: ColumnValueFilterCondition
  columns: TabularColumn[]
  rows: TabularRow[]
  onChange: (patch: Partial<ColumnValueFilterCondition>) => void
  onRemove: () => void
  selectSx: object
}

function FilterRow({
  rowIndex,
  condition,
  columns,
  rows,
  onChange,
  onRemove,
  selectSx,
}: FilterRowProps) {
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
        alignItems: "center",
        gap: 1,
      }}
    >
      <FormControl size="small" sx={{ minWidth: 160, flex: 1 }}>
        <InputLabel id={`filter-col-${rowIndex}`}>Колонка</InputLabel>
        <Select
          labelId={`filter-col-${rowIndex}`}
          value={condition.columnId || ""}
          label="Колонка"
          onChange={(e) =>
            onChange({
              columnId: e.target.value as string,
              selectedValues: [],
            })
          }
          sx={selectSx}
        >
          {columns.map((c) => (
            <MenuItem key={c.id} value={c.id}>
              {c.column_label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <FormControl size="small" sx={{ minWidth: 100 }}>
        <InputLabel id={`filter-op-${rowIndex}`}>Оператор</InputLabel>
        <Select value="equals" label="Оператор" disabled sx={selectSx}>
          <MenuItem value="equals">Равно</MenuItem>
        </Select>
      </FormControl>

      <FormControl size="small" sx={{ minWidth: 180, flex: 1 }}>
        <InputLabel id={`filter-vals-${rowIndex}`}>Выберите значения</InputLabel>
        <Select
          labelId={`filter-vals-${rowIndex}`}
          multiple
          value={condition.selectedValues}
          label="Выберите значения"
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
              : "Выберите значения"
          }
          disabled={!condition.columnId}
          sx={selectSx}
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

      <IconButton
        size="small"
        onClick={onRemove}
        aria-label="Удалить условие"
        sx={{ color: "#6B7280", "&:hover": { color: "#374151", bgcolor: "#F3F4F6" } }}
      >
        <CloseIcon sx={{ fontSize: 18 }} />
      </IconButton>
    </Box>
  )
}
