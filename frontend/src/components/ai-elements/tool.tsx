import * as React from "react"
import { cn } from "@/lib/utils"
import { Zap, CheckCircle2, Clock, AlertCircle, Loader2, ChevronDown, ChevronRight } from "lucide-react"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/UI/collapsible"
import { Card, CardContent, CardHeader } from "@/components/UI/card"
import { Badge } from "@/components/UI/badge"

// Animation styles
const fadeIn = "animate-in fade-in slide-in-from-left-2 duration-300"

export interface ToolProps {
  name: string
  status?: "pending" | "running" | "completed" | "error"
  children?: React.ReactNode
  className?: string
}

export const Tool = React.memo(function Tool({ 
  name, 
  status = "completed",
  children,
  className 
}: ToolProps) {
  const [isOpen, setIsOpen] = React.useState(false)
  
  const statusIcons = {
    pending: <Clock className="w-4 h-4 text-gray-400" />,
    running: <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />,
    completed: <CheckCircle2 className="w-4 h-4 text-green-600" />,
    error: <AlertCircle className="w-4 h-4 text-red-600" />
  }

  const statusColors = {
    pending: "border-gray-200 bg-gray-50",
    running: "border-blue-200 bg-blue-50",
    completed: "border-green-200 bg-green-50",
    error: "border-red-200 bg-red-50"
  }

  const statusLabels = {
    pending: "Ожидает",
    running: "Выполняется",
    completed: "Завершено",
    error: "Ошибка"
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <Card className={cn("border transition-all", fadeIn, statusColors[status], className)}>
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer hover:bg-opacity-80 transition-colors">
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-yellow-600" />
              <span className="text-sm font-semibold">{name}</span>
              <Badge variant="outline" className="ml-auto">
                {statusLabels[status]}
              </Badge>
              {statusIcons[status]}
              {children && (
                isOpen ? (
                  <ChevronDown className="w-4 h-4 ml-2 text-gray-500" />
                ) : (
                  <ChevronRight className="w-4 h-4 ml-2 text-gray-500" />
                )
              )}
            </div>
          </CardHeader>
        </CollapsibleTrigger>
        {children && (
          <CollapsibleContent>
            <CardContent className="pt-0">
              {children}
            </CardContent>
          </CollapsibleContent>
        )}
      </Card>
    </Collapsible>
  )
})

export interface ToolInputProps {
  children: React.ReactNode
  className?: string
}

export function ToolInput({ children, className }: ToolInputProps) {
  return (
    <div className={cn("space-y-2", className)}>
      <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
        Входные данные
      </div>
      <pre className="text-xs bg-gray-50 p-3 rounded border border-gray-200 overflow-x-auto">
        {typeof children === 'string' ? children : JSON.stringify(children, null, 2)}
      </pre>
    </div>
  )
}

export interface ToolOutputProps {
  children: React.ReactNode
  className?: string
}

export function ToolOutput({ children, className }: ToolOutputProps) {
  return (
    <div className={cn("space-y-2 mt-3", className)}>
      <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
        Результат
      </div>
      <pre className="text-xs bg-gray-50 p-3 rounded border border-gray-200 overflow-x-auto">
        {typeof children === 'string' ? children : JSON.stringify(children, null, 2)}
      </pre>
    </div>
  )
}

