import { describe, expect, it } from "vitest"
import {
  compareTabularCellValues,
  compareTabularCellValuesForSort,
  parseTabularDateMs,
} from "./tabularDateUtils"

describe("parseTabularDateMs", () => {
  it("parses ISO and DD.MM.YYYY", () => {
    expect(parseTabularDateMs("2024-03-15")).not.toBeNull()
    expect(parseTabularDateMs("15.03.2024")).not.toBeNull()
    expect(parseTabularDateMs("")).toBeNull()
    expect(parseTabularDateMs("N/A")).toBeNull()
  })
})

describe("compareTabularCellValues", () => {
  it("sorts dates chronologically", () => {
    expect(
      compareTabularCellValues("2024-01-10", "2024-03-15", "date", "Дата"),
    ).toBeLessThan(0)
  })
})

describe("compareTabularCellValuesForSort", () => {
  it("keeps empty values at the bottom when ascending", () => {
    expect(
      compareTabularCellValuesForSort("", "2024-03-15", "date", "Дата", false),
    ).toBeGreaterThan(0)
  })

  it("keeps empty values at the bottom when descending", () => {
    expect(
      compareTabularCellValuesForSort("", "2024-03-15", "date", "Дата", true),
    ).toBeLessThan(0)
  })
})
