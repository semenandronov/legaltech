import { FileText, AlertTriangle, Users, Clock } from 'lucide-react'
import Card from '../UI/Card'
import Button from '../UI/Button'

interface QuickStatsProps {
  totalDocuments: number
  totalChunks: number
  lastIndexed: string
  indexStatus: 'active' | 'inactive'
  risksIdentified: number
  contradictions: number
  teamMembers: number
  onUploadDocuments?: () => void
  onGenerateReport?: () => void
  onShareWithTeam?: () => void
  onExportAnalysis?: () => void
  onArchiveCase?: () => void
}

const QuickStats = ({
  totalDocuments,
  totalChunks,
  lastIndexed,
  indexStatus,
  risksIdentified,
  contradictions,
  teamMembers,
  onUploadDocuments,
  onGenerateReport,
  onShareWithTeam,
  onExportAnalysis,
  onArchiveCase,
}: QuickStatsProps) => {
  return (
    <div className="w-[350px] h-screen bg-secondary border-l border-border flex flex-col overflow-y-auto">
      <div className="p-6 space-y-6">
        {/* Case Stats */}
        <Card>
          <h3 className="text-h3 text-primary mb-4">📊 Статистика дела</h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-secondary" />
                <span className="text-body text-secondary">Документов:</span>
              </div>
              <span className="text-body font-medium text-primary">{totalDocuments}</span>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-secondary" />
                <span className="text-body text-secondary">Фрагментов:</span>
              </div>
              <span className="text-body font-medium text-primary">{totalChunks}</span>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-secondary" />
                <span className="text-body text-secondary">Последняя индексация:</span>
              </div>
              <span className="text-small text-secondary">{lastIndexed}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-body text-secondary">Статус индексации:</span>
              <span className={`text-small font-medium ${indexStatus === 'active' ? 'text-success' : 'text-warning'}`}>
                {indexStatus === 'active' ? '✅ Active' : '⏳ Inactive'}
              </span>
            </div>
          </div>
        </Card>
        
        {/* Risks & Contradictions */}
        <Card>
          <h3 className="text-h3 text-primary mb-4">⚠️ Риски и противоречия</h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-body text-secondary">Выявлено рисков:</span>
              <span className="text-body font-medium text-error">{risksIdentified}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-body text-secondary">Противоречий:</span>
              <span className="text-body font-medium text-warning">{contradictions}</span>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Users className="w-4 h-4 text-secondary" />
                <span className="text-body text-secondary">Участников команды:</span>
              </div>
              <span className="text-body font-medium text-primary">{teamMembers}</span>
            </div>
          </div>
        </Card>
        
        {/* Quick Actions */}
        <Card>
          <h3 className="text-h3 text-primary mb-4">⚡ Быстрые действия</h3>
          <div className="space-y-2">
            <Button variant="primary" className="w-full" onClick={onUploadDocuments}>
              Загрузить документы
            </Button>
            <Button variant="secondary" className="w-full" onClick={onGenerateReport}>
              Сгенерировать отчёт
            </Button>
            <Button variant="secondary" className="w-full" onClick={onShareWithTeam}>
              Поделиться с командой
            </Button>
            <Button variant="secondary" className="w-full" onClick={onExportAnalysis}>
              Экспорт анализа
            </Button>
            <Button variant="danger" className="w-full" onClick={onArchiveCase}>
              Архивировать дело
            </Button>
          </div>
        </Card>
        
        {/* Recent Activity */}
        <Card>
          <h3 className="text-h3 text-primary mb-4">🕐 Последняя активность</h3>
          <div className="space-y-3">
            <div className="text-small text-secondary">
              <p className="text-primary font-medium">John Doe</p>
              <p>добавил документ 30 мин назад</p>
            </div>
            <div className="text-small text-secondary">
              <p className="text-primary font-medium">Система</p>
              <p>проанализировала новые противоречия 1ч назад</p>
            </div>
            <div className="text-small text-secondary">
              <p className="text-primary font-medium">Jane Doe</p>
              <p>оставила комментарий 3ч назад</p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}

export default QuickStats
