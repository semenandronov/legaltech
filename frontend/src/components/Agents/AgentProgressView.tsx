import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/UI/card'
import { Badge } from '@/components/UI/Badge'
import { Progress } from '@/components/UI/progress'
import { ScrollArea } from '@/components/UI/scroll-area'
import { 
  Bot, 
  CheckCircle2, 
  XCircle, 
  Clock, 
  Loader2,
  AlertTriangle,
  ArrowRight,
  ChevronRight
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'

export interface PlanStep {
  step_id: string
  agent_name: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped'
  reasoning?: string
  error?: string
}

export interface AgentLog {
  id: string
  agent_name: string
  log_type: 'start' | 'progress' | 'result' | 'error' | 'decision'
  message: string
  timestamp: string
}

interface AgentProgressViewProps {
  steps: PlanStep[]
  logs?: AgentLog[]
  currentStepId?: string
  isRunning?: boolean
  className?: string
}

const AGENT_NAMES: Record<string, string> = {
  timeline: 'Хронология',
  key_facts: 'Ключевые факты',
  discrepancy: 'Противоречия',
  risk: 'Риски',
  summary: 'Резюме',
  entity_extraction: 'Сущности',
  classification: 'Классификация',
  supervisor: 'Координатор',
}

const STATUS_CONFIG = {
  pending: {
    icon: Clock,
    color: 'text-muted-foreground',
    bg: 'bg-muted',
    label: 'Ожидает',
  },
  in_progress: {
    icon: Loader2,
    color: 'text-blue-500',
    bg: 'bg-blue-500/10',
    label: 'Выполняется',
  },
  completed: {
    icon: CheckCircle2,
    color: 'text-green-500',
    bg: 'bg-green-500/10',
    label: 'Завершено',
  },
  failed: {
    icon: XCircle,
    color: 'text-red-500',
    bg: 'bg-red-500/10',
    label: 'Ошибка',
  },
  skipped: {
    icon: AlertTriangle,
    color: 'text-orange-500',
    bg: 'bg-orange-500/10',
    label: 'Пропущено',
  },
}

export function AgentProgressView({
  steps,
  logs = [],
  currentStepId,
  isRunning = false,
  className,
}: AgentProgressViewProps) {
  const completedCount = steps.filter(s => s.status === 'completed').length
  const totalCount = steps.length
  const progress = totalCount > 0 ? (completedCount / totalCount) * 100 : 0

  return (
    <Card className={cn("w-full", className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <Bot className="h-5 w-5" />
            Прогресс анализа
          </CardTitle>
          {isRunning && (
            <Badge variant="secondary" className="gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              Выполняется
            </Badge>
          )}
        </div>
        <div className="space-y-1">
          <div className="flex justify-between text-sm text-muted-foreground">
            <span>{completedCount} из {totalCount} шагов</span>
            <span>{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} className="h-2" />
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        <ScrollArea className="max-h-[400px]">
          <div className="space-y-2">
            <AnimatePresence>
              {steps.map((step, index) => {
                const config = STATUS_CONFIG[step.status]
                const Icon = config.icon
                const isActive = step.step_id === currentStepId
                const agentName = AGENT_NAMES[step.agent_name] || step.agent_name

                return (
                  <motion.div
                    key={step.step_id}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: index * 0.05 }}
                    className={cn(
                      "flex items-start gap-3 p-3 rounded-lg border transition-colors",
                      isActive && "border-primary bg-primary/5",
                      !isActive && config.bg
                    )}
                  >
                    <div className={cn(
                      "flex-shrink-0 mt-0.5",
                      config.color,
                      step.status === 'in_progress' && "animate-spin"
                    )}>
                      <Icon className="h-5 w-5" />
                    </div>
                    
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium">{agentName}</span>
                        <Badge variant="outline" className="text-xs">
                          {config.label}
                        </Badge>
                      </div>
                      <p className="text-sm text-muted-foreground mt-0.5 line-clamp-2">
                        {step.description}
                      </p>
                      {step.error && (
                        <p className="text-sm text-destructive mt-1">
                          {step.error}
                        </p>
                      )}
                      {step.reasoning && (
                        <p className="text-xs text-muted-foreground mt-1 italic">
                          {step.reasoning}
                        </p>
                      )}
                    </div>

                    {index < steps.length - 1 && (
                      <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                    )}
                  </motion.div>
                )
              })}
            </AnimatePresence>
          </div>

          {/* Logs section */}
          {logs.length > 0 && (
            <div className="mt-4 pt-4 border-t">
              <h4 className="text-sm font-medium mb-2 text-muted-foreground">
                Журнал выполнения
              </h4>
              <div className="space-y-1">
                {logs.slice(-10).map((log) => (
                  <div
                    key={log.id}
                    className="flex items-start gap-2 text-xs"
                  >
                    <span className="text-muted-foreground whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>
                    <Badge 
                      variant="outline" 
                      className="text-[10px] px-1 py-0"
                    >
                      {AGENT_NAMES[log.agent_name] || log.agent_name}
                    </Badge>
                    <span className={cn(
                      log.log_type === 'error' && 'text-destructive',
                      log.log_type === 'decision' && 'text-blue-500'
                    )}>
                      {log.message}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  )
}

export default AgentProgressView

