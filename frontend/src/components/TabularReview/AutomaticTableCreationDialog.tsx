import React, { useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/UI/dialog"
import { Button } from "@/components/UI/Button"
import Input from "@/components/UI/Input"
import Spinner from "@/components/UI/Spinner"
import { tabularReviewApi, type CreateFromDescriptionResponse } from "@/services/tabularReviewApi"

interface Message {
  from: "user" | "agent"
  text: string
}

interface AutomaticTableCreationDialogProps {
  isOpen: boolean
  onClose: () => void
  caseId: string
  onTableCreated: (reviewId: string) => void
}

export const AutomaticTableCreationDialog: React.FC<AutomaticTableCreationDialogProps> = ({
  isOpen,
  onClose,
  caseId,
  onTableCreated,
}) => {
  const [messages, setMessages] = useState<Message[]>([
    {
      from: "agent",
      text: "Опишите, какую таблицу вы хотите получить (какие документы, какие колонки, какая задача анализа).",
    },
  ])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [reviewId, setReviewId] = useState<string | null>(null)

  const appendMessage = (msg: Message) => {
    setMessages(prev => [...prev, msg])
  }

  const handleResponse = (resp: CreateFromDescriptionResponse) => {
    if (resp.status === "needs_clarification" && resp.clarificationQuestions?.length) {
      appendMessage({
        from: "agent",
        text:
          "Нужно уточнить:\n" +
          resp.clarificationQuestions.map((q, i) => `${i + 1}. ${q}`).join("\n"),
      })
      if (resp.review_id) setReviewId(resp.review_id)
      return
    }

    if (resp.status === "ok" && resp.review_id) {
      appendMessage({
        from: "agent",
        text: resp.message || "Таблица создана. Открываю её.",
      })
      // Небольшая задержка перед закрытием, чтобы пользователь увидел сообщение
      setTimeout(() => {
        onTableCreated(resp.review_id!)
        onClose()
        // Сброс состояния после закрытия
        setMessages([{
          from: "agent",
          text: "Опишите, какую таблицу вы хотите получить (какие документы, какие колонки, какая задача анализа).",
        }])
        setInput("")
        setReviewId(null)
      }, 1000)
      return
    }

    appendMessage({
      from: "agent",
      text: resp.message || "Не удалось создать таблицу. Попробуйте уточнить задачу.",
    })
  }

  const send = async () => {
    if (!input.trim() || loading) return
    const text = input.trim()
    setInput("")

    appendMessage({ from: "user", text })
    setLoading(true)
    try {
      const resp = await tabularReviewApi.createFromDescription(caseId, {
        description: text,
        existing_review_id: reviewId,
      })
      handleResponse(resp)
    } catch (e: any) {
      appendMessage({
        from: "agent",
        text: "Ошибка при работе агента: " + (e?.message || "неизвестная ошибка"),
      })
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    if (loading) return // Не позволяем закрыть во время загрузки
    onClose()
    // Сброс состояния при закрытии
    setMessages([{
      from: "agent",
      text: "Опишите, какую таблицу вы хотите получить (какие документы, какие колонки, какая задача анализа).",
    }])
    setInput("")
    setReviewId(null)
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="max-w-3xl h-[700px] flex flex-col">
        <DialogHeader>
          <DialogTitle>Автоматическое создание таблицы</DialogTitle>
        </DialogHeader>

        {/* Область чата с прокруткой */}
        <div className="flex-1 overflow-y-auto space-y-2 p-4 min-h-0">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`max-w-xl px-3 py-2 rounded-lg text-sm whitespace-pre-wrap ${
                m.from === "user"
                  ? "ml-auto bg-accent text-bg-primary"
                  : "mr-auto bg-muted text-text-primary"
              }`}
            >
              {m.text}
            </div>
          ))}
          {loading && (
            <div className="flex items-center gap-2 text-sm text-text-secondary mt-2">
              <Spinner size="sm" />
              <span>Агент думает…</span>
            </div>
          )}
        </div>

        {/* Область ввода внизу */}
        <div className="p-3 border-t border-border bg-bg-primary/60">
          <div className="flex gap-2">
            <Input
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Опишите желаемую таблицу или ответьте на вопрос агента..."
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              disabled={loading}
            />
            <Button onClick={send} disabled={loading || !input.trim()}>
              Отправить
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

