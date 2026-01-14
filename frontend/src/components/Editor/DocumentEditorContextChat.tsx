"use client"

import React, { useState, useCallback } from "react"
import { Conversation, ConversationContent, ConversationEmptyState } from "@/components/ai-elements/conversation"
import { UserMessage, AssistantMessage } from "@/components/ai-elements/message"
import {
  PromptInputProvider,
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputSubmit,
  PromptInputFooter,
} from "@/components/ai-elements/prompt-input"
import { chatOverDocument } from "@/services/documentEditorApi"
import { toast } from "sonner"
import { Loader } from "@/components/ai-elements/loader"
import { MessageSquare, Check } from "lucide-react"
import { Button } from "@/components/UI/Button"

interface DocumentEditorContextChatProps {
  documentId: string
  documentTitle: string
  onApplyEdit?: (text: string) => void
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  citations?: Array<{ file: string; file_id: string }>
  editedContent?: string
  suggestions?: string[]
}

export const DocumentEditorContextChat: React.FC<DocumentEditorContextChatProps> = ({
  documentId,
  documentTitle,
  onApplyEdit,
}) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const handleSend = useCallback(async (text: string) => {
    if (!text.trim() || isLoading) return

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text.trim(),
    }

    setMessages((prev) => [...prev, userMessage])
    setIsLoading(true)

    try {
      const response = await chatOverDocument(documentId, text.trim())
      
      const assistantMessage: Message = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: response.answer,
        citations: response.citations,
        editedContent: response.edited_content,
        suggestions: response.suggestions,
      }

      setMessages((prev) => [...prev, assistantMessage])

      // If there are suggestions to apply edits, notify parent
      if (response.suggestions.length > 0 && response.edited_content && onApplyEdit) {
        toast.info("ИИ предложил изменения. Используйте кнопку 'Применить' для вставки.")
      }
    } catch (err: any) {
      toast.error("Ошибка: " + (err.message || "Не удалось получить ответ"))
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-error-${Date.now()}`,
          role: "assistant",
          content: "Извините, произошла ошибка при обработке запроса.",
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }, [documentId, isLoading, onApplyEdit])

  const handleSubmit = useCallback(async ({ text }: { text: string; files: any[] }) => {
    await handleSend(text)
  }, [handleSend])

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[#E5E7EB] bg-[#F9FAFB]">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-[#6B7280]" />
          <h3 className="font-semibold text-sm text-[#1F2937]">AI Помощник</h3>
        </div>
        <p className="text-xs text-[#6B7280] mt-1">{documentTitle}</p>
      </div>

      {/* Messages Area */}
      <div className="flex-1 overflow-hidden">
        <Conversation>
          <ConversationContent>
            {messages.length === 0 && (
              <ConversationEmptyState
                title=""
                description=""
                icon={<MessageSquare className="w-8 h-8 text-[#9CA3AF]" />}
              >
                <div className="text-center space-y-2">
                  <p className="text-sm text-[#6B7280]">
                    Задайте вопрос о документе или попросите ИИ отредактировать его
                  </p>
                  <div className="text-xs text-[#9CA3AF] mt-2 space-y-1">
                    <p>Примеры запросов:</p>
                    <p>• "Проверь документ на риски"</p>
                    <p>• "Улучши формулировки"</p>
                    <p>• "Добавь пункт о штрафах"</p>
                  </div>
                </div>
              </ConversationEmptyState>
            )}

            {messages.map((message) => {
              if (message.role === "user") {
                return (
                  <UserMessage
                    key={message.id}
                    content={message.content}
                  />
                )
              }

              return (
                <div key={message.id}>
                  <AssistantMessage
                    content={message.content}
                    sources={message.citations?.map((c) => ({
                      title: c.file,
                      url: `#file-${c.file_id}`,
                    }))}
                  />
                  {message.editedContent && onApplyEdit && (
                    <div className="mt-2 mb-4 flex justify-start">
                      <Button
                        onClick={() => {
                          if (onApplyEdit && message.editedContent) {
                            onApplyEdit(message.editedContent)
                          }
                        }}
                        className="flex items-center gap-2 bg-blue-600 text-white hover:bg-blue-700"
                        size="sm"
                      >
                        <Check className="w-4 h-4" />
                        Применить изменения
                      </Button>
                    </div>
                  )}
                </div>
              )
            })}

            {isLoading && (
              <div className="flex justify-start">
                <div className="max-w-[75%] rounded-2xl px-4 py-3 bg-gray-100">
                  <Loader />
                </div>
              </div>
            )}
          </ConversationContent>
        </Conversation>
      </div>

      {/* Input Area */}
      <PromptInputProvider>
        <div className="border-t border-[#E5E7EB] bg-white p-4">
          <PromptInput onSubmit={handleSubmit}>
            <PromptInputBody>
              <PromptInputTextarea
                placeholder="Задайте вопрос или попросите отредактировать документ..."
                disabled={isLoading}
              />
            </PromptInputBody>
            <PromptInputFooter>
              <PromptInputSubmit disabled={isLoading} />
            </PromptInputFooter>
          </PromptInput>
        </div>
      </PromptInputProvider>
    </div>
  )
}

