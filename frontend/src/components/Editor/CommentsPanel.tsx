import React, { useState } from 'react'
import { MessageSquare, X, Plus } from 'lucide-react'
import { Button } from '@/components/UI/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/UI/Card'
import { Textarea } from '@/components/UI/Textarea'
import { ScrollArea } from '@/components/UI/scroll-area'

interface Comment {
  id: string
  from: number
  to: number
  text: string
  author?: string
  createdAt?: string
}

interface CommentsPanelProps {
  comments: Comment[]
  onAddComment: (from: number, to: number, text: string) => void
  onRemoveComment: (id: string) => void
  showPanel: boolean
  onTogglePanel: () => void
  selectedText?: string
  selectedRange?: { from: number; to: number }
}

export const CommentsPanel: React.FC<CommentsPanelProps> = ({
  comments,
  onAddComment,
  onRemoveComment,
  showPanel,
  onTogglePanel,
  selectedText,
  selectedRange,
}) => {
  const [newCommentText, setNewCommentText] = useState('')
  const [showAddForm, setShowAddForm] = useState(false)

  const handleAddComment = () => {
    if (newCommentText.trim() && selectedRange) {
      onAddComment(selectedRange.from, selectedRange.to, newCommentText.trim())
      setNewCommentText('')
      setShowAddForm(false)
    }
  }

  if (!showPanel) {
    return (
      <div className="fixed bottom-4 right-4 z-50">
        <Button
          onClick={onTogglePanel}
          size="sm"
          variant="outline"
          className="shadow-lg"
        >
          <MessageSquare className="w-4 h-4 mr-2" />
          Комментарии ({comments.length})
        </Button>
      </div>
    )
  }

  return (
    <Card className="w-96 h-full border-l shadow-lg">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">
            Комментарии ({comments.length})
          </CardTitle>
          <Button
            onClick={onTogglePanel}
            size="sm"
            variant="ghost"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-3 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 120px)' }}>
        {selectedText && selectedRange && (
          <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
            <div className="text-xs font-medium text-blue-700 mb-1">Выделенный текст:</div>
            <div className="text-sm text-blue-900 mb-2 line-clamp-2">{selectedText}</div>
            {!showAddForm ? (
              <Button
                onClick={() => setShowAddForm(true)}
                size="sm"
                variant="outline"
                className="w-full"
              >
                <Plus className="w-3 h-3 mr-1" />
                Добавить комментарий
              </Button>
            ) : (
              <div className="space-y-2">
                <Textarea
                  value={newCommentText}
                  onChange={(e) => setNewCommentText(e.target.value)}
                  placeholder="Введите комментарий..."
                  className="text-sm"
                  rows={3}
                />
                <div className="flex gap-2">
                  <Button
                    onClick={handleAddComment}
                    size="sm"
                    className="flex-1"
                    disabled={!newCommentText.trim()}
                  >
                    Добавить
                  </Button>
                  <Button
                    onClick={() => {
                      setShowAddForm(false)
                      setNewCommentText('')
                    }}
                    size="sm"
                    variant="outline"
                  >
                    Отмена
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {comments.length === 0 ? (
          <div className="text-center text-sm text-muted-foreground py-8">
            Нет комментариев
            {!selectedText && (
              <div className="mt-2 text-xs">
                Выделите текст, чтобы добавить комментарий
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {comments.map((comment) => (
              <div
                key={comment.id}
                className="border rounded-lg p-3 bg-card"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1">
                    <div className="text-sm">{comment.text}</div>
                    {comment.createdAt && (
                      <div className="text-xs text-muted-foreground mt-1">
                        {new Date(comment.createdAt).toLocaleString('ru-RU')}
                      </div>
                    )}
                  </div>
                  <Button
                    onClick={() => onRemoveComment(comment.id)}
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                  >
                    <X className="w-3 h-3" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

