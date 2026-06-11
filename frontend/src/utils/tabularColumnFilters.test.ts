import { describe, expect, it } from "vitest"
import type { TabularColumn, TabularRow } from "@/services/tabularReviewApi"
import {
  applyColumnValueFilters,
  evaluateColumnValueFilter,
  emptyFilterCondition,
  isFilterConditionComplete,
} from "./tabularColumnFilters"

const dateColumn: TabularColumn = {
  id: "col-date",
  column_label: "Дата документа",
  column_type: "date",
  prompt: "",
  order_index: 0,
  is_pinned: false,
}

const textColumn: TabularColumn = {
  id: "col-text",
  column_label: "Кратко",
  column_type: "text",
  prompt: "",
  order_index: 1,
  is_pinned: false,
}

const rows: TabularRow[] = [
  {
    file_id: "f1",
    file_name: "a.pdf",
    status: "not_reviewed",
    cells: {
      "col-date": { cell_value: "2024-03-15", status: "completed" },
      "col-text": { cell_value: "договор с неустойкой", status: "completed" },
    },
  },
  {
    file_id: "f2",
    file_name: "b.pdf",
    status: "not_reviewed",
    cells: {
      "col-date": { cell_value: "", status: "completed" },
      "col-text": { cell_value: "иск", status: "completed" },
    },
  },
  {
    file_id: "f3",
    file_name: "c.pdf",
    status: "not_reviewed",
    cells: {
      "col-date": { cell_value: "2024-01-10", status: "completed" },
      "col-text": { cell_value: "N/A", status: "completed" },
    },
  },
]

describe("evaluateColumnValueFilter", () => {
  it("contains matches substring", () => {
    const cond = { ...emptyFilterCondition(), columnId: "col-text", operator: "contains" as const, textQuery: "неустой" }
    expect(evaluateColumnValueFilter("договор с неустойкой", cond, textColumn)).toBe(true)
    expect(evaluateColumnValueFilter("иск", cond, textColumn)).toBe(false)
  })

  it("not_empty excludes blanks and N/A", () => {
    const cond = { ...emptyFilterCondition(), columnId: "col-text", operator: "not_empty" as const }
    expect(evaluateColumnValueFilter("иск", cond, textColumn)).toBe(true)
    expect(evaluateColumnValueFilter("", cond, textColumn)).toBe(false)
    expect(evaluateColumnValueFilter("N/A", cond, textColumn)).toBe(false)
  })

  it("date_after filters correctly", () => {
    const cond = {
      ...emptyFilterCondition(),
      columnId: "col-date",
      operator: "date_after" as const,
      dateFrom: "2024-02-01",
    }
    expect(evaluateColumnValueFilter("2024-03-15", cond, dateColumn)).toBe(true)
    expect(evaluateColumnValueFilter("2024-01-10", cond, dateColumn)).toBe(false)
  })

  it("date_between includes range endpoints", () => {
    const cond = {
      ...emptyFilterCondition(),
      columnId: "col-date",
      operator: "date_between" as const,
      dateFrom: "2024-01-01",
      dateTo: "2024-02-01",
    }
    expect(evaluateColumnValueFilter("2024-01-10", cond, dateColumn)).toBe(true)
    expect(evaluateColumnValueFilter("2024-03-15", cond, dateColumn)).toBe(false)
  })
})

describe("applyColumnValueFilters", () => {
  it("applies multiple AND conditions", () => {
    const result = applyColumnValueFilters(
      rows,
      [
        {
          ...emptyFilterCondition(),
          columnId: "col-text",
          operator: "not_empty",
        },
        {
          ...emptyFilterCondition(),
          columnId: "col-date",
          operator: "date_after",
          dateFrom: "2024-02-01",
        },
      ],
      [dateColumn, textColumn],
    )
    expect(result.map((r) => r.file_id)).toEqual(["f1"])
  })
})

describe("isFilterConditionComplete", () => {
  it("requires text for contains", () => {
    const cond = { ...emptyFilterCondition(), columnId: "col-text", operator: "contains" as const }
    expect(isFilterConditionComplete(cond, textColumn)).toBe(false)
    expect(isFilterConditionComplete({ ...cond, textQuery: "x" }, textColumn)).toBe(true)
  })
})
