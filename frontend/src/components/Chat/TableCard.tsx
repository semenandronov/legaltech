"use client"

import React from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/UI/Card"
import { Button } from "@/components/UI/Button"
import { Table2, ExternalLink, FileText } from "lucide-react"
import { useNavigate } from "react-router-dom"

interface TableCardProps {
  reviewId: string
  caseId: string
  tableData: {
    id: string
    name: string
    description?: string
    columns_count?: number
    rows_count?: number
    preview?: {
      columns: string[]
      rows: Array<Record<string, string>>
    }
  }
  onOpen?: () => void
}

export const TableCard: React.FC<TableCardProps> = ({
  reviewId,
  caseId,
  tableData,
  onOpen,
}) => {
  const navigate = useNavigate()

  const handleOpen = () => {
    if (onOpen) {
      onOpen()
    } else {
      navigate(`/cases/${caseId}/tabular-review/${reviewId}`)
    }
  }

  const previewRows = tableData.preview?.rows || []
  const previewColumns = tableData.preview?.columns || []

  return (
    <Card className="w-full max-w-2xl border border-[#E5E7EB] hover:border-[#2563EB] transition-colors">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Table2 className="w-5 h-5 text-[#2563EB]" />
            <CardTitle className="text-base font-semibold text-[#1F2937]">
              {tableData.name}
            </CardTitle>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleOpen}
            className="text-[#2563EB] hover:text-[#1D4ED8] hover:bg-[#EFF6FF]"
          >
            <ExternalLink className="w-4 h-4 mr-1" />
            Открыть таблицу
          </Button>
        </div>
        {tableData.description && (
          <p className="text-sm text-[#6B7280] mt-1">{tableData.description}</p>
        )}
        <div className="flex items-center gap-4 mt-2 text-xs text-[#6B7280]">
          <span className="flex items-center gap-1">
            <FileText className="w-3 h-3" />
            {tableData.rows_count || 0} документов
          </span>
          <span>•</span>
          <span>{tableData.columns_count || 0} колонок</span>
        </div>
      </CardHeader>
      
      {previewRows.length > 0 && previewColumns.length > 0 && (
        <CardContent className="pt-0">
          <div className="overflow-x-auto border border-[#E5E7EB] rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-[#F9FAFB] border-b border-[#E5E7EB]">
                <tr>
                  {previewColumns.slice(0, 4).map((col, idx) => (
                    <th
                      key={idx}
                      className="px-3 py-2 text-left text-xs font-medium text-[#6B7280] whitespace-nowrap"
                    >
                      {col}
                    </th>
                  ))}
                  {previewColumns.length > 4 && (
                    <th className="px-3 py-2 text-left text-xs font-medium text-[#6B7280]">
                      ...
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {previewRows.slice(0, 3).map((row, rowIdx) => (
                  <tr
                    key={rowIdx}
                    className="border-b border-[#E5E7EB] hover:bg-[#F9FAFB]"
                  >
                    {previewColumns.slice(0, 4).map((col, colIdx) => (
                      <td
                        key={colIdx}
                        className="px-3 py-2 text-[#1F2937] whitespace-nowrap"
                      >
                        {row[col] || "-"}
                      </td>
                    ))}
                    {previewColumns.length > 4 && (
                      <td className="px-3 py-2 text-[#6B7280]">...</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {previewRows.length > 3 && (
            <p className="text-xs text-[#6B7280] mt-2 text-center">
              И еще {previewRows.length - 3} строк...
            </p>
          )}
        </CardContent>
      )}
    </Card>
  )
}

