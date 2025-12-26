import React, { useState, useEffect } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/UI/dialog'
import { Button } from '@/components/UI/Button'
import { Input } from '@/components/UI/input'
import { Badge } from '@/components/UI/Badge'
import { ScrollArea } from '@/components/UI/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/UI/tabs'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/UI/card'
import { 
  BookOpen, 
  Search, 
  Star, 
  Clock, 
  FileText, 
  Gavel, 
  SearchIcon,
  Shield,
  FolderOpen,
  Copy,
  Play,
  Plus,
  Sparkles
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'
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
}

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  contract: <FileText className="h-4 w-4" />,
  litigation: <Gavel className="h-4 w-4" />,
  due_diligence: <SearchIcon className="h-4 w-4" />,
  research: <BookOpen className="h-4 w-4" />,
  compliance: <Shield className="h-4 w-4" />,
  custom: <FolderOpen className="h-4 w-4" />,
}

const CATEGORY_NAMES: Record<string, string> = {
  contract: 'Договоры',
  litigation: 'Судебные дела',
  due_diligence: 'Due Diligence',
  research: 'Исследование',
  compliance: 'Compliance',
  custom: 'Прочее',
}

export function PromptLibrary({ onSelectPrompt, trigger }: PromptLibraryProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [prompts, setPrompts] = useState<PromptTemplate[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptTemplate | null>(null)
  const [variableValues, setVariableValues] = useState<Record<string, string>>({})
  const [isLoading, setIsLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('all')

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

  const filteredPrompts = prompts.filter(p => {
    if (activeTab === 'my') return !p.is_system && !p.is_public
    if (activeTab === 'popular') return p.usage_count > 0
    return true
  })

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" size="sm" className="gap-2">
            <BookOpen className="h-4 w-4" />
            Промпты
          </Button>
        )}
      </DialogTrigger>
      
      <DialogContent className="sm:max-w-[800px] max-h-[80vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Библиотека промптов
          </DialogTitle>
          <DialogDescription>
            Выберите готовый шаблон или создайте свой
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-4 h-[500px]">
          {/* Left sidebar - categories */}
          <div className="w-48 flex-shrink-0 border-r pr-4">
            <div className="space-y-1">
              <Button
                variant={selectedCategory === null ? "secondary" : "ghost"}
                className="w-full justify-start"
                onClick={() => setSelectedCategory(null)}
              >
                Все категории
              </Button>
              {categories.map((cat) => (
                <Button
                  key={cat}
                  variant={selectedCategory === cat ? "secondary" : "ghost"}
                  className="w-full justify-start gap-2"
                  onClick={() => setSelectedCategory(cat)}
                >
                  {CATEGORY_ICONS[cat]}
                  {CATEGORY_NAMES[cat]}
                </Button>
              ))}
            </div>
          </div>

          {/* Main content */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Search and tabs */}
            <div className="flex gap-3 mb-4">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Поиск промптов..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>
              <Tabs value={activeTab} onValueChange={setActiveTab}>
                <TabsList>
                  <TabsTrigger value="all">Все</TabsTrigger>
                  <TabsTrigger value="popular" className="gap-1">
                    <Star className="h-3 w-3" />
                    Популярные
                  </TabsTrigger>
                  <TabsTrigger value="my" className="gap-1">
                    <Clock className="h-3 w-3" />
                    Мои
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </div>

            {/* Prompt list or detail view */}
            <AnimatePresence mode="wait">
              {selectedPrompt ? (
                <motion.div
                  key="detail"
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  className="flex-1 flex flex-col"
                >
                  <Button
                    variant="ghost"
                    size="sm"
                    className="self-start mb-3"
                    onClick={() => setSelectedPrompt(null)}
                  >
                    ← Назад к списку
                  </Button>
                  
                  <Card className="flex-1">
                    <CardHeader>
                      <div className="flex items-start justify-between">
                        <div>
                          <CardTitle>{selectedPrompt.title}</CardTitle>
                          <CardDescription>{selectedPrompt.description}</CardDescription>
                        </div>
                        <Badge variant="outline">
                          {CATEGORY_NAMES[selectedPrompt.category]}
                        </Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {/* Variables */}
                      {selectedPrompt.variables.length > 0 && (
                        <div className="space-y-3">
                          <h4 className="text-sm font-medium">Параметры</h4>
                          {selectedPrompt.variables.map((variable) => (
                            <div key={variable.name} className="space-y-1">
                              <label className="text-sm text-muted-foreground">
                                {variable.description || variable.name}
                                {variable.required && <span className="text-destructive"> *</span>}
                              </label>
                              <Input
                                value={variableValues[variable.name] || ''}
                                onChange={(e) => setVariableValues({
                                  ...variableValues,
                                  [variable.name]: e.target.value
                                })}
                                placeholder={`Введите ${variable.name}`}
                              />
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {/* Preview */}
                      <div className="space-y-2">
                        <h4 className="text-sm font-medium">Шаблон промпта</h4>
                        <div className="bg-muted rounded-lg p-3 text-sm whitespace-pre-wrap">
                          {selectedPrompt.prompt_text}
                        </div>
                      </div>

                      {/* Tags */}
                      {selectedPrompt.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {selectedPrompt.tags.map((tag) => (
                            <Badge key={tag} variant="secondary" className="text-xs">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  <div className="flex gap-2 mt-4">
                    <Button variant="outline" onClick={() => handleDuplicatePrompt(selectedPrompt.id)}>
                      <Copy className="mr-2 h-4 w-4" />
                      Скопировать
                    </Button>
                    <Button className="flex-1" onClick={handleUsePrompt}>
                      <Play className="mr-2 h-4 w-4" />
                      Использовать
                    </Button>
                  </div>
                </motion.div>
              ) : (
                <motion.div
                  key="list"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex-1"
                >
                  <ScrollArea className="h-[400px]">
                    {isLoading ? (
                      <div className="flex items-center justify-center h-full">
                        <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
                      </div>
                    ) : filteredPrompts.length === 0 ? (
                      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                        <BookOpen className="h-12 w-12 mb-2 opacity-50" />
                        <p>Промпты не найдены</p>
                      </div>
                    ) : (
                      <div className="grid gap-3 pr-4">
                        {filteredPrompts.map((prompt) => (
                          <Card
                            key={prompt.id}
                            className={cn(
                              "cursor-pointer transition-all hover:border-primary/50",
                              prompt.is_system && "bg-muted/30"
                            )}
                            onClick={() => handleSelectPrompt(prompt)}
                          >
                            <CardContent className="p-4">
                              <div className="flex items-start justify-between gap-4">
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2 mb-1">
                                    <h3 className="font-medium truncate">{prompt.title}</h3>
                                    {prompt.is_system && (
                                      <Badge variant="secondary" className="text-xs">
                                        Системный
                                      </Badge>
                                    )}
                                  </div>
                                  {prompt.description && (
                                    <p className="text-sm text-muted-foreground line-clamp-2">
                                      {prompt.description}
                                    </p>
                                  )}
                                  <div className="flex items-center gap-2 mt-2">
                                    <Badge variant="outline" className="text-xs">
                                      {CATEGORY_ICONS[prompt.category]}
                                      <span className="ml-1">{CATEGORY_NAMES[prompt.category]}</span>
                                    </Badge>
                                    {prompt.usage_count > 0 && (
                                      <span className="text-xs text-muted-foreground">
                                        Использован {prompt.usage_count} раз
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </CardContent>
                          </Card>
                        ))}
                      </div>
                    )}
                  </ScrollArea>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default PromptLibrary

