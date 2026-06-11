"use client"

import { useState, useEffect, useMemo, useRef, useId } from "react"
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
  TextField,
} from "@mui/material"
import { Close as CloseIcon, Add as AddIcon } from "@mui/icons-material"
import type { TabularColumn, TabularRow } from "@/services/tabularReviewApi"
import type { ColumnValueFilterCondition } from "./AdvancedFiltersPanel"
import {
  EMPTY_VALUE_KEY,
  emptyFilterCondition,
  normalizeCellValue,
  displayFilterValue,
  getOperatorsForColumn,
  defaultOperatorForColumn,
  isFilterConditionComplete,
  type ColumnFilterOperator,
} from "@/utils/tabularColumnFilters"
import { isDateColumn } from "@/utils/tabularDateUtils"

function computeValueCounts(
  rows: TabularRow[],
  columnId: string,
): { value: string; count: number }[] {
  const map = new Map<string, number>()
  for (const row of rows) {
    const raw = row.cells[columnId]?.cell_value ?? null
    const key = normalizeCellValue(raw)
    map.set(key, (map.get(key) ?? 0) + 1)
  }
  return Array.from(map.entries())
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count)
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
      maxWidth: 600,
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
  const [currentRows, setCurrentRows] = useState<ColumnValueFilterCondition[]>([emptyFilterCondition()])
  const popoverPaperRef = useRef<HTMLDivElement | null>(null)
  const idPrefix = useId().replace(/:/g, "")

  useEffect(() => {
    if (open) {
      setAppliedConditions(
        valueFilters.length > 0
          ? valueFilters.map((c) => ({
              ...emptyFilterCondition(),
              ...c,
              selectedValues: [...(c.selectedValues ?? [])],
            }))
          : [],
      )
      setCurrentRows([emptyFilterCondition()])
    }
  }, [open, valueFilters])

  const columnById = useMemo(
    () => new Map(columns.map((c) => [c.id, c])),
    [columns],
  )

  const updateCurrentRow = (index: number, patch: Partial<ColumnValueFilterCondition>) => {
    setCurrentRows((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], ...patch }
      return next
    })
  }

  const addFilterRow = () => {
    setCurrentRows((prev) => [...prev, emptyFilterCondition()])
  }

  const removeCurrentRow = (index: number) => {
    setCurrentRows((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : [emptyFilterCondition()]))
  }

  const handleApply = () => {
    const valid = currentRows.filter((c) =>
      isFilterConditionComplete(c, columnById.get(c.columnId)),
    )
    if (valid.length === 0) return
    const nextApplied = [
      ...appliedConditions,
      ...valid.map((c) => ({
        ...c,
        selectedValues: [...c.selectedValues],
        textQuery: c.textQuery,
        dateFrom: c.dateFrom,
        dateTo: c.dateTo,
      })),
    ]
    setAppliedConditions(nextApplied)
    onApply(nextApplied)
    setCurrentRows([emptyFilterCondition()])
  }

  const updateApplied = (index: number, patch: Partial<ColumnValueFilterCondition>) => {
    setAppliedConditions((prev) => {
      const next = prev.map((c, i) => (i === index ? { ...c, ...patch } : c))
      onApply(next)
      return next
    })
  }

  const removeApplied = (index: number) => {
    const next = appliedConditions.filter((_, i) => i !== index)
    setAppliedConditions(next)
    onApply(next)
  }

  const canApplyCurrent = currentRows.some((c) =>
    isFilterConditionComplete(c, columnById.get(c.columnId)),
  )

  return (
    <Popover
      open={open}
      anchorEl={anchorEl}
      onClose={onClose}
      {...popoverProps}
      PaperProps={{ ...popoverProps.PaperProps, ref: popoverPaperRef }}
    >
      <Box sx={{ pb: 1 }}>
        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 2 }}>
          <Typography variant="subtitle1" fontWeight={700} sx={{ color: "#111827", fontSize: "1rem" }}>
            Фильтр по колонке
          </Typography>
          <IconButton size="small" onClick={onClose} aria-label="Закрыть" sx={{ color: "#6B7280", p: 0.5 }}>
            <CloseIcon sx={{ fontSize: 20 }} />
          </IconButton>
        </Box>

        <Stack spacing={1.5} sx={{ mb: 2 }}>
          {currentRows.map((cond, index) => (
            <FilterRow
              key={index}
              rowIndex={index}
              idPrefix={idPrefix}
              condition={cond}
              columns={columns}
              rows={rows}
              onChange={(patch) => updateCurrentRow(index, patch)}
              onRemove={() => removeCurrentRow(index)}
              selectSx={selectSx}
              menuContainerRef={popoverPaperRef}
            />
          ))}
        </Stack>

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
            disabled={!canApplyCurrent}
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

        {appliedConditions.length > 0 && (
          <Stack spacing={1.5} sx={{ mt: 2, pt: 2, borderTop: "1px solid #E5E7EB" }}>
            {appliedConditions.map((cond, index) => (
              <FilterRow
                key={`applied-${index}`}
                rowIndex={1000 + index}
                idPrefix={idPrefix}
                condition={cond}
                columns={columns}
                rows={rows}
                onChange={(patch) => updateApplied(index, patch)}
                onRemove={() => removeApplied(index)}
                selectSx={selectSx}
                menuContainerRef={popoverPaperRef}
              />
            ))}
          </Stack>
        )}
      </Box>
    </Popover>
  )
}

