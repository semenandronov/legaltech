import React, { useState, useEffect } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  Button,
  TextField,
  Chip,
  Box,
  Typography,
  Stack,
  Tabs,
  Tab,
  Card,
  CardContent,
  InputAdornment,
  Divider,
  CircularProgress,
  IconButton,
  Grid,
  Fade,
} from '@mui/material'
import {
  Search as SearchIcon,
  Star as StarIcon,
  AccessTime as ClockIcon,
  Description as FileTextIcon,
  Gavel as GavelIcon,
  Shield as ShieldIcon,
  FolderOpen as FolderOpenIcon,
  PlayArrow as PlayIcon,
  AutoAwesome as SparklesIcon,
  Close as CloseIcon,
} from '@mui/icons-material'
import { tabularReviewApi } from '@/services/tabularReviewApi'
import { toast } from 'sonner'

// Re-export for use in other components
export { tabularReviewApi }

export interface TabularTemplate {
  id: string
  name: string
  description?: string
  columns: Array<{
    column_label: string
    column_type: string
    prompt: string
  }>
  is_public: boolean
  is_system?: boolean
  is_featured?: boolean
  category?: string
  tags?: string[]
  usage_count?: number
  created_at?: string
}

interface TemplatesModalProps {
  isOpen: boolean
  onClose: () => void
  reviewId: string
  onTemplateApplied?: () => void
}

const CATEGORY_ICONS: Record<string, React.ReactElement> = {
  contract: <FileTextIcon fontSize="small" />,
  litigation: <GavelIcon fontSize="small" />,
  due_diligence: <ShieldIcon fontSize="small" />,
  research: <FileTextIcon fontSize="small" />,
  compliance: <ShieldIcon fontSize="small" />,
  custom: <FolderOpenIcon fontSize="small" />,
}

const CATEGORY_NAMES: Record<string, string> = {
  contract: 'Договоры',
  litigation: 'Судебные дела',
  due_diligence: 'Due Diligence',
  research: 'Исследование',
  compliance: 'Compliance',
  custom: 'Прочее',
}

