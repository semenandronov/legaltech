import React from 'react'
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/UI/resizable'

interface SplitViewLayoutProps {
  leftPanel: React.ReactNode
  rightPanel: React.ReactNode
  defaultSizes?: [number, number] // [left, right] percentages
  minSizes?: [number, number]
  maxSizes?: [number, number]
  className?: string
}

/**
 * Split View Layout компонент для отображения чата и документа рядом
 * 
 * Поддерживает:
 * - Резизирование панелей через react-resizable-panels
 * - Клик по citation для открытия документа
 * - Минимальные/максимальные размеры панелей
 */
export const SplitViewLayout: React.FC<SplitViewLayoutProps> = ({
  leftPanel,
  rightPanel,
  defaultSizes = [50, 50],
  minSizes = [30, 30],
  maxSizes = [70, 70],
  className = ''
}) => {
  return (
    <ResizablePanelGroup 
      className={`split-view-layout h-full ${className}`}
    >
      {/* Левая панель (чат) */}
      <ResizablePanel 
        defaultSize={defaultSizes[0]}
        minSize={minSizes[0]}
        maxSize={maxSizes[0]}
        className="split-view-left"
      >
        <div className="h-full overflow-auto">
          {leftPanel}
        </div>
      </ResizablePanel>

      {/* Разделитель */}
      <ResizableHandle withHandle />

      {/* Правая панель (документ) */}
      <ResizablePanel 
        defaultSize={defaultSizes[1]}
        minSize={minSizes[1]}
        maxSize={maxSizes[1]}
        className="split-view-right"
      >
        <div className="h-full overflow-auto">
          {rightPanel}
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}

export default SplitViewLayout

