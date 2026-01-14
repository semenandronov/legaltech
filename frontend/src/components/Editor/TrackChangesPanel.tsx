import React, { useState } from 'react'
import { Check, X, Eye, EyeOff } from 'lucide-react'
import { Button } from '@/components/UI/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/UI/Card'

interface Change {
  id: string
  type: 'insertion' | 'deletion' | 'modification'
  oldText?: string
  newText?: string
  description?: string
}

interface TrackChangesPanelProps {
  changes: Change[]
  onAccept: (changeId: string) => void
  onReject: (changeId: string) => void
  onAcceptAll: () => void
  onRejectAll: () => void
  showPanel: boolean
  onTogglePanel: () => void
}

export const TrackChangesPanel: React.FC<TrackChangesPanelProps> = ({
  changes,
  onAccept,
  onReject,
  onAcceptAll,
  onRejectAll,
  showPanel,
  onTogglePanel,
}) => {
  const [expandedChanges, setExpandedChanges] = useState<Set<string>>(new Set())

  const toggleChange = (changeId: string) => {
    const newExpanded = new Set(expandedChanges)
    if (newExpanded.has(changeId)) {
      newExpanded.delete(changeId)
    } else {
      newExpanded.add(changeId)
    }
    setExpandedChanges(newExpanded)
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
          <Eye className="w-4 h-4 mr-2" />
          Показать изменения ({changes.length})
        </Button>
      </div>
    )
  }

  return (
    <Card className="w-96 h-full border-l shadow-lg">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">
            Изменения AI ({changes.length})
          </CardTitle>
          <div className="flex gap-2">
            <Button
              onClick={onAcceptAll}
              size="sm"
              variant="outline"
              className="text-xs"
              disabled={changes.length === 0}
            >
              Принять все
            </Button>
            <Button
              onClick={onRejectAll}
              size="sm"
              variant="outline"
              className="text-xs"
              disabled={changes.length === 0}
            >
              Отклонить все
            </Button>
            <Button
              onClick={onTogglePanel}
              size="sm"
              variant="ghost"
            >
              <EyeOff className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-3 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 120px)' }}>
        {changes.length === 0 ? (
          <div className="text-center text-sm text-muted-foreground py-8">
            Нет изменений для просмотра
          </div>
        ) : (
          <div className="space-y-2">
            {changes.map((change) => (
              <div
                key={change.id}
                className="border rounded-lg p-3 bg-card"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`text-xs font-medium px-2 py-0.5 rounded ${
                          change.type === 'insertion'
                            ? 'bg-green-100 text-green-700'
                            : change.type === 'deletion'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-blue-100 text-blue-700'
                        }`}
                      >
                        {change.type === 'insertion'
                          ? 'Добавлено'
                          : change.type === 'deletion'
                          ? 'Удалено'
                          : 'Изменено'}
                      </span>
                    </div>
                    {change.description && (
                      <p className="text-xs text-muted-foreground mb-2">
                        {change.description}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-1">
                    <Button
                      onClick={() => onAccept(change.id)}
                      size="sm"
                      variant="ghost"
                      className="h-6 w-6 p-0 text-green-600 hover:text-green-700 hover:bg-green-50"
                    >
                      <Check className="w-3 h-3" />
                    </Button>
                    <Button
                      onClick={() => onReject(change.id)}
                      size="sm"
                      variant="ghost"
                      className="h-6 w-6 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                    >
                      <X className="w-3 h-3" />
                    </Button>
                  </div>
                </div>
                {expandedChanges.has(change.id) && (
                  <div className="mt-2 space-y-2 text-xs">
                    {change.oldText && (
                      <div>
                        <div className="font-medium text-muted-foreground mb-1">Было:</div>
                        <div className="bg-red-50 border border-red-200 rounded p-2 line-through text-red-700">
                          {change.oldText}
                        </div>
                      </div>
                    )}
                    {change.newText && (
                      <div>
                        <div className="font-medium text-muted-foreground mb-1">Стало:</div>
                        <div className="bg-green-50 border border-green-200 rounded p-2 text-green-700">
                          {change.newText}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {!expandedChanges.has(change.id) && (change.oldText || change.newText) && (
                  <Button
                    onClick={() => toggleChange(change.id)}
                    size="sm"
                    variant="ghost"
                    className="text-xs mt-2"
                  >
                    Показать детали
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