export const TemplatesModal: React.FC<TemplatesModalProps> = ({
  isOpen,
  onClose,
  reviewId,
  onTemplateApplied,
}) => {
  const [templates, setTemplates] = useState<TabularTemplate[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [selectedTemplate, setSelectedTemplate] = useState<TabularTemplate | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const [activeTab, setActiveTab] = useState(0) // 0: all, 1: featured, 2: my

  useEffect(() => {
    if (isOpen) {
      loadTemplates()
    }
  }, [isOpen, selectedCategory, searchQuery])

  const loadTemplates = async () => {
    setIsLoading(true)
    try {
      const params: {
        category?: string
        featured?: boolean
        search?: string
      } = {}
      
      if (selectedCategory) params.category = selectedCategory
      if (searchQuery) params.search = searchQuery
      if (activeTab === 1) params.featured = true
      
      const data = await tabularReviewApi.getTemplates(params)
      setTemplates(data)
    } catch (error: any) {
      console.error('Error loading templates:', error)
      toast.error('Ошибка при загрузке шаблонов')
    } finally {
      setIsLoading(false)
    }
  }

  const handleApplyTemplate = async (template: TabularTemplate) => {
    if (!reviewId) return
    
    setIsApplying(true)
    try {
      console.log("Applying template from modal:", { reviewId, templateId: template.id, templateName: template.name, columnsCount: template.columns.length })
      await tabularReviewApi.applyTemplate(reviewId, template.id)
      toast.success(`Шаблон "${template.name}" применен: добавлено ${template.columns.length} колонок`)
      onTemplateApplied?.()
      onClose()
      setSelectedTemplate(null)
    } catch (error: any) {
      console.error('Error applying template:', error)
      toast.error('Ошибка при применении шаблона')
    } finally {
      setIsApplying(false)
    }
  }

  const categories = Object.keys(CATEGORY_NAMES)

  const filteredTemplates = templates.filter(t => {
    if (activeTab === 1) return t.is_featured === true
    if (activeTab === 2) return !t.is_system && !t.is_public
    return true
  })

  return (
    <Dialog 
      open={isOpen} 
      onClose={onClose} 
      maxWidth="md" 
      fullWidth
      PaperProps={{
        sx: { height: '80vh' }
      }}
    >
      <DialogTitle>
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
          <Stack direction="row" spacing={1} alignItems="center">
            <SparklesIcon color="primary" />
            <Typography variant="h6">Библиотека шаблонов</Typography>
          </Stack>
          <IconButton size="small" onClick={onClose}>
            <CloseIcon />
          </IconButton>
        </Stack>
      </DialogTitle>
      <Typography variant="body2" color="text.secondary" sx={{ px: 3, pb: 2 }}>
        Выберите готовый шаблон для быстрого создания колонок
      </Typography>

      <DialogContent dividers sx={{ p: 0, display: 'flex', flexDirection: 'column', height: '100%' }}>
        <Box sx={{ display: 'flex', height: '100%' }}>
          {/* Left sidebar - categories */}
          <Box
            sx={{
              width: 240,
              flexShrink: 0,
              borderRight: 1,
              borderColor: 'divider',
              p: 2,
              display: 'flex',
              flexDirection: 'column',
              gap: 2,
            }}
          >
            <Button
              variant="contained"
              fullWidth
              startIcon={<SparklesIcon />}
              onClick={() => {
                toast.info("Создание нового шаблона будет реализовано позже")
              }}
              sx={{ justifyContent: 'flex-start', mb: 1 }}
          >
              + New template
            </Button>
            
            <Divider />
            
            <Stack spacing={0.5}>
              <Button
                variant={activeTab === 0 && selectedCategory === null ? 'contained' : 'text'}
                fullWidth
                onClick={() => {
                  setActiveTab(0)
                  setSelectedCategory(null)
                }}
                sx={{ justifyContent: 'flex-start' }}
              >
                Все
              </Button>
              <Button
                variant={activeTab === 1 ? 'contained' : 'text'}
                fullWidth
                startIcon={<StarIcon />}
                onClick={() => {
                  setActiveTab(1)
                  setSelectedCategory(null)
                }}
                sx={{ justifyContent: 'flex-start' }}
              >
                Избранные
              </Button>
              <Button
                variant={activeTab === 2 ? 'contained' : 'text'}
                fullWidth
                startIcon={<ClockIcon />}
                onClick={() => {
                  setActiveTab(2)
                  setSelectedCategory(null)
                }}
                sx={{ justifyContent: 'flex-start' }}
              >
                Мои шаблоны
              </Button>
            </Stack>
            
            <Divider />
            
            <Typography variant="caption" color="text.secondary" sx={{ px: 1, fontWeight: 600 }}>
              by System
            </Typography>
            
            <Stack spacing={0.5}>
              {categories.map((cat) => (
                <Button
                  key={cat}
                  variant={selectedCategory === cat ? 'contained' : 'text'}
                  fullWidth
                  startIcon={CATEGORY_ICONS[cat]}
                  onClick={() => {
                    setSelectedCategory(cat)
                    setActiveTab(0)
                  }}
                  sx={{ justifyContent: 'flex-start' }}
                >
                  {CATEGORY_NAMES[cat]}
                </Button>
              ))}
            </Stack>
          </Box>

          {/* Main content */}
          <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, p: 2 }}>
            {/* Search and tabs */}
            <Stack spacing={2} sx={{ mb: 2 }}>
              <TextField
                placeholder="Поиск шаблонов..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                size="small"
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" />
                    </InputAdornment>
                  ),
                }}
              />
              <Tabs value={activeTab} onChange={(_, newValue) => setActiveTab(newValue)}>
                <Tab label="Все" />
                <Tab icon={<StarIcon />} iconPosition="start" label="Избранные" />
                <Tab icon={<ClockIcon />} iconPosition="start" label="Мои" />
              </Tabs>
            </Stack>

            {/* Template list */}
            <Box sx={{ flex: 1, overflow: 'auto', position: 'relative' }}>
              {isLoading ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
                  <CircularProgress />
                </Box>
              ) : filteredTemplates.length === 0 ? (
                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 400, color: 'text.secondary' }}>
                  <FileTextIcon sx={{ fontSize: 48, mb: 2, opacity: 0.5 }} />
                  <Typography>Шаблоны не найдены</Typography>
                </Box>
              ) : (
                <Grid container spacing={2}>
                  {filteredTemplates.map((template, idx) => (
                    <Grid item xs={12} sm={6} key={template.id}>
                      <Fade in timeout={300 + idx * 50}>
                        <Card
                        sx={{
                          cursor: 'pointer',
                          bgcolor: template.is_system ? 'action.hover' : 'background.paper',
                          height: '100%',
                          display: 'flex',
                          flexDirection: 'column',
                          '&:hover': {
                            borderColor: 'primary.main',
                            boxShadow: 2,
                          },
                        }}
                        variant="outlined"
                        onClick={() => setSelectedTemplate(template)}
                      >
                        <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                          <Stack spacing={1} sx={{ flex: 1 }}>
                            <Stack direction="row" spacing={1} alignItems="center">
                              <Typography variant="subtitle1" fontWeight={500} sx={{ flex: 1 }}>
                                {template.name}
                              </Typography>
                              {template.is_system && (
                                <Chip label="Системный" size="small" variant="outlined" />
                              )}
                              {template.is_featured && (
                                <StarIcon fontSize="small" color="primary" />
                              )}
                            </Stack>
                            {template.description && (
                              <Typography variant="body2" color="text.secondary" sx={{ 
                                display: '-webkit-box',
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: 'vertical',
                                overflow: 'hidden',
                              }}>
                                {template.description}
                              </Typography>
                            )}
                            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                              {template.category && (
                                <Chip
                                  icon={CATEGORY_ICONS[template.category]}
                                  label={CATEGORY_NAMES[template.category] || template.category}
                                  size="small"
                                  variant="outlined"
                                />
                              )}
                              <Typography variant="caption" color="text.secondary">
                                {template.columns.length} колонок
                              </Typography>
                              {template.usage_count && template.usage_count > 0 && (
                                <Typography variant="caption" color="text.secondary">
                                  Использован {template.usage_count} раз
                                </Typography>
                              )}
                            </Stack>
                            {/* Preview колонок (первые 5 названий) */}
                            <Box>
                              <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
                                Колонки:
                              </Typography>
                              <Stack direction="row" spacing={0.5} flexWrap="wrap">
                                {template.columns.slice(0, 5).map((col, idx) => (
                                  <Chip
                                    key={idx}
                                    label={col.column_label}
                                    size="small"
                                    variant="outlined"
                                    sx={{ fontSize: '0.65rem', height: 20 }}
                                  />
                                ))}
                                {template.columns.length > 5 && (
                                  <Chip
                                    label={`+${template.columns.length - 5}`}
                                    size="small"
                                    variant="outlined"
                                    sx={{ fontSize: '0.65rem', height: 20 }}
                                  />
                                )}
                              </Stack>
                            </Box>
                            
                            {template.tags && template.tags.length > 0 && (
                              <Stack direction="row" spacing={0.5} flexWrap="wrap">
                                {template.tags.slice(0, 3).map((tag, idx) => (
                                  <Chip key={idx} label={tag} size="small" variant="outlined" />
                                ))}
                              </Stack>
                            )}
                          </Stack>
                          
                          <Stack direction="row" spacing={1} sx={{ mt: 1, pt: 1, borderTop: 1, borderColor: 'divider' }}>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={(e) => {
                                e.stopPropagation()
                                setSelectedTemplate(template)
                              }}
                              sx={{ flex: 1 }}
                            >
                              Preview
                            </Button>
                            <Button
                              size="small"
                              variant="contained"
                              startIcon={<PlayIcon />}
                              onClick={(e) => {
                                e.stopPropagation()
                                handleApplyTemplate(template)
                              }}
                              disabled={isApplying}
                              sx={{ flex: 1 }}
                            >
                              Use template
                            </Button>
                            <IconButton
                              size="small"
                              onClick={(e) => {
                                e.stopPropagation()
                                toast.info("Добавление в избранное будет реализовано позже")
                              }}
                            >
                              <StarIcon fontSize="small" />
                            </IconButton>
                          </Stack>
                        </CardContent>
                      </Card>
                      </Fade>
                    </Grid>
                  ))}
                </Grid>
              )}
            </Box>
          </Box>
        </Box>
      </DialogContent>

      {/* Template Preview Dialog */}
      {selectedTemplate && (
        <Dialog
          open={!!selectedTemplate}
          onClose={() => setSelectedTemplate(null)}
          maxWidth="sm"
          fullWidth
        >
          <DialogTitle>
            <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
              <Typography variant="h6">{selectedTemplate.name}</Typography>
              <IconButton size="small" onClick={() => setSelectedTemplate(null)}>
                <CloseIcon />
              </IconButton>
            </Stack>
          </DialogTitle>
          <DialogContent>
            <Stack spacing={3}>
              {selectedTemplate.description && (
                <Typography variant="body2" color="text.secondary">
                  {selectedTemplate.description}
                </Typography>
              )}
              
              <Divider />
              
              <Box>
                <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 2 }}>
                  Колонки в шаблоне ({selectedTemplate.columns.length})
                </Typography>
                <Stack spacing={1}>
                  {selectedTemplate.columns.map((col, idx) => (
                    <Card key={idx} variant="outlined">
                      <CardContent>
                        <Stack spacing={1}>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Typography variant="body2" fontWeight={500}>
                              {col.column_label}
                            </Typography>
                            <Chip label={col.column_type} size="small" variant="outlined" />
                          </Stack>
                          <Typography variant="caption" color="text.secondary">
                            {col.prompt}
                          </Typography>
                        </Stack>
                      </CardContent>
                    </Card>
                  ))}
                </Stack>
              </Box>
            </Stack>
          </DialogContent>
          <Box sx={{ p: 2, display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
            <Button variant="outlined" onClick={() => setSelectedTemplate(null)}>
              Отмена
            </Button>
            <Button
              variant="contained"
              startIcon={<PlayIcon />}
              onClick={() => handleApplyTemplate(selectedTemplate)}
              disabled={isApplying}
            >
              {isApplying ? 'Применение...' : 'Применить шаблон'}
            </Button>
          </Box>
        </Dialog>
      )}
    </Dialog>
  )
}

