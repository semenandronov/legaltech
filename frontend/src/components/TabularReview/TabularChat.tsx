import React, { useState, useRef, useEffect } from "react"
import { Button } from "@/components/UI/Button"
import { Textarea } from "@/components/UI/Textarea"
import { Card, CardContent } from "@/components/UI/Card"
import { ScrollArea } from "@/components/UI/scroll-area"
import { Send, MessageSquare } from "lucide-react"
import { tabularReviewApi, TableData } from "@/services/tabularReviewApi"
import { toast } from "sonner"
import Spinner from "@/components/UI/Spinner"
import { Badge } from "@/components/UI/Badge"

interface Message {
  role: "user" | "assistant"
  content: string
  citations?: Array<{ file: string; file_id: string }>
}

interface TabularChatProps {
  reviewId: string
  caseId: string
  tableData: TableData | null
  onDocumentClick?: (fileId: string) => void
}

export const TabularChat: React.FC<TabularChatProps> = ({
  reviewId,
  caseId: _caseId,
  tableData,
  onDocumentClick,
}) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState("")
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  const handleSend = async () => {
    if (!inputValue.trim() || loading) return

    const userMessage: Message = {
      role: "user",
      content: inputValue.trim(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInputValue("")
    setLoading(true)

    try {
      const response = await tabularReviewApi.chatOverTable(reviewId, inputValue.trim())
      
      const assistantMessage: Message = {
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
          role: "assistant",
          content: "Извините, произошла ошибка при обработке запроса.",
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full border-r bg-background">
      {/* Header */}
      <div className="border-b p-3 bg-muted/30">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4" />
          <span className="font-medium text-sm">Ассистент по таблице</span>
        </div>
        {tableData && (
          <div className="text-xs text-muted-foreground mt-1">
            {tableData.rows.length} документов, {tableData.columns.length} колонок
          </div>
        )}
      </div>

      {/* Messages */}
      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-muted-foreground text-sm py-8">
              <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>Задайте вопрос о данных в таблице</p>
              <p className="text-xs mt-2">Например: "Какая максимальная сумма в контрактах?"</p>
            </div>
          )}

          {messages.map((message, index) => (
            <div
              key={index}
              className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <Card
                className={`max-w-[85%] ${
                  message.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted"
                }`}
              >
                <CardContent className="p-3">
                  <div className="text-sm whitespace-pre-wrap">{message.content}</div>
                  
                  {message.citations && message.citations.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-border/50">
                      <div className="text-xs font-medium mb-1">Источники:</div>
                      <div className="flex flex-wrap gap-1">
                        {message.citations.map((citation, idx) => (
                          <Badge
                            key={idx}
                            variant="secondary"
                            className="cursor-pointer text-xs"
                            onClick={() => onDocumentClick?.(citation.file_id)}
                          >
                            {citation.file}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <Card className="bg-muted">
                <CardContent className="p-3">
                  <div className="flex items-center gap-2">
                    <Spinner size="sm" />
                    <span className="text-sm text-muted-foreground">Анализирую таблицу...</span>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>

      {/* Input */}
      <div className="border-t p-3">
        <div className="flex gap-2">
          <Textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Задайте вопрос о таблице..."
            className="min-h-[60px] max-h-[120px] resize-none"
            disabled={loading}
          />
          <Button
            onClick={handleSend}
            disabled={!inputValue.trim() || loading}
            size="icon"
            className="shrink-0"
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}