interface FilterRowProps {
  rowIndex: number
  idPrefix: string
  condition: ColumnValueFilterCondition
  columns: TabularColumn[]
  rows: TabularRow[]
  onChange: (patch: Partial<ColumnValueFilterCondition>) => void
  onRemove: () => void
  selectSx: object
  menuContainerRef: React.RefObject<HTMLDivElement | null>
}

function FilterRow({
  rowIndex,
  idPrefix,
  condition,
  columns,
  rows,
  onChange,
  onRemove,
  selectSx,
  menuContainerRef,
}: FilterRowProps) {
  const selectedColumn = columns.find((c) => c.id === condition.columnId)
  const operators = getOperatorsForColumn(selectedColumn)
  const isDate = selectedColumn
    ? isDateColumn(selectedColumn.column_type, selectedColumn.column_label)
    : false

  const valueCounts = useMemo(
    () => (condition.columnId ? computeValueCounts(rows, condition.columnId) : []),
    [rows, condition.columnId],
  )

  const baseId = `${idPrefix}-${rowIndex}`

  const handleColumnChange = (columnId: string) => {
    const col = columns.find((c) => c.id === columnId)
    onChange({
      columnId,
      operator: defaultOperatorForColumn(col),
      selectedValues: [],
      textQuery: "",
      dateFrom: null,
      dateTo: null,
    })
  }

  const handleOperatorChange = (operator: ColumnFilterOperator) => {
    onChange({
      operator,
      selectedValues: [],
      textQuery: "",
      dateFrom: null,
      dateTo: null,
    })
  }

  const showValuePicker =
    condition.operator === "equals" || condition.operator === "not_equals"
  const showTextInput = condition.operator === "contains"
  const showDateSingle =
    isDate &&
    (condition.operator === "equals" ||
      condition.operator === "not_equals" ||
      condition.operator === "date_after" ||
      condition.operator === "date_before")
  const showDateRange = isDate && condition.operator === "date_between"
  const showValueMultiSelect = showValuePicker && !isDate

  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 1 }}>
      <FormControl size="small" sx={{ minWidth: 160, flex: 1 }}>
        <InputLabel id={`${baseId}-col`}>Колонка</InputLabel>
        <Select
          labelId={`${baseId}-col`}
          value={condition.columnId || ""}
          label="Колонка"
          onChange={(e) => handleColumnChange(e.target.value as string)}
          sx={selectSx}
        >
          {columns.map((c) => (
            <MenuItem key={c.id} value={c.id}>
              {c.column_label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <FormControl size="small" sx={{ minWidth: 120 }}>
        <InputLabel id={`${baseId}-op`}>Оператор</InputLabel>
        <Select
          labelId={`${baseId}-op`}
          value={condition.operator}
          label="Оператор"
          onChange={(e) => handleOperatorChange(e.target.value as ColumnFilterOperator)}
          disabled={!condition.columnId}
          sx={selectSx}
        >
          {operators.map((op) => (
            <MenuItem key={op.value} value={op.value}>
              {op.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {showValueMultiSelect && (
        <FormControl size="small" sx={{ minWidth: 180, flex: 1 }}>
          <InputLabel id={`${baseId}-vals`}>Значения</InputLabel>
          <Select
            labelId={`${baseId}-vals`}
            multiple
            value={condition.selectedValues}
            label="Значения"
            onChange={(e) => {
              const v = e.target.value
              onChange({
                selectedValues: typeof v === "string" ? v.split(",") : v,
              })
            }}
            renderValue={(selected) =>
              (selected as string[]).length
                ? (selected as string[]).map((s) => displayFilterValue(s)).join(", ")
                : "Выберите значения"
            }
            disabled={!condition.columnId}
            sx={selectSx}
            MenuProps={{
              disableScrollLock: true,
              container: () => menuContainerRef.current ?? null,
              sx: { zIndex: 9999 },
            }}
          >
            {valueCounts.map(({ value, count }) => (
              <MenuItem key={value === EMPTY_VALUE_KEY ? "__empty" : value} value={value}>
                <Checkbox checked={condition.selectedValues.indexOf(value) > -1} size="small" />
                <ListItemText
                  primary={`${displayFilterValue(value)} (${count})`}
                  primaryTypographyProps={{ variant: "body2" }}
                />
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      )}

      {showTextInput && (
        <TextField
          size="small"
          label="Текст"
          placeholder="например, неустойка"
          value={condition.textQuery}
          onChange={(e) => onChange({ textQuery: e.target.value })}
          disabled={!condition.columnId}
          sx={{ minWidth: 180, flex: 1 }}
        />
      )}

      {showDateSingle && (
        <TextField
          size="small"
          type="date"
          label="Дата"
          value={condition.dateFrom ?? ""}
          onChange={(e) => onChange({ dateFrom: e.target.value || null })}
          disabled={!condition.columnId}
          InputLabelProps={{ shrink: true }}
          sx={{ minWidth: 160 }}
        />
      )}

      {showDateRange && (
        <>
          <TextField
            size="small"
            type="date"
            label="От"
            value={condition.dateFrom ?? ""}
            onChange={(e) => onChange({ dateFrom: e.target.value || null })}
            disabled={!condition.columnId}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 140 }}
          />
          <TextField
            size="small"
            type="date"
            label="До"
            value={condition.dateTo ?? ""}
            onChange={(e) => onChange({ dateTo: e.target.value || null })}
            disabled={!condition.columnId}
            InputLabelProps={{ shrink: true }}
            sx={{ minWidth: 140 }}
          />
        </>
      )}

      {condition.operator === "not_empty" && condition.columnId && (
        <Typography variant="body2" sx={{ color: "#6B7280", px: 0.5 }}>
          Только заполненные ячейки
        </Typography>
      )}

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
