import React from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, Calendar, MoreVertical, ExternalLink, Share2, Archive, Copy } from 'lucide-react'
import { CaseListItem } from '../../services/api'
import { Card } from '../UI/Card'
import { Badge } from '../UI/Badge'
import { Button } from '../UI/Button'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/UI/context-menu'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/UI/dropdown-menu'

interface CaseCardProps {
  caseItem: CaseListItem
}

const CaseCard = ({ caseItem }: CaseCardProps) => {
  const navigate = useNavigate()
  
  // Определяем риск (в реальном приложении это должно приходить с API)
  const getRiskLevel = (): 'high-risk' | 'medium-risk' | 'low-risk' => {
    // Заглушка - в реальности нужно получать с API
    const risk = Math.random()
    if (risk > 0.7) return 'high-risk'
    if (risk > 0.4) return 'medium-risk'
    return 'low-risk'
  }
  
  const riskLevel = getRiskLevel()
  
  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffTime = Math.abs(now.getTime() - date.getTime())
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
    
    if (diffDays === 1) return '1 день назад'
    if (diffDays < 7) return `${diffDays} дня назад`
    if (diffDays < 30) return `${Math.ceil(diffDays / 7)} недели назад`
    return date.toLocaleDateString('ru-RU')
  }
  
  const getStatusBadge = (status: string) => {
    const statusMap: Record<string, { variant: 'pending' | 'completed' | 'flagged', label: string }> = {
      'review': { variant: 'pending', label: 'Review' },
      'investigation': { variant: 'flagged', label: 'Investigation' },
      'litigation': { variant: 'flagged', label: 'Litigation' },
      'completed': { variant: 'completed', label: 'Completed' },
    }
    
    const statusInfo = statusMap[status] || { variant: 'pending' as const, label: status }
    return statusInfo
  }
  
  const statusInfo = getStatusBadge(caseItem.status)
  
  const dropdownItems = [
    { label: 'Открыть', onClick: () => navigate(`/cases/${caseItem.id}/workspace`) },
    { label: 'Экспорт', onClick: () => console.log('Export') },
    { label: 'Поделиться', onClick: () => console.log('Share') },
    { label: 'Архивировать', onClick: () => console.log('Archive'), danger: true },
  ]
  
  return (
    <ContextMenu>
      <ContextMenuTrigger>
        <Card hoverable className="cursor-pointer" onClick={() => navigate(`/cases/${caseItem.id}/workspace`)}>
          <div className="space-y-3">
            {/* Header */}
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <FileText className="w-5 h-5 text-primary" />
                  <h3 className="text-h3 text-primary">{caseItem.title || 'Без названия'}</h3>
                </div>
                {caseItem.case_type && (
                  <p className="text-body text-secondary">vs {caseItem.case_type}</p>
                )}
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className="p-1 hover:bg-tertiary rounded transition-colors"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <MoreVertical className="w-4 h-4 text-secondary" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => navigate(`/cases/${caseItem.id}/workspace`)}>
                    <ExternalLink className="mr-2 h-4 w-4" />
                    Открыть
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => navigate(`/cases/${caseItem.id}/chat`)}>
                    Чат
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem>
                    <Copy className="mr-2 h-4 w-4" />
                    Копировать
                  </DropdownMenuItem>
                  <DropdownMenuItem>
                    <Share2 className="mr-2 h-4 w-4" />
                    Поделиться
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem className="text-destructive">
                    <Archive className="mr-2 h-4 w-4" />
                    Архивировать
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
        
        {/* Badges */}
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant={riskLevel}>
            {riskLevel === 'high-risk' && '🔴'}
            {riskLevel === 'medium-risk' && '🟡'}
            {riskLevel === 'low-risk' && '🟢'}
            {' '}
            {riskLevel === 'high-risk' && 'High'}
            {riskLevel === 'medium-risk' && 'Medium'}
            {riskLevel === 'low-risk' && 'Low'}
          </Badge>
          <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
        </div>
        
        {/* Stats */}
        <div className="flex items-center gap-4 text-small text-secondary">
          <div className="flex items-center gap-1">
            <FileText className="w-4 h-4" />
            <span>Документов: {caseItem.num_documents}</span>
          </div>
          <div className="flex items-center gap-1">
            <Calendar className="w-4 h-4" />
            <span>Обновлено: {formatDate(caseItem.updated_at)}</span>
          </div>
        </div>
        
        {/* Quick Actions */}
        <div className="flex items-center gap-2 pt-2 border-t border-border">
          <Button
            variant="primary"
            size="sm"
            onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
              e.stopPropagation()
              navigate(`/cases/${caseItem.id}/workspace`)
            }}
          >
            Открыть
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
              e.stopPropagation()
              console.log('Export')
            }}
          >
            Экспорт
          </Button>
        </div>
      </div>
    </Card>
      </ContextMenuTrigger>
      <ContextMenuContent className="w-56">
        <ContextMenuItem onClick={() => navigate(`/cases/${caseItem.id}/workspace`)}>
          <ExternalLink className="mr-2 h-4 w-4" />
          Открыть
        </ContextMenuItem>
        <ContextMenuItem onClick={() => navigate(`/cases/${caseItem.id}/chat`)}>
          Чат
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem>
          <Copy className="mr-2 h-4 w-4" />
          Копировать
        </ContextMenuItem>
        <ContextMenuItem>
          <Share2 className="mr-2 h-4 w-4" />
          Поделиться
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem className="text-destructive">
          <Archive className="mr-2 h-4 w-4" />
          Архивировать
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}

export default CaseCard
