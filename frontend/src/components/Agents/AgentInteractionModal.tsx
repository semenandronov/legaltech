import React, { useState, useEffect } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/UI/dialog'
import { Button } from '@/components/UI/Button'
import { Textarea } from '@/components/UI/textarea'
import { RadioGroup, RadioGroupItem } from '@/components/UI/radio-group'
import { Label } from '@/components/UI/label'
import { Badge } from '@/components/UI/Badge'
import { Card, CardContent } from '@/components/UI/card'
import { Bot, Clock, AlertCircle, CheckCircle2, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'

export interface AgentQuestion {
  request_id: string
  agent_name: string
  question_type: 'clarification' | 'confirmation' | 'choice'
  question_text: string
  options?: { id: string; label: string; description?: string }[]
  context?: string
}

interface AgentInteractionModalProps {
  question: AgentQuestion | null
  isOpen: boolean
  onClose: () => void
  onSubmit: (requestId: string, response: string) => void
  timeoutSeconds?: number
}

const AGENT_NAMES: Record<string, string> = {
  timeline: 'Хронология',
  key_facts: 'Ключевые факты',
  discrepancy: 'Противоречия',
  risk: 'Риски',
  summary: 'Резюме',
  entity_extraction: 'Извлечение сущностей',
  classification: 'Классификация',
  supervisor: 'Координатор',
}

const AGENT_COLORS: Record<string, string> = {
  timeline: 'bg-blue-500',
  key_facts: 'bg-green-500',
  discrepancy: 'bg-orange-500',
  risk: 'bg-red-500',
  summary: 'bg-purple-500',
  entity_extraction: 'bg-cyan-500',
  classification: 'bg-pink-500',
  supervisor: 'bg-indigo-500',
}

export function AgentInteractionModal({
  question,
  isOpen,
  onClose,
  onSubmit,
  timeoutSeconds = 300,
}: AgentInteractionModalProps) {
  const [response, setResponse] = useState('')
  const [selectedOption, setSelectedOption] = useState<string>('')
  const [timeLeft, setTimeLeft] = useState(timeoutSeconds)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Reset state when question changes
  useEffect(() => {
    if (question) {
      setResponse('')
      setSelectedOption('')
      setTimeLeft(timeoutSeconds)
      setIsSubmitting(false)
    }
  }, [question, timeoutSeconds])

  // Countdown timer
  useEffect(() => {
    if (!isOpen || timeLeft <= 0) return

    const timer = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          onClose()
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(timer)
  }, [isOpen, timeLeft, onClose])

  const handleSubmit = async () => {
    if (!question) return

    setIsSubmitting(true)
    
    let finalResponse = response
    if (question.question_type === 'choice' || question.question_type === 'confirmation') {
      finalResponse = selectedOption
    }

    try {
      await onSubmit(question.request_id, finalResponse)
      onClose()
    } finally {
      setIsSubmitting(false)
    }
  }

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const isValid = () => {
    if (question?.question_type === 'clarification') {
      return response.trim().length > 0
    }
    return selectedOption !== ''
  }

  if (!question) return null

  const agentName = AGENT_NAMES[question.agent_name] || question.agent_name
  const agentColor = AGENT_COLORS[question.agent_name] || 'bg-gray-500'

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <div className="flex items-center gap-3 mb-2">
            <div className={cn("p-2 rounded-full", agentColor)}>
              <Bot className="h-5 w-5 text-white" />
            </div>
            <div>
              <DialogTitle className="text-xl">Вопрос от агента</DialogTitle>
              <Badge variant="outline" className="mt-1">
                {agentName}
              </Badge>
            </div>
          </div>
          <DialogDescription className="sr-only">
            Агент запрашивает дополнительную информацию
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Timer */}
          <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
            <Clock className="h-4 w-4" />
            <span className={cn(timeLeft < 60 && "text-destructive font-medium")}>
              {formatTime(timeLeft)}
            </span>
          </div>

          {/* Question */}
          <Card>
            <CardContent className="pt-4">
              <p className="text-base leading-relaxed">{question.question_text}</p>
            </CardContent>
          </Card>

          {/* Context */}
          {question.context && (
            <div className="bg-muted/50 rounded-lg p-3 text-sm">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 mt-0.5 text-muted-foreground" />
                <div>
                  <p className="font-medium text-muted-foreground mb-1">Контекст</p>
                  <p className="text-muted-foreground">{question.context}</p>
                </div>
              </div>
            </div>
          )}

          {/* Response Input */}
          <AnimatePresence mode="wait">
            {question.question_type === 'clarification' && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
              >
                <Textarea
                  placeholder="Введите ваш ответ..."
                  value={response}
                  onChange={(e) => setResponse(e.target.value)}
                  className="min-h-[100px]"
                  autoFocus
                />
              </motion.div>
            )}

            {question.question_type === 'confirmation' && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="flex gap-3"
              >
                <Button
                  variant={selectedOption === 'yes' ? 'default' : 'outline'}
                  className="flex-1 h-14"
                  onClick={() => setSelectedOption('yes')}
                >
                  <CheckCircle2 className="mr-2 h-5 w-5" />
                  Да
                </Button>
                <Button
                  variant={selectedOption === 'no' ? 'destructive' : 'outline'}
                  className="flex-1 h-14"
                  onClick={() => setSelectedOption('no')}
                >
                  <XCircle className="mr-2 h-5 w-5" />
                  Нет
                </Button>
              </motion.div>
            )}

            {question.question_type === 'choice' && question.options && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
              >
                <RadioGroup
                  value={selectedOption}
                  onValueChange={setSelectedOption}
                  className="space-y-2"
                >
                  {question.options.map((option) => (
                    <div
                      key={option.id}
                      className={cn(
                        "flex items-start space-x-3 p-3 rounded-lg border cursor-pointer transition-colors",
                        selectedOption === option.id
                          ? "border-primary bg-primary/5"
                          : "border-border hover:bg-muted/50"
                      )}
                      onClick={() => setSelectedOption(option.id)}
                    >
                      <RadioGroupItem value={option.id} id={option.id} className="mt-0.5" />
                      <Label htmlFor={option.id} className="flex-1 cursor-pointer">
                        <div className="font-medium">{option.label}</div>
                        {option.description && (
                          <div className="text-sm text-muted-foreground mt-0.5">
                            {option.description}
                          </div>
                        )}
                      </Label>
                    </div>
                  ))}
                </RadioGroup>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Пропустить
          </Button>
          <Button onClick={handleSubmit} disabled={!isValid() || isSubmitting}>
            {isSubmitting ? 'Отправка...' : 'Отправить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default AgentInteractionModal

