import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import './Chat.css'

interface QuickButtonsProps {
  onClassifyAll?: () => void
  onFindPrivilege?: () => void
  onTimeline?: () => void
  onStatistics?: () => void
  onExtractEntities?: () => void
}

const QuickButtons: React.FC<QuickButtonsProps> = ({
  onClassifyAll,
  onFindPrivilege,
  onTimeline,
  onStatistics,
  onExtractEntities
}) => {
  return (
    <TooltipProvider>
      <Card className="mx-6 mt-4 mb-2 border">
        <CardHeader className="pb-3">
          <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            📌 Quick Start:
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {onClassifyAll && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onClassifyAll}
                    aria-label="Классифицировать все документы"
                  >
                    [Classify All]
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Классифицировать все документы в деле</TooltipContent>
              </Tooltip>
            )}
            {onFindPrivilege && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onFindPrivilege}
                    aria-label="Найти привилегированные документы"
                  >
                    [Find Privilege]
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Найти все привилегированные документы</TooltipContent>
              </Tooltip>
            )}
            {onTimeline && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onTimeline}
                    aria-label="Показать таймлайн"
                  >
                    [Timeline]
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Показать таймлайн событий из документов</TooltipContent>
              </Tooltip>
            )}
            {onStatistics && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onStatistics}
                    aria-label="Показать статистику"
                  >
                    [Statistics]
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Показать статистику по делу</TooltipContent>
              </Tooltip>
            )}
            {onExtractEntities && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={onExtractEntities}
                    aria-label="Извлечь сущности"
                  >
                    [Extract Entities]
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Извлечь все сущности из документов</TooltipContent>
              </Tooltip>
            )}
          </div>
        </CardContent>
      </Card>
    </TooltipProvider>
  )
}

export default QuickButtons
