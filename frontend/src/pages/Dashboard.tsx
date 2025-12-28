import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box,
  Container,
  Grid,
  Card,
  CardContent,
  CardHeader,
  Typography,
  Button,
  Avatar,
  Chip,
  Stack,
  List,
  ListItem,
  ListItemButton,
  ListItemAvatar,
  ListItemText,
  IconButton,
  Skeleton,
  Divider,
  Fade,
  Grow,
} from '@mui/material'
import {
  Add as AddIcon,
  FolderOpen as FolderOpenIcon,
  TableChart as TableChartIcon,
  Chat as ChatIcon,
  MoreVert as MoreVertIcon,
  ArrowForward as ArrowForwardIcon,
} from '@mui/icons-material'
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
        tabularReviewApi.listReviews(0, 5), // Get first 5 recent reviews
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
      <Container maxWidth="xl" sx={{ py: 4 }}>
        <Stack spacing={4}>
          {/* Header */}
          <Box>
            <Typography variant="h4" fontWeight={600} gutterBottom>
              Проекты
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Управляйте вашими делами и Tabular Reviews
            </Typography>
          </Box>

          {/* Quick Actions */}
          <Grow in timeout={400}>
            <Card>
              <CardContent>
                <Stack direction="row" spacing={2}>
                <Button
                  variant="contained"
                  startIcon={<AddIcon />}
                  onClick={() => navigate('/cases/new')}
                >
                  Новое дело
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<TableChartIcon />}
                  onClick={() => navigate('/cases')}
                >
                  Все дела
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<ChatIcon />}
                  onClick={() => navigate('/cases')}
                >
                  Все чаты
                </Button>
              </Stack>
            </CardContent>
          </Card>
          </Grow>

          <Grid container spacing={3}>
            {/* Projects Grid */}
            <Grid item xs={12} md={8}>
              <Card>
                <CardHeader
                  title="Проекты"
                  action={
                    <Button
                      size="small"
                      endIcon={<ArrowForwardIcon />}
                      onClick={() => navigate('/cases')}
                    >
                      Все проекты
                    </Button>
                  }
                />
                <CardContent>
                  {loading ? (
                    <Grid container spacing={2}>
                      {[1, 2, 3, 4, 5, 6].map((i) => (
                        <Grid item xs={12} sm={6} key={i}>
                          <Skeleton variant="rectangular" height={120} />
                        </Grid>
                      ))}
                    </Grid>
                  ) : cases.length === 0 ? (
                    <Box sx={{ textAlign: 'center', py: 4 }}>
                      <FolderOpenIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2 }} />
                      <Typography variant="body1" color="text.secondary" gutterBottom>
                        Нет проектов
                      </Typography>
                      <Button
                        variant="contained"
                        startIcon={<AddIcon />}
                        onClick={() => navigate('/cases/new')}
                        sx={{ mt: 2 }}
                      >
                        Создать проект
                      </Button>
                    </Box>
                  ) : (
                    <Grid container spacing={2}>
                      {cases.map((caseItem, idx) => (
                        <Grid item xs={12} sm={6} key={caseItem.id}>
                          <Fade in timeout={300 + idx * 100}>
                            <Card
                            sx={{
                              cursor: 'pointer',
                              transition: 'all 0.2s',
                              '&:hover': {
                                boxShadow: 4,
                                transform: 'translateY(-2px)',
                              },
                            }}
                            onClick={() => navigate(`/cases/${caseItem.id}`)}
                          >
                            <CardContent>
                              <Stack spacing={2}>
                                <Stack direction="row" spacing={2} alignItems="center">
                                  <Avatar sx={{ bgcolor: 'primary.main' }}>
                                    {getInitials(caseItem.title)}
                                  </Avatar>
                                  <Box sx={{ flex: 1, minWidth: 0 }}>
                                    <Typography variant="subtitle1" fontWeight={600} noWrap>
                                      {caseItem.title || `Дело ${caseItem.id.slice(0, 8)}`}
                                    </Typography>
                                    {caseItem.description && (
                                      <Typography
                                        variant="body2"
                                        color="text.secondary"
                                        sx={{
                                          overflow: 'hidden',
                                          textOverflow: 'ellipsis',
                                          display: '-webkit-box',
                                          WebkitLineClamp: 2,
                                          WebkitBoxOrient: 'vertical',
                                        }}
                                      >
                                        {caseItem.description}
                                      </Typography>
                                    )}
                                  </Box>
                                  <IconButton size="small">
                                    <MoreVertIcon />
                                  </IconButton>
                                </Stack>
                                <Stack direction="row" spacing={1} alignItems="center">
                                  <Chip
                                    label={caseItem.status}
                                    size="small"
                                    color={getStatusColor(caseItem.status)}
                                  />
                                  <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                                    {formatDate(caseItem.created_at)}
                                  </Typography>
                                </Stack>
                              </Stack>
                            </CardContent>
                          </Card>
                          </Fade>
                        </Grid>
                      ))}
                    </Grid>
                  )}
                </CardContent>
              </Card>
            </Grid>

            {/* Recent Reviews Sidebar */}
            <Grid item xs={12} md={4}>
              <Card>
                <CardHeader
                  title="Недавние Tabular Reviews"
                  action={
                    <IconButton size="small">
                      <MoreVertIcon />
                    </IconButton>
                  }
                />
                <Divider />
                <CardContent>
                  {reviewsLoading ? (
                    <Stack spacing={2}>
                      {[1, 2, 3].map((i) => (
                        <Skeleton key={i} variant="rectangular" height={60} />
                      ))}
                    </Stack>
                  ) : recentReviews.length === 0 ? (
                    <Box sx={{ textAlign: 'center', py: 4 }}>
                      <TableChartIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2 }} />
                      <Typography variant="body2" color="text.secondary">
                        Нет недавних reviews
                      </Typography>
                    </Box>
                  ) : (
                    <List>
                      {recentReviews.map((review, idx) => (
                        <React.Fragment key={review.id}>
                          <ListItem disablePadding>
                            <ListItemButton
                              onClick={() => navigate(`/cases/${review.case_id}/tabular-review/${review.id}`)}
                              sx={{
                                '&:hover': {
                                  bgcolor: 'action.hover',
                                },
                              }}
                            >
                              <ListItemAvatar>
                                <Avatar sx={{ bgcolor: 'primary.main' }}>
                                  <TableChartIcon />
                                </Avatar>
                              </ListItemAvatar>
                              <ListItemText
                                primary={review.name}
                                secondary={
                                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
                                    <Chip
                                      label={review.status}
                                      size="small"
                                      color={getStatusColor(review.status)}
                                    />
                                    <Typography variant="caption" color="text.secondary">
                                      {formatDate(review.updated_at || review.created_at)}
                                    </Typography>
                                  </Stack>
                                }
                              />
                            </ListItemButton>
                          </ListItem>
                          {idx < recentReviews.length - 1 && <Divider variant="inset" component="li" />}
                        </React.Fragment>
                      ))}
                    </List>
                  )}
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </Stack>
      </Container>
    </MainLayout>
  )
}

export default Dashboard
