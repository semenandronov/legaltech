"use client"

import React, { useState, useCallback, useEffect, useRef } from "react"
import { AssistantMessage } from "@/components/ai-elements/message"
import { operationsApi, type OperationsSessionUiState } from "@/services/operationsApi"
import { toast } from "sonner"
import { Loader } from "@/components/ai-elements/loader"
import { ArrowRight, ChevronLeft, MessageSquare, Square } from "lucide-react"

interface OperationsContextChatProps {
  caseId: string
  fileId: string
  reviewName: string
  uiState: OperationsSessionUiState
  onClose?: () => void
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  citations?: Array<{ file: string; file_id: string }>
  isStreaming?: boolean
}

const SUGGESTED_PROMPTS = [
  "Какие списания больше 500 000 ₽?",
  "Покажи операции за последний год",
  "Кто основные контрагенты по сумме?",
  "Есть ли повторяющиеся платежи одному получателю?",
]

export const OperationsContextChat: React.FC<OperationsContextChatProps> = ({
  caseId,
  fileId,
  reviewName,
  uiState,
  onClose,
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
    operationsApi
      .getChatHistory(caseId, fileId)
      .then((data) => {
        if (cancelled) return
        setMessages(
          data.map((m) => ({
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
  }, [caseId, fileId])

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
      if (!trimmed || isLoading || !fileId) return

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
        await operationsApi.chatStream(
          caseId,
          trimmed,
          fileId,
          uiState,
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
    [caseId, fileId, isLoading, uiState],
  )

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 192)}px`
    el.style.overflowY = el.scrollHeight > 192 ? "auto" : "hidden"
  }, [inputValue])

  const handleCancel = useCallback(() => {
    abortRef.current?.abort()
    setIsLoading(false)
    setMessages((prev) =>
      prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m)),
    )
  }, [])

  const handleInputAction = useCallback(() => {
    if (isLoading) {
      handleCancel()
      return
    }
    void handleSend(inputValue)
  }, [handleCancel, handleSend, inputValue, isLoading])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleInputAction()
    }
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value)
    const el = e.target
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 192)}px`
    el.style.overflowY = el.scrollHeight > 192 ? "auto" : "hidden"
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="ws-tabular-chat-header">
        <div className="flex items-center gap-1 min-w-0">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="ws-tabular-chat-header-btn"
              title="Закрыть ассистента"
              aria-label="Закрыть ассистента"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
          )}
          <span className="ws-tabular-chat-title truncate">{reviewName}</span>
        </div>
      </div>

      <div
        ref={scrollContainerRef}
        className={`flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 pt-4 ${
          hasMessages ? "space-y-4" : "flex flex-col"
        }`}
      >
        {loadingHistory ? (
          <div className="flex justify-center py-10">
            <Loader />
          </div>
        ) : !hasMessages ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 py-8 text-center">
            <div className="ws-tabular-chat-empty-icon" aria-hidden>
              <MessageSquare className="w-6 h-6 text-gray-300" />
            </div>
            <p className="text-gray-400 font-serif text-sm leading-relaxed max-w-[240px]">
              Задайте вопрос по операциям в этой выписке
            </p>
            <div className="w-full max-w-[280px] space-y-1.5 mt-2">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  disabled={isLoading}
                  onClick={() => void handleSend(prompt)}
                  className="ws-tabular-chat-suggestion-btn"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((message) => {
              if (message.role === "user") {
                return (
                  <div key={message.id} className="flex justify-end">
                    <div className="ws-tabular-chat-user-bubble">{message.content}</div>
                  </div>
                )
              }
              if (message.isStreaming && !message.content.trim()) {
                return (
                  <div
                    key={message.id}
                    className="flex items-center gap-2 text-xs py-1"
                    style={{ color: "var(--color-text-muted)" }}
                  >
                    <Loader />
                    <span>Формирую ответ…</span>
                  </div>
                )
              }
              return (
                <div key={message.id} className="tabular-chat-assistant-msg min-w-0 overflow-x-auto text-sm">
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
              <div className="flex items-center gap-2 text-xs" style={{ color: "var(--color-text-muted)" }}>
                <Loader />
                <span>Анализирую выписку…</span>
              </div>
            )}
          </>
        )}
      </div>

      <div className="shrink-0 px-3 pb-3 pt-2">
        <div className="ws-tabular-chat-input-glass">
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={handleTextareaChange}
            onKeyDown={handleKeyDown}
            placeholder="Спросите о операциях в выписке…"
            disabled={loadingHistory || !fileId}
            rows={1}
            className="w-full resize-none border-0 bg-transparent px-3 pt-2 pb-1 text-sm leading-6 outline-none placeholder:text-gray-400 max-h-48 overflow-hidden"
          />
          <div className="flex items-center justify-end px-2 pb-1.5">
            <button
              type="button"
              onClick={handleInputAction}
              disabled={loadingHistory || !fileId || (!isLoading && !inputValue.trim())}
              className="ws-tabular-chat-send"
              aria-label={isLoading ? "Остановить" : "Отправить"}
            >
              {isLoading ? (
                <Square className="h-3.5 w-3.5" fill="currentColor" strokeWidth={0} />
              ) : (
                <ArrowRight className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
