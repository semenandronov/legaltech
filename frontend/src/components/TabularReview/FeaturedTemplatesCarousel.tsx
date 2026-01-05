import React, { useState, useEffect } from 'react'
import {
  Box,
  Card,
  CardContent,
  Typography,
  Stack,
  Chip,
  IconButton,
  Button,
  Skeleton,
} from '@mui/material'
import {
  Star as StarIcon,
  PlayArrow as PlayIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
} from '@mui/icons-material'
import { tabularReviewApi, TabularTemplate } from './TemplatesModal'
import { toast } from 'sonner'

interface FeaturedTemplatesCarouselProps {
  reviewId: string
  onTemplateApplied?: () => void
  onViewAll?: () => void
}

export const FeaturedTemplatesCarousel: React.FC<FeaturedTemplatesCarouselProps> = ({
  reviewId,
  onTemplateApplied,
  onViewAll,
}) => {
  const [templates, setTemplates] = useState<TabularTemplate[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [scrollPosition, setScrollPosition] = useState(0)

  useEffect(() => {
    loadFeaturedTemplates()
  }, [])

  const loadFeaturedTemplates = async () => {
    setIsLoading(true)
    try {
      const data = await tabularReviewApi.getTemplates({ featured: true })
      setTemplates(data.slice(0, 6)) // Show max 6 featured templates
    } catch (error: any) {
      console.error('Error loading featured templates:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleApplyTemplate = async (template: TabularTemplate) => {
    if (!reviewId) return
    
    try {
      console.log("Applying template:", { reviewId, templateId: template.id, templateName: template.name, columnsCount: template.columns.length })
      await tabularReviewApi.applyTemplate(reviewId, template.id)
      toast.success(`Шаблон "${template.name}" применен: добавлено ${template.columns.length} колонок`)
      onTemplateApplied?.()
    } catch (error: any) {
      console.error('Error applying template:', error)
      toast.error('Ошибка при применении шаблона')
    }
  }

  const scrollLeft = () => {
    const container = document.getElementById('templates-carousel')
    if (container) {
      container.scrollBy({ left: -300, behavior: 'smooth' })
      setScrollPosition(container.scrollLeft - 300)
    }
  }

  const scrollRight = () => {
    const container = document.getElementById('templates-carousel')
    if (container) {
      container.scrollBy({ left: 300, behavior: 'smooth' })
      setScrollPosition((container.scrollLeft || 0) + 300)
    }
  }

  if (isLoading) {
    return (
      <Box sx={{ py: 2 }}>
        <Stack direction="row" spacing={2} sx={{ overflowX: 'auto' }}>
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} variant="rectangular" width={280} height={180} />
          ))}
        </Stack>
      </Box>
    )
  }

  if (templates.length === 0) {
    return null
  }

  return (
    <Box sx={{ py: 2 }}>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h6" fontWeight={600}>
          Избранные шаблоны
        </Typography>
        {onViewAll && (
          <Button size="small" onClick={onViewAll}>
            Все шаблоны
          </Button>
        )}
      </Stack>
      
      <Box sx={{ position: 'relative' }}>
        <IconButton
          onClick={scrollLeft}
          disabled={scrollPosition <= 0}
          sx={{
            position: 'absolute',
            left: -20,
            top: '50%',
            transform: 'translateY(-50%)',
            zIndex: 1,
            bgcolor: 'background.paper',
            boxShadow: 2,
            '&:hover': { bgcolor: 'action.hover' },
          }}
        >
          <ChevronLeftIcon />
        </IconButton>
        
        <Box
          id="templates-carousel"
          sx={{
            display: 'flex',
            gap: 2,
            overflowX: 'auto',
            scrollBehavior: 'smooth',
            scrollbarWidth: 'thin',
            '&::-webkit-scrollbar': {
              height: 8,
            },
            '&::-webkit-scrollbar-thumb': {
              backgroundColor: 'action.disabled',
              borderRadius: 4,
            },
            px: 1,
          }}
        >
          {templates.map((template) => (
            <Card
              key={template.id}
              sx={{
                minWidth: 280,
                maxWidth: 280,
                transition: 'all 0.2s',
                '&:hover': {
                  boxShadow: 4,
                  transform: 'translateY(-4px)',
                },
              }}
            >
              <CardContent>
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography variant="subtitle1" fontWeight={600} sx={{ flex: 1 }}>
                      {template.name}
                    </Typography>
                    {template.is_featured && (
                      <StarIcon fontSize="small" color="primary" />
                    )}
                  </Stack>
                  
                  {template.description && (
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                    >
                      {template.description}
                    </Typography>
                  )}
                  
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                    <Chip
                      label={`${template.columns.length} колонок`}
                      size="small"
                      variant="outlined"
                    />
                    {template.category && (
                      <Chip
                        label={template.category}
                        size="small"
                        variant="outlined"
                      />
                    )}
                  </Stack>
                  
                  <Button
                    variant="contained"
                    size="small"
                    startIcon={<PlayIcon />}
                    fullWidth
                    onClick={(e) => {
                      e.stopPropagation()
                      handleApplyTemplate(template)
                    }}
                  >
                    Использовать
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          ))}
        </Box>
        
        <IconButton
          onClick={scrollRight}
          sx={{
            position: 'absolute',
            right: -20,
            top: '50%',
            transform: 'translateY(-50%)',
            zIndex: 1,
            bgcolor: 'background.paper',
            boxShadow: 2,
            '&:hover': { bgcolor: 'action.hover' },
          }}
        >
          <ChevronRightIcon />
        </IconButton>
      </Box>
    </Box>
  )
}

