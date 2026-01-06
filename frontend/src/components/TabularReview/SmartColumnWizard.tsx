"use client"

import React, { useState } from "react"
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Stack,
  Typography,
  Paper,
  Tabs,
  Tab,
  Box,
  IconButton,
  CircularProgress,
} from "@mui/material"
import {
  Close as CloseIcon,
  AutoAwesome as AutoAwesomeIcon,
  Add as AddIcon,
  Delete as DeleteIcon,
} from "@mui/icons-material"
import { tabularReviewApi } from "@/services/tabularReviewApi"
import { toast } from "sonner"

interface SmartColumnWizardProps {
  open: boolean
  onClose: () => void
  reviewId: string
  onColumnCreated: () => void
}

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`smart-column-tabpanel-${index}`}
      aria-labelledby={`smart-column-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  )
}

export const SmartColumnWizard: React.FC<SmartColumnWizardProps> = ({
  open,
  onClose,
  reviewId,
  onColumnCreated,
}) => {
  const [tabValue, setTabValue] = useState(0)
  const [description, setDescription] = useState("")
  const [generating, setGenerating] = useState(false)
  const [preview, setPreview] = useState<any>(null)
  
  // Examples tab
  const [examples, setExamples] = useState<Array<{
    document_text: string
    expected_value: string
    context?: string
  }>>([
    { document_text: "", expected_value: "", context: "" },
    { document_text: "", expected_value: "", context: "" },
    { document_text: "", expected_value: "", context: "" },
  ])
  const [analyzing, setAnalyzing] = useState(false)

  const handleGenerateFromDescription = async () => {
    if (!description.trim()) {
      toast.error("Введите описание колонки")
      return
    }

    setGenerating(true)
    try {
      const result = await tabularReviewApi.createColumnFromDescription(reviewId, description)
      setPreview(result)
      toast.success("Колонка создана успешно!")
      onColumnCreated()
      onClose()
      // Reset
      setDescription("")
      setPreview(null)
    } catch (error: any) {
      toast.error("Ошибка создания колонки: " + (error.message || ""))
    } finally {
      setGenerating(false)
    }
  }

  const handleAnalyzeExamples = async () => {
    const validExamples = examples.filter(
      ex => ex.document_text.trim() && ex.expected_value.trim()
    )

    if (validExamples.length < 2) {
      toast.error("Добавьте хотя бы 2 примера")
      return
    }

    setAnalyzing(true)
    try {
      const result = await tabularReviewApi.createColumnFromExamples(reviewId, validExamples)
      setPreview(result)
      toast.success("Колонка создана на основе примеров!")
      onColumnCreated()
      onClose()
      // Reset
      setExamples([
        { document_text: "", expected_value: "", context: "" },
        { document_text: "", expected_value: "", context: "" },
        { document_text: "", expected_value: "", context: "" },
      ])
      setPreview(null)
    } catch (error: any) {
      toast.error("Ошибка создания колонки: " + (error.message || ""))
    } finally {
      setAnalyzing(false)
    }
  }

  const handleAddExample = () => {
    setExamples([...examples, { document_text: "", expected_value: "", context: "" }])
  }

  const handleRemoveExample = (index: number) => {
    if (examples.length > 2) {
      setExamples(examples.filter((_, i) => i !== index))
    } else {
      toast.error("Нужно минимум 2 примера")
    }
  }

  const handleExampleChange = (index: number, field: string, value: string) => {
    const newExamples = [...examples]
    newExamples[index] = { ...newExamples[index], [field]: value }
    setExamples(newExamples)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: {
          borderRadius: 2,
        },
      }}
    >
      <DialogTitle>
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
          <Stack direction="row" spacing={1} alignItems="center">
            <AutoAwesomeIcon color="primary" />
            <Typography variant="h6">Smart Column Creation</Typography>
          </Stack>
          <IconButton size="small" onClick={onClose}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Stack>
      </DialogTitle>

      <DialogContent>
        <Tabs value={tabValue} onChange={(_, newValue) => setTabValue(newValue)}>
          <Tab label="From Description" />
          <Tab label="From Examples" />
        </Tabs>

        <TabPanel value={tabValue} index={0}>
          <Stack spacing={3}>
            <Typography variant="body2" color="text.secondary">
              Опишите, какую информацию нужно извлечь из документов. AI автоматически определит тип колонки и создаст промпт.
            </Typography>

            <TextField
              label="Описание колонки"
              placeholder="Например: Найди пункт о неустойке и выпиши размер и условие начисления"
              multiline
              rows={4}
              fullWidth
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />

            {preview && (
              <Paper elevation={0} sx={{ p: 2, bgcolor: "action.hover" }}>
                <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
                  Предпросмотр:
                </Typography>
                <Stack spacing={1}>
                  <Typography variant="body2">
                    <strong>Название:</strong> {preview.column_label}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Тип:</strong> {preview.column_type}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Промпт:</strong> {preview.prompt}
                  </Typography>
                </Stack>
              </Paper>
            )}

            <Button
              variant="contained"
              onClick={handleGenerateFromDescription}
              disabled={generating || !description.trim()}
              startIcon={generating ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}
              fullWidth
            >
              {generating ? "Создание..." : "Create Column"}
            </Button>
          </Stack>
        </TabPanel>

        <TabPanel value={tabValue} index={1}>
          <Stack spacing={3}>
            <Typography variant="body2" color="text.secondary">
              Покажите 3-5 примеров того, как должна выглядеть извлеченная информация. AI проанализирует паттерны и создаст колонку.
            </Typography>

            <Stack spacing={2}>
              {examples.map((example, index) => (
                <Paper key={index} elevation={0} sx={{ p: 2, border: 1, borderColor: "divider" }}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <Typography variant="subtitle2">Пример {index + 1}</Typography>
                    {examples.length > 2 && (
                      <IconButton
                        size="small"
                        onClick={() => handleRemoveExample(index)}
                        sx={{ ml: "auto" }}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    )}
                  </Stack>
                  <Stack spacing={2}>
                    <TextField
                      label="Текст документа"
                      placeholder="Вставьте фрагмент документа..."
                      multiline
                      rows={3}
                      fullWidth
                      size="small"
                      value={example.document_text}
                      onChange={(e) => handleExampleChange(index, "document_text", e.target.value)}
                    />
                    <TextField
                      label="Ожидаемое значение"
                      placeholder="Какое значение должно быть извлечено?"
                      fullWidth
                      size="small"
                      value={example.expected_value}
                      onChange={(e) => handleExampleChange(index, "expected_value", e.target.value)}
                    />
                    <TextField
                      label="Контекст (опционально)"
                      placeholder="Дополнительный контекст..."
                      fullWidth
                      size="small"
                      value={example.context || ""}
                      onChange={(e) => handleExampleChange(index, "context", e.target.value)}
                    />
                  </Stack>
                </Paper>
              ))}
            </Stack>

            <Button
              variant="outlined"
              startIcon={<AddIcon />}
              onClick={handleAddExample}
              sx={{ textTransform: "none" }}
            >
              Добавить пример
            </Button>

            {preview && (
              <Paper elevation={0} sx={{ p: 2, bgcolor: "action.hover" }}>
                <Typography variant="subtitle2" fontWeight={600} sx={{ mb: 1 }}>
                  Предпросмотр:
                </Typography>
                <Stack spacing={1}>
                  <Typography variant="body2">
                    <strong>Название:</strong> {preview.column_label}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Тип:</strong> {preview.column_type}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Промпт:</strong> {preview.prompt}
                  </Typography>
                </Stack>
              </Paper>
            )}

            <Button
              variant="contained"
              onClick={handleAnalyzeExamples}
              disabled={analyzing || examples.filter(ex => ex.document_text.trim() && ex.expected_value.trim()).length < 2}
              startIcon={analyzing ? <CircularProgress size={16} /> : <AutoAwesomeIcon />}
              fullWidth
            >
              {analyzing ? "Анализ..." : "Analyze Examples & Create Column"}
            </Button>
          </Stack>
        </TabPanel>
      </DialogContent>

      <DialogActions sx={{ p: 2, borderTop: 1, borderColor: "divider" }}>
        <Button onClick={onClose}>Cancel</Button>
      </DialogActions>
    </Dialog>
  )
}

