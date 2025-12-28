import React, { useState, useEffect, useMemo } from 'react'
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
  CardHeader,
  InputAdornment,
  Divider,
  CircularProgress,
  Fade,
  Grow,
} from '@mui/material'
import {
  MenuBook as BookOpenIcon,
  Search as SearchIcon,
  Star as StarIcon,
  AccessTime as ClockIcon,
  Description as FileTextIcon,
  Gavel as GavelIcon,
  Shield as ShieldIcon,
  FolderOpen as FolderOpenIcon,
  ContentCopy as CopyIcon,
  PlayArrow as PlayIcon,
  AutoAwesome as SparklesIcon,
  ArrowBack as ArrowBackIcon,
} from '@mui/icons-material'
import api from '@/services/api'

export interface PromptVariable {
  name: string
  type: string
  description?: string
  required: boolean
}

export interface PromptTemplate {
  id: string
  title: string
  description?: string
  prompt_text: string
  category: string
  variables: PromptVariable[]
  tags: string[]
  is_public: boolean
  is_system: boolean
  usage_count: number
}

interface PromptLibraryProps {
  onSelectPrompt: (prompt: string) => void
  trigger?: React.ReactNode
  isOpen?: boolean
  onClose?: () => void
}

const CATEGORY_ICONS: Record<string, React.ReactElement> = {
  contract: <FileTextIcon fontSize="small" />,
  litigation: <GavelIcon fontSize="small" />,
  due_diligence: <SearchIcon fontSize="small" />,
  research: <BookOpenIcon fontSize="small" />,
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

export const PromptLibrary = React.memo(({ onSelectPrompt, trigger, isOpen: externalIsOpen, onClose: externalOnClose }: PromptLibraryProps) => {
  const [internalIsOpen, setInternalIsOpen] = useState(false)
  const isOpen = externalIsOpen !== undefined ? externalIsOpen : internalIsOpen
  const setIsOpen = externalOnClose ? (() => externalOnClose()) : setInternalIsOpen
  const [prompts, setPrompts] = useState<PromptTemplate[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptTemplate | null>(null)
  const [variableValues, setVariableValues] = useState<Record<string, string>>({})
  const [isLoading, setIsLoading] = useState(false)
  const [activeTab, setActiveTab] = useState(0) // 0: all, 1: popular, 2: my

  useEffect(() => {
    if (isOpen) {
      loadPrompts()
    }
  }, [isOpen, selectedCategory, searchQuery])

  const loadPrompts = async () => {
    setIsLoading(true)
    try {
      const params: Record<string, string> = {}
      if (selectedCategory) params.category = selectedCategory
      if (searchQuery) params.search = searchQuery
      
      const response = await api.get('/prompts/', { params })
      setPrompts(response.data)
    } catch (error) {
      console.error('Error loading prompts:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleSelectPrompt = (prompt: PromptTemplate) => {
    setSelectedPrompt(prompt)
    // Initialize variable values
    const initialValues: Record<string, string> = {}
    prompt.variables.forEach(v => {
      initialValues[v.name] = ''
    })
    setVariableValues(initialValues)
  }

  const handleUsePrompt = async () => {
    if (!selectedPrompt) return

    try {
      const response = await api.post(`/prompts/${selectedPrompt.id}/use`, {
        variables: variableValues
      })
      
      onSelectPrompt(response.data.rendered_prompt)
      setIsOpen(false)
      setSelectedPrompt(null)
      setVariableValues({})
    } catch (error) {
      console.error('Error using prompt:', error)
    }
  }

  const handleDuplicatePrompt = async (promptId: string) => {
    try {
      await api.post(`/prompts/${promptId}/duplicate`)
      loadPrompts()
    } catch (error) {
      console.error('Error duplicating prompt:', error)
    }
  }

  const categories = Object.keys(CATEGORY_NAMES)

  const filteredPrompts = useMemo(() => {
    return prompts.filter(p => {
      if (activeTab === 1) return p.usage_count > 0 // popular
      if (activeTab === 2) return !p.is_system && !p.is_public // my
      return true // all
    })
  }, [prompts, activeTab])

  return (
    <>
      {trigger ? (
        <Box onClick={() => setIsOpen(true)}>{trigger}</Box>
      ) : (
        <Button
          variant="outlined"
          size="small"
          startIcon={<BookOpenIcon />}
          onClick={() => setIsOpen(true)}
        >
          Промпты
        </Button>
      )}
      
      <Dialog open={isOpen} onClose={() => setIsOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          <Stack direction="row" spacing={1} alignItems="center">
            <SparklesIcon color="primary" />
            <Typography variant="h6">Библиотека промптов</Typography>
          </Stack>
        </DialogTitle>
        <Typography variant="body2" color="text.secondary" sx={{ px: 3, pb: 2 }}>
          Выберите готовый шаблон или создайте свой
        </Typography>

        <DialogContent dividers sx={{ p: 0 }}>
          <Box sx={{ display: 'flex', height: 600 }}>
            {/* Left sidebar - categories */}
            <Box
              sx={{
                width: 200,
                flexShrink: 0,
                borderRight: 1,
                borderColor: 'divider',
                p: 2,
              }}
            >
              <Stack spacing={0.5}>
                <Button
                  variant={selectedCategory === null ? 'contained' : 'text'}
                  fullWidth
                  onClick={() => setSelectedCategory(null)}
                  sx={{ justifyContent: 'flex-start' }}
                >
                  Все категории
                </Button>
                {categories.map((cat) => (
                  <Button
                    key={cat}
                    variant={selectedCategory === cat ? 'contained' : 'text'}
                    fullWidth
                    startIcon={CATEGORY_ICONS[cat]}
                    onClick={() => setSelectedCategory(cat)}
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
                  placeholder="Поиск промптов..."
                  value={searchQuery}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(e.target.value)}
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
                  <Tab icon={<StarIcon />} iconPosition="start" label="Популярные" />
                  <Tab icon={<ClockIcon />} iconPosition="start" label="Мои" />
                </Tabs>
              </Stack>

              {/* Prompt list or detail view */}
              <Box sx={{ flex: 1, overflow: 'auto', position: 'relative' }}>
                {selectedPrompt ? (
                  <Grow in={!!selectedPrompt}>
                    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                      <Button
                        variant="text"
                        size="small"
                        startIcon={<ArrowBackIcon />}
                        onClick={() => setSelectedPrompt(null)}
                        sx={{ alignSelf: 'flex-start', mb: 2 }}
                      >
                        Назад к списку
                      </Button>
                      
                      <Card sx={{ flex: 1, mb: 2 }}>
                        <CardHeader
                          title={selectedPrompt.title}
                          subheader={selectedPrompt.description}
                          action={
                            <Chip
                              label={CATEGORY_NAMES[selectedPrompt.category]}
                              size="small"
                              variant="outlined"
                            />
                          }
                        />
                        <CardContent>
                          <Stack spacing={3}>
                            {/* Variables */}
                            {selectedPrompt.variables.length > 0 && (
                              <Box>
                                <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 2 }}>
                                  Параметры
                                </Typography>
                                <Stack spacing={2}>
                                  {selectedPrompt.variables.map((variable) => (
                                    <Box key={variable.name}>
                                      <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
                                        {variable.description || variable.name}
                                        {variable.required && (
                                          <Typography component="span" color="error.main"> *</Typography>
                                        )}
                                      </Typography>
                                      <TextField
                                        fullWidth
                                        size="small"
                                        value={variableValues[variable.name] || ''}
                                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setVariableValues({
                                          ...variableValues,
                                          [variable.name]: e.target.value
                                        })}
                                        placeholder={`Введите ${variable.name}`}
                                      />
                                    </Box>
                                  ))}
                                </Stack>
                              </Box>
                            )}
                            
                            <Divider />
                            
                            {/* Preview */}
                            <Box>
                              <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
                                Шаблон промпта
                              </Typography>
                              <Box
                                sx={{
                                  bgcolor: 'action.hover',
                                  borderRadius: 1,
                                  p: 2,
                                  whiteSpace: 'pre-wrap',
                                }}
                              >
                                <Typography variant="body2" component="pre" sx={{ m: 0, fontFamily: 'inherit' }}>
                                  {selectedPrompt.prompt_text}
                                </Typography>
                              </Box>
                            </Box>

                            {/* Tags */}
                            {selectedPrompt.tags.length > 0 && (
                              <Box>
                                <Stack direction="row" spacing={1} flexWrap="wrap">
                                  {selectedPrompt.tags.map((tag) => (
                                    <Chip key={tag} label={tag} size="small" variant="outlined" />
                                  ))}
                                </Stack>
                              </Box>
                            )}
                          </Stack>
                        </CardContent>
                      </Card>

                      <Stack direction="row" spacing={2}>
                        <Button
                          variant="outlined"
                          startIcon={<CopyIcon />}
                          onClick={() => handleDuplicatePrompt(selectedPrompt.id)}
                        >
                          Скопировать
                        </Button>
                        <Button
                          variant="contained"
                          fullWidth
                          startIcon={<PlayIcon />}
                          onClick={handleUsePrompt}
                        >
                          Использовать
                        </Button>
                      </Stack>
                    </Box>
                  </Grow>
                ) : (
                  <Fade in={!selectedPrompt}>
                    <Box>
                      {isLoading ? (
                        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 400 }}>
                          <CircularProgress />
                        </Box>
                      ) : filteredPrompts.length === 0 ? (
                        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 400, color: 'text.secondary' }}>
                          <BookOpenIcon sx={{ fontSize: 48, mb: 2, opacity: 0.5 }} />
                          <Typography>Промпты не найдены</Typography>
                        </Box>
                      ) : (
                        <Stack spacing={2} sx={{ pr: 1 }}>
                          {filteredPrompts.map((prompt) => (
                            <Card
                              key={prompt.id}
                              sx={{
                                cursor: 'pointer',
                                bgcolor: prompt.is_system ? 'action.hover' : 'background.paper',
                                '&:hover': {
                                  borderColor: 'primary.main',
                                  boxShadow: 2,
                                },
                              }}
                              variant="outlined"
                              onClick={() => handleSelectPrompt(prompt)}
                            >
                              <CardContent>
                                <Stack spacing={1}>
                                  <Stack direction="row" spacing={1} alignItems="center">
                                    <Typography variant="subtitle1" fontWeight={500} noWrap sx={{ flex: 1 }}>
                                      {prompt.title}
                                    </Typography>
                                    {prompt.is_system && (
                                      <Chip label="Системный" size="small" variant="outlined" />
                                    )}
                                  </Stack>
                                  {prompt.description && (
                                    <Typography variant="body2" color="text.secondary" sx={{ 
                                      display: '-webkit-box',
                                      WebkitLineClamp: 2,
                                      WebkitBoxOrient: 'vertical',
                                      overflow: 'hidden',
                                    }}>
                                      {prompt.description}
                                    </Typography>
                                  )}
                                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                                    <Chip
                                      icon={CATEGORY_ICONS[prompt.category]}
                                      label={CATEGORY_NAMES[prompt.category]}
                                      size="small"
                                      variant="outlined"
                                    />
                                    {prompt.usage_count > 0 && (
                                      <Typography variant="caption" color="text.secondary">
                                        Использован {prompt.usage_count} раз
                                      </Typography>
                                    )}
                                  </Stack>
                                </Stack>
                              </CardContent>
                            </Card>
                          ))}
                        </Stack>
                      )}
                    </Box>
                  </Fade>
                )}
              </Box>
            </Box>
          </Box>
        </DialogContent>
      </Dialog>
    </>
  )
})

PromptLibrary.displayName = 'PromptLibrary'

export default PromptLibrary
