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
import { tabularReviewApi, TableData } from "@/services/tabularReviewApi"
import { toast } from "sonner"
import { Loader } from "@/components/ai-elements/loader"
import { 
  MessageSquare
} from "lucide-react"

interface TabularReviewContextChatProps {
  reviewId: string
  reviewName: string
  tableData: TableData | null
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  citations?: Array<{ file: string; file_id: string }>
}

export const TabularReviewContextChat: React.FC<TabularReviewContextChatProps> = ({
  reviewId,
  reviewName,
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
      const response = await tabularReviewApi.chatOverTable(reviewId, text.trim())
      
      const assistantMessage: Message = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: response.answer,
        citations: response.citations,
      }

      setMessages((prev) => [...prev, assistantMessage])
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
  }, [reviewId, isLoading])

  const handleSubmit = useCallback(async ({ text }: { text: string; files: any[] }) => {
    await handleSend(text)
  }, [handleSend])


  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[#E5E7EB] bg-[#F9FAFB]">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-[#6B7280]" />
          <h3 className="font-semibold text-sm text-[#1F2937]">Context</h3>
        </div>
        <p className="text-xs text-[#6B7280] mt-1">{reviewName}</p>
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
                    Задайте вопрос о таблице или используйте подсказку
                  </p>
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
                <AssistantMessage
                  key={message.id}
                  content={message.content}
                  sources={message.citations?.map((c) => ({
                    title: c.file,
                    url: `#file-${c.file_id}`,
                  }))}
                />
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
                placeholder="Введите вопрос или используйте подсказку"
                className="min-h-[60px] max-h-[120px] resize-none border-[#E5E7EB] focus:border-[#2563EB] focus:ring-[#2563EB]"
              />
            </PromptInputBody>
            <PromptInputFooter>
              <div className="flex items-center justify-end w-full">
                <PromptInputSubmit
                  status={isLoading ? "submitted" : undefined}
                  className="h-8 w-8 bg-[#2563EB] hover:bg-[#1D4ED8] text-white border-0"
                />
              </div>
            </PromptInputFooter>
          </PromptInput>
        </div>
      </PromptInputProvider>
    </div>
  )
}

