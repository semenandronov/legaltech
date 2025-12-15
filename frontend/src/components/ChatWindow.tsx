import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import './ChatWindow.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
}

interface ChatWindowProps {
  caseId: string
  fileNames: string[]
}

const ChatWindow = ({ caseId, fileNames }: ChatWindowProps) => {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadHistory()
  }, [caseId])

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const loadHistory = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/chat/${caseId}/history`)
      if (response.data.messages) {
        setMessages(
          response.data.messages.map((msg: any) => ({
            role: msg.role,
            content: msg.content,
            sources: msg.sources || [],
          }))
        )
      }
    } catch (err) {
      console.error('Ошибка при загрузке истории:', err)
    }
  }

  const handleSend = async () => {
    if (!inputValue.trim() || isLoading) return

    const userMessage: Message = {
      role: 'user',
      content: inputValue.trim(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInputValue('')
    setIsLoading(true)
    setError(null)

    try {
      const response = await axios.post(`${API_URL}/api/chat`, {
        case_id: caseId,
        question: userMessage.content,
      })

      if (response.data.status === 'success') {
        const assistantMessage: Message = {
          role: 'assistant',
          content: response.data.answer,
          sources: response.data.sources || [],
        }
        setMessages((prev) => [...prev, assistantMessage])
      } else {
        setError('Ошибка при получении ответа')
      }
    } catch (err: any) {
      setError(
        err.response?.data?.detail ||
          'Ошибка при отправке вопроса. Проверьте что backend запущен.'
      )
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-container">
      <div className="chat-header">
        <h2>Чат с AI</h2>
        <p className="chat-subtitle">
          {fileNames.length} документов загружено: {fileNames.join(', ')}
        </p>
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="empty-state">
            <p>Задайте вопрос о загруженных документах</p>
          </div>
        )}

        {messages.map((message, index) => (
          <div
            key={index}
            className={`message ${message.role === 'user' ? 'message-user' : 'message-assistant'}`}
          >
            <div className={`message-content ${message.role}`}>
              {message.content}
              {message.sources && message.sources.length > 0 && (
                <div className="sources">
                  {message.sources.map((source, idx) => (
                    <span key={idx} className="source-tag">
                      📎 {source}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="message message-assistant">
            <div className="message-content assistant">
              <div className="spinner-small"></div>
              <span>AI думает...</span>
            </div>
          </div>
        )}

        {error && (
          <div className="error-message">{error}</div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Введите вопрос..."
          disabled={isLoading}
          className="chat-input"
        />
        <button
          onClick={handleSend}
          disabled={isLoading || !inputValue.trim()}
          className="send-button"
        >
          Отправить
        </button>
      </div>
    </div>
  )
}

export default ChatWindow

