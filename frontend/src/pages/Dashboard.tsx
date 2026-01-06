import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, FolderOpen, Table2, MessageSquare, MoreVertical, ArrowRight } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/UI/Card'
import { Button } from '../components/UI/button'
import MainLayout from '../components/Layout/MainLayout'
import { getCasesList } from '../services/api'
import { tabularReviewApi } from '../services/tabularReviewApi'

interface Case {
  id: string
  title: string | null
  description?: string
  status: string
  created_at: string
}

interface TabularReview {
  id: string
  case_id: string
  name: string
  description?: string
  status: string
  created_at?: string
  updated_at?: string
}

const Dashboard: React.FC = () => {
  const navigate = useNavigate()
  const [cases, setCases] = useState<Case[]>([])
  const [recentReviews, setRecentReviews] = useState<TabularReview[]>([])
  const [loading, setLoading] = useState(true)
  const [reviewsLoading, setReviewsLoading] = useState(true)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      setLoading(true)
      const [casesData, reviewsData] = await Promise.all([
        getCasesList(0, 6), // Get first 6 cases
        tabularReviewApi.listReviews(undefined, 0, 5), // Get first 5 recent reviews (no case filter)
      ])
      setCases(casesData.cases)
      setRecentReviews(reviewsData.reviews)
    } catch (error: any) {
      console.error('Error loading dashboard data:', error)
    } finally {
      setLoading(false)
      setReviewsLoading(false)
    }
  }

  const getStatusColor = (status: string): 'default' | 'primary' | 'success' | 'warning' | 'error' => {
    switch (status) {
      case 'completed':
        return 'success'
      case 'processing':
        return 'warning'
      case 'draft':
        return 'default'
      default:
        return 'default'
    }
  }

  const getInitials = (name: string | null): string => {
    if (!name) return '??'
    return name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2)
  }

  const formatDate = (dateString?: string): string => {
    if (!dateString) return ''
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffDays === 0) return 'Сегодня'
    if (diffDays === 1) return 'Вчера'
    if (diffDays < 7) return `${diffDays} дн. назад`
    return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
  }

  return (
    <MainLayout>
      <div 
        className="max-w-7xl mx-auto py-8 px-4"
        style={{ 
          padding: 'var(--space-8) var(--space-4)',
          backgroundColor: 'var(--color-bg-primary)'
        }}
      >
        <div className="space-y-6" style={{ gap: 'var(--space-6)' }}>
          {/* Header */}
          <div>
            <h1 
              className="text-4xl font-display mb-2"
              style={{ 
                fontFamily: 'var(--font-display)',
                color: 'var(--color-text-primary)',
                fontWeight: 400,
                letterSpacing: 'var(--tracking-tight)'
              }}
            >
              Проекты
            </h1>
            <p 
              className="text-sm"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              Управляйте вашими делами и Tabular Reviews
            </p>
          </div>

          {/* Quick Actions */}
          <Card className="animate-fade-in">
            <CardContent style={{ padding: 'var(--space-6)' }}>
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="default"
                  onClick={() => navigate('/cases/new')}
                  className="flex items-center gap-2"
                >
                  <Plus className="w-4 h-4" />
                  Новое дело
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => navigate('/cases')}
                  className="flex items-center gap-2"
                >
                  <Table2 className="w-4 h-4" />
                  Все дела
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => navigate('/cases')}
                  className="flex items-center gap-2"
                >
                  <MessageSquare className="w-4 h-4" />
                  Все чаты
                </Button>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Projects Grid */}
            <div className="md:col-span-2">
              <Card className="animate-fade-in">
                <CardHeader style={{ padding: 'var(--space-6)' }}>
                  <div className="flex items-center justify-between">
                    <CardTitle style={{ fontFamily: 'var(--font-display)', fontWeight: 400 }}>
                      Проекты
                    </CardTitle>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => navigate('/cases')}
                      className="flex items-center gap-2"
                    >
                      Все проекты
                      <ArrowRight className="w-4 h-4" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent style={{ padding: 'var(--space-6)' }}>
                  {loading ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      {[1, 2, 3, 4, 5, 6].map((i) => (
                        <div 
                          key={i}
                          className="h-32 rounded-lg border animate-pulse"
                          style={{
                            backgroundColor: 'var(--color-bg-secondary)',
                            borderColor: 'var(--color-border)'
                          }}
                        />
                      ))}
                    </div>
                  ) : cases.length === 0 ? (
                    <div 
                      className="text-center py-8"
                      style={{ padding: 'var(--space-8)' }}
                    >
                      <FolderOpen 
                        className="w-12 h-12 mx-auto mb-4"
                        style={{ color: 'var(--color-text-muted)' }}
                      />
                      <p 
                        className="text-base mb-4"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        Нет проектов
                      </p>
                      <Button
                        variant="default"
                        onClick={() => navigate('/cases/new')}
                        className="flex items-center gap-2 mx-auto"
                      >
                        <Plus className="w-4 h-4" />
                        Создать проект
                      </Button>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      {cases.map((caseItem) => (
                        <Card
                          key={caseItem.id}
                          className="cursor-pointer transition-all duration-150 hover:bg-bg-hover"
                          style={{
                            borderColor: 'var(--color-border)',
                          }}
                          onClick={() => navigate(`/cases/${caseItem.id}`)}
                        >
                          <CardContent style={{ padding: 'var(--space-4)' }}>
                            <div className="space-y-3">
                              <div className="flex items-center gap-3">
                                <div 
                                  className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-medium"
                                  style={{
                                    backgroundColor: 'var(--color-bg-active)',
                                    color: 'var(--color-text-primary)'
                                  }}
                                >
                                  {getInitials(caseItem.title)}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <h3 
                                    className="text-base font-medium truncate"
                                    style={{ color: 'var(--color-text-primary)' }}
                                  >
                                    {caseItem.title || `Дело ${caseItem.id.slice(0, 8)}`}
                                  </h3>
                                  {caseItem.description && (
                                    <p 
                                      className="text-sm line-clamp-2 mt-1"
                                      style={{ color: 'var(--color-text-secondary)' }}
                                    >
                                      {caseItem.description}
                                    </p>
                                  )}
                                </div>
                                <button
                                  className="p-1 rounded-md hover:bg-bg-hover transition-colors"
                                  style={{ color: 'var(--color-text-secondary)' }}
                                >
                                  <MoreVertical className="w-4 h-4" />
                                </button>
                              </div>
                              <div className="flex items-center justify-between">
                                <span 
                                  className="text-xs px-2 py-1 rounded-md"
                                  style={{
                                    backgroundColor: getStatusColor(caseItem.status) === 'success' 
                                      ? 'var(--color-success-bg)' 
                                      : getStatusColor(caseItem.status) === 'warning'
                                      ? 'var(--color-warning-bg)'
                                      : 'var(--color-bg-tertiary)',
                                    color: getStatusColor(caseItem.status) === 'success'
                                      ? 'var(--color-success)'
                                      : getStatusColor(caseItem.status) === 'warning'
                                      ? 'var(--color-warning)'
                                      : 'var(--color-text-secondary)',
                                  }}
                                >
                                  {caseItem.status}
                                </span>
                                <span 
                                  className="text-xs"
                                  style={{ color: 'var(--color-text-muted)' }}
                                >
                                  {formatDate(caseItem.created_at)}
                                </span>
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Recent Reviews Sidebar */}
            <div className="md:col-span-1">
              <Card className="animate-fade-in">
                <CardHeader style={{ padding: 'var(--space-6)' }}>
                  <div className="flex items-center justify-between">
                    <CardTitle style={{ fontFamily: 'var(--font-display)', fontWeight: 400 }}>
                      Недавние Tabular Reviews
                    </CardTitle>
                    <button
                      className="p-1 rounded-md hover:bg-bg-hover transition-colors"
                      style={{ color: 'var(--color-text-secondary)' }}
                    >
                      <MoreVertical className="w-4 h-4" />
                    </button>
                  </div>
                </CardHeader>
                <div 
                  className="border-t"
                  style={{ borderTopColor: 'var(--color-border)' }}
                />
                <CardContent style={{ padding: 'var(--space-6)' }}>
                  {reviewsLoading ? (
                    <div className="space-y-3">
                      {[1, 2, 3].map((i) => (
                        <div 
                          key={i}
                          className="h-16 rounded-lg border animate-pulse"
                          style={{
                            backgroundColor: 'var(--color-bg-secondary)',
                            borderColor: 'var(--color-border)'
                          }}
                        />
                      ))}
                    </div>
                  ) : recentReviews.length === 0 ? (
                    <div 
                      className="text-center py-8"
                      style={{ padding: 'var(--space-8)' }}
                    >
                      <Table2 
                        className="w-12 h-12 mx-auto mb-4"
                        style={{ color: 'var(--color-text-muted)' }}
                      />
                      <p 
                        className="text-sm"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        Нет недавних reviews
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {recentReviews.map((review, idx) => (
                        <div key={review.id}>
                          <button
                            className="w-full flex items-center gap-3 p-3 rounded-lg transition-all duration-150 hover:bg-bg-hover text-left"
                            onClick={() => navigate(`/cases/${review.case_id}/tabular-review/${review.id}`)}
                          >
                            <div 
                              className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0"
                              style={{
                                backgroundColor: 'var(--color-bg-active)',
                                color: 'var(--color-text-primary)'
                              }}
                            >
                              <Table2 className="w-5 h-5" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p 
                                className="text-sm font-medium truncate"
                                style={{ color: 'var(--color-text-primary)' }}
                              >
                                {review.name}
                              </p>
                              <div className="flex items-center gap-2 mt-1">
                                <span 
                                  className="text-xs px-2 py-0.5 rounded-md"
                                  style={{
                                    backgroundColor: getStatusColor(review.status) === 'success' 
                                      ? 'var(--color-success-bg)' 
                                      : getStatusColor(review.status) === 'warning'
                                      ? 'var(--color-warning-bg)'
                                      : 'var(--color-bg-tertiary)',
                                    color: getStatusColor(review.status) === 'success'
                                      ? 'var(--color-success)'
                                      : getStatusColor(review.status) === 'warning'
                                      ? 'var(--color-warning)'
                                      : 'var(--color-text-secondary)',
                                  }}
                                >
                                  {review.status}
                                </span>
                                <span 
                                  className="text-xs"
                                  style={{ color: 'var(--color-text-muted)' }}
                                >
                                  {formatDate(review.updated_at || review.created_at)}
                                </span>
                              </div>
                            </div>
                          </button>
                          {idx < recentReviews.length - 1 && (
                            <div 
                              className="border-b my-1"
                              style={{ borderBottomColor: 'var(--color-border)' }}
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  )
}

export default Dashboard
