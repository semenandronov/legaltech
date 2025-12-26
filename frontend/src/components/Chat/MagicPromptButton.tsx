import React, { useState } from 'react'
import { Button } from '@/components/UI/Button'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/UI/popover'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/UI/tooltip'
import { Badge } from '@/components/UI/Badge'
import { Separator } from '@/components/UI/separator'
import { Sparkles, Check, X, Loader2, Lightbulb, ArrowRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'
import api from '@/services/api'

interface MagicPromptButtonProps {
  prompt: string
  onImprovedPrompt: (improved: string) => void
  disabled?: boolean
  className?: string
}

interface ImprovementResult {
  improved_prompt: string
  suggestions: string[]
  reasoning: string
  improvements_made: string[]
}

export function MagicPromptButton({
  prompt,
  onImprovedPrompt,
  disabled = false,
  className,
}: MagicPromptButtonProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [result, setResult] = useState<ImprovementResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleImprove = async () => {
    if (!prompt.trim() || isLoading) return

    setIsLoading(true)
    setError(null)
    setResult(null)

    try {
      const response = await api.post('/chat/improve-prompt', {
        prompt: prompt,
      })
      setResult(response.data)
    } catch (err: any) {
      console.error('Error improving prompt:', err)
      setError(err.response?.data?.detail || 'Ошибка улучшения запроса')
    } finally {
      setIsLoading(false)
    }
  }

  const handleAccept = () => {
    if (result?.improved_prompt) {
      onImprovedPrompt(result.improved_prompt)
      setIsOpen(false)
      setResult(null)
    }
  }

  const handleReject = () => {
    setIsOpen(false)
    setResult(null)
  }

  const isDisabled = disabled || !prompt.trim()

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              disabled={isDisabled}
              className={cn(
                "transition-all",
                !isDisabled && "hover:bg-primary/10 hover:text-primary",
                className
              )}
              onClick={() => {
                if (!isOpen) handleImprove()
              }}
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent side="top">
          <p>Улучшить запрос</p>
        </TooltipContent>
      </Tooltip>

      <PopoverContent className="w-96 p-0" align="end" side="top">
        <AnimatePresence mode="wait">
          {isLoading ? (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="p-6 text-center"
            >
              <Loader2 className="h-8 w-8 animate-spin mx-auto mb-3 text-primary" />
              <p className="text-sm text-muted-foreground">
                Анализируем и улучшаем запрос...
              </p>
            </motion.div>
          ) : error ? (
            <motion.div
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="p-6 text-center"
            >
              <X className="h-8 w-8 mx-auto mb-3 text-destructive" />
              <p className="text-sm text-destructive mb-4">{error}</p>
              <Button variant="outline" size="sm" onClick={() => setError(null)}>
                Попробовать снова
              </Button>
            </motion.div>
          ) : result ? (
            <motion.div
              key="result"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            >
              {/* Header */}
              <div className="p-4 border-b bg-gradient-to-r from-primary/5 to-transparent">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-primary" />
                  <h4 className="font-semibold">Улучшенный запрос</h4>
                </div>
              </div>

              {/* Original vs Improved */}
              <div className="p-4 space-y-3">
                {/* Original */}
                <div className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground">
                    Исходный запрос
                  </span>
                  <div className="bg-muted/50 rounded-md p-2 text-sm line-clamp-2">
                    {prompt}
                  </div>
                </div>

                <div className="flex justify-center">
                  <ArrowRight className="h-4 w-4 text-muted-foreground" />
                </div>

                {/* Improved */}
                <div className="space-y-1">
                  <span className="text-xs font-medium text-primary">
                    Улучшенный запрос
                  </span>
                  <div className="bg-primary/5 border border-primary/20 rounded-md p-2 text-sm">
                    {result.improved_prompt}
                  </div>
                </div>

                {/* Improvements made */}
                {result.improvements_made.length > 0 && (
                  <div className="space-y-1">
                    <span className="text-xs font-medium text-muted-foreground">
                      Что изменилось
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {result.improvements_made.map((imp, idx) => (
                        <Badge key={idx} variant="secondary" className="text-xs">
                          {imp}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Suggestions */}
                {result.suggestions.length > 0 && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
                        <Lightbulb className="h-3 w-3" />
                        Рекомендации
                      </div>
                      <ul className="text-xs text-muted-foreground space-y-1">
                        {result.suggestions.map((sug, idx) => (
                          <li key={idx} className="flex items-start gap-1">
                            <span className="text-primary">•</span>
                            {sug}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </>
                )}
              </div>

              {/* Actions */}
              <div className="p-3 border-t bg-muted/30 flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1"
                  onClick={handleReject}
                >
                  <X className="mr-1 h-3 w-3" />
                  Отменить
                </Button>
                <Button
                  size="sm"
                  className="flex-1"
                  onClick={handleAccept}
                >
                  <Check className="mr-1 h-3 w-3" />
                  Применить
                </Button>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </PopoverContent>
    </Popover>
  )
}

export default MagicPromptButton

