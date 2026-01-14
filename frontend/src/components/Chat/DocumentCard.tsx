"use client"

import React from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/UI/Card"
import { Button } from "@/components/UI/Button"
import { FileText, ExternalLink, Edit } from "lucide-react"
import { useNavigate } from "react-router-dom"

interface DocumentCardProps {
  documentId: string
  title: string
  preview?: string
  caseId: string
  onOpen?: () => void
}

export const DocumentCard: React.FC<DocumentCardProps> = ({
  documentId,
  title,
  preview,
  caseId,
  onOpen,
}) => {
  const navigate = useNavigate()

  const handleOpen = () => {
    if (onOpen) {
      onOpen()
    } else {
      navigate(`/cases/${caseId}/editor/${documentId}`)
    }
  }

  // Удаляем HTML теги из превью для отображения
  const cleanPreview = preview
    ? preview.replace(/<[^>]*>/g, '').trim()
    : ''

  return (
    <Card className="w-full max-w-2xl border border-[#E5E7EB] hover:border-[#2563EB] transition-colors cursor-pointer" onClick={handleOpen}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-[#2563EB]" />
            <CardTitle className="text-base font-semibold text-[#1F2937]">
              {title}
            </CardTitle>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              handleOpen()
            }}
            className="text-[#2563EB] hover:text-[#1D4ED8] hover:bg-[#EFF6FF]"
          >
            <Edit className="w-4 h-4 mr-1" />
            Открыть в редакторе
          </Button>
        </div>
      </CardHeader>
      
      {cleanPreview && (
        <CardContent className="pt-0">
          <div className="bg-[#F9FAFB] border border-[#E5E7EB] rounded-lg p-3">
            <p className="text-sm text-[#6B7280] line-clamp-3">
              {cleanPreview}
              {cleanPreview.length >= 150 && '...'}
            </p>
          </div>
        </CardContent>
      )}
    </Card>
  )
}

