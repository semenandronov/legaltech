"use client"

import React, { useState, useCallback, useEffect, useRef } from "react"
import { UserMessage, AssistantMessage } from "@/components/ai-elements/message"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { toast } from "sonner"
import { Loader } from "@/components/ai-elements/loader"
import { ArrowRight, MessageSquare, Sparkles } from "lucide-react"

interface TabularReviewContextChatProps {
  reviewId: string
  reviewName: string
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  citations?: Array<{ file: string; file_id: string }>
  isStreaming?: boolean
}

const SUGGESTED_PROMPTS = [
  "Какие документы без даты в таблице?",
  "Покажи только договоры",
  "Какие суммы требований самые крупные?",
  "Есть ли противоречия между документами?",
]

export const TabularReviewContextChat: React.FC<TabularReviewContextChatProps> = ({
  reviewId,
  reviewName,
}) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(true)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const hasMessages = messages.length > 0
  const isStreaming = messages.some((m) => m.isStreaming)

  useEffect(() => {
    let cancelled = false
    setLoadingHistory(true)
    tabularReviewApi
      .getTabularChatHistory(reviewId)
      .then((data) => {
        if (cancelled) return
        setMessages(
          (data.messages || []).map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            citations: m.citations,
          })),
        )
      })
      .catch(() => {
        if (!cancelled) setMessages([])
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false)
      })
    return () => {
      cancelled = true
    }
  }, [reviewId])

  useEffect(() => {
    const el = scrollContainerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages])

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const handleSend = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || isLoading) return

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      setInputValue("")
      const userMessage: Message = {
        id: `user-${Date.now()}`,
        role: "user",
        content: trimmed,
      }
      const assistantId = `assistant-${Date.now()}`
      const assistantPlaceholder: Message = {
        id: assistantId,
        role: "assistant",
        content: "",
        isStreaming: true,
      }

      setMessages((prev) => [...prev, userMessage, assistantPlaceholder])
      setIsLoading(true)

      try {
        await tabularReviewApi.chatOverTableStream(
          reviewId,
          trimmed,
          {
            onTextDelta: (delta) => {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: m.content + delta } : m,
                ),
              )
            },
            onDone: ({ answer, citations }) => {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: answer, citations, isStreaming: false }
                    : m,
                ),
              )
            },
          },
          controller.signal,
        )
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return
        const message = err instanceof Error ? err.message : "Не удалось получить ответ"
        toast.error("Ошибка: " + message)
        setMessages((prev) => {
          const hasPlaceholder = prev.some((m) => m.id === assistantId)
          if (hasPlaceholder) {
            return prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: "Извините, произошла ошибка при обработке запроса.",
                    isStreaming: false,
                  }
                : m,
            )
          }
          return [
            ...prev,
            {
              id: `assistant-error-${Date.now()}`,
              role: "assistant",
              content: "Извините, произошла ошибка при обработке запроса.",
            },
          ]
        })
      } finally {
        setIsLoading(false)
        if (abortRef.current === controller) {
          abortRef.current = null
        }
      }
    },
    [reviewId, isLoading],
  )

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void handleSend(inputValue)
    }
  }

  const promptChipClass =
    "text-xs px-3 py-1.5 rounded-full border transition-colors disabled:opacity-50 text-left"

  return (
    <div
      className="flex flex-col h-full min-h-0"
      style={{ backgroundColor: "var(--color-bg-elevated)" }}
    >
      {/* Header */}
      <div
        className="px-4 pt-4 pb-3 border-b shrink-0"
        style={{ borderColor: "var(--color-border)", minHeight: "54px" }}
      >
        <div className="flex items-center justify-between gap-2">
          <span
            className="text-xs font-semibold uppercase tracking-wider shrink-0"
            style={{ color: "var(--color-text-muted)" }}
          >
            Чат по таблице
          </span>
          <span
            className="text-xs truncate max-w-[160px] text-right"
            style={{ color: "var(--color-text-muted)" }}
            title={reviewName}
          >
            {reviewName}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollContainerRef}
        className={`flex-1 min-h-0 overflow-y-auto overscroll-contain px-3 py-3 ${
          hasMessages ? "space-y-4" : "flex flex-col"
        }`}
      >
        {loadingHistory ? (
          <div className="flex justify-center py-10">
            <Loader />
          </div>
        ) : !hasMessages ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 px-2 py-6 text-center">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center"
              style={{ backgroundColor: "var(--color-bg-primary)" }}
            >
              <MessageSquare className="w-5 h-5" style={{ color: "var(--color-text-muted)" }} />
            </div>
            <div>
              <p className="text-sm font-medium" style={{ color: "var(--color-text-primary)" }}>
                Вопросы по данным таблицы
              </p>
              <p className="text-xs mt-1 leading-relaxed" style={{ color: "var(--color-text-muted)" }}>
                Ответы строятся только по заполненным ячейкам — без доступа к полным текстам документов.
              </p>
            </div>
            <div className="w-full space-y-2">
              <p
                className="text-xs font-semibold uppercase tracking-wider text-left"
                style={{ color: "var(--color-text-muted)" }}
              >
                Подсказки
              </p>
              <div className="flex flex-col gap-1.5">
                {SUGGESTED_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    disabled={isLoading}
                    onClick={() => void handleSend(prompt)}
                    className="w-full text-left px-3 py-2 rounded-lg text-xs transition-colors border"
                    style={{
                      borderColor: "var(--color-border)",
                      color: "var(--color-text-secondary)",
                      backgroundColor: "var(--color-bg-primary)",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = "var(--color-bg-hover)"
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = "var(--color-bg-primary)"
                    }}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <>
            {messages.map((message) => {
              if (message.role === "user") {
                return <UserMessage key={message.id} content={message.content} />
              }
              if (message.isStreaming && !message.content.trim()) {
                return (
                  <div
                    key={message.id}
                    className="flex items-center gap-2 text-sm py-1"
                    style={{ color: "var(--color-text-muted)" }}
                  >
                    <Loader />
                    <span>Формирую ответ…</span>
                  </div>
                )
              }
              return (
                <div key={message.id} className="tabular-chat-assistant-msg min-w-0 overflow-x-auto">
                  <AssistantMessage
                    content={message.content}
                    preferLegacyCitations
                    isStreaming={Boolean(message.isStreaming)}
                    sources={message.citations?.map((c) => ({
                      title: c.file,
                      file: c.file,
                      url: `#file-${c.file_id}`,
                    }))}
                  />
                </div>
              )
            })}
            {isLoading && !isStreaming && (
              <div className="flex items-center gap-2 text-sm" style={{ color: "var(--color-text-muted)" }}>
                <Loader />
                <span>Анализирую таблицу…</span>
              </div>
            )}
          </>
        )}
      </div>

      {/* Input */}
      <div className="shrink-0 border-t px-3 pt-3 pb-3" style={{ borderColor: "var(--color-border)" }}>
        {hasMessages && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {SUGGESTED_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                disabled={isLoading || loadingHistory}
                onClick={() => void handleSend(prompt)}
                className={promptChipClass}
                style={{
                  borderColor: "var(--color-border)",
                  color: "var(--color-text-secondary)",
                  backgroundColor: "var(--color-bg-primary)",
                }}
              >
                {prompt}
              </button>
            ))}
          </div>
        )}

        <div
          className="rounded-2xl border overflow-hidden transition-shadow focus-within:shadow-sm"
          style={{
            borderColor: "var(--color-border)",
            backgroundColor: "var(--color-bg-primary)",
          }}
        >
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Спросите о данных в таблице…"
            disabled={isLoading || loadingHistory}
            rows={hasMessages ? 2 : 3}
            className="w-full px-4 pt-3 pb-2 text-sm resize-none outline-none bg-transparent placeholder:opacity-70"
            style={{ color: "var(--color-text-primary)" }}
          />
          <div className="flex items-center justify-between px-3 pb-2.5">
            <div className="flex items-center gap-1.5 text-xs" style={{ color: "var(--color-text-muted)" }}>
              <Sparkles className="w-3.5 h-3.5" />
              <span>Только ячейки таблицы</span>
            </div>
            <button
              type="button"
              onClick={() => void handleSend(inputValue)}
              disabled={isLoading || loadingHistory || !inputValue.trim()}
              className="w-8 h-8 flex items-center justify-center rounded-xl transition-all disabled:opacity-30"
              style={{
                backgroundColor:
                  inputValue.trim() && !isLoading ? "var(--color-text-primary)" : "var(--color-border)",
                color:
                  inputValue.trim() && !isLoading
                    ? "var(--color-bg-primary)"
                    : "var(--color-text-muted)",
              }}
              aria-label="Отправить"
            >
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
