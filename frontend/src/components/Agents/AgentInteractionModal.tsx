import { useState, useEffect } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  RadioGroup,
  FormControlLabel,
  Radio,
  Typography,
  Box,
  Stack,
  LinearProgress,
  Chip,
  Card,
  CardContent,
  Fade,
  Alert,
} from '@mui/material'
import {
  Psychology as BotIcon,
  AccessTime as ClockIcon,
  ErrorOutline as AlertCircleIcon,
  CheckCircleOutline as CheckCircleIcon,
  Cancel as XCircleIcon,
} from '@mui/icons-material'

export interface AgentQuestion {
  request_id: string
  agent_name: string
  question_type: 'clarification' | 'confirmation' | 'choice'
  question_text: string
  options?: { id: string; label: string; description?: string }[]
  context?: string
}

interface AgentInteractionModalProps {
  question: AgentQuestion | null
  isOpen: boolean
  onClose: () => void
  onSubmit: (requestId: string, response: string) => void
  timeoutSeconds?: number
}

const AGENT_NAMES: Record<string, string> = {
  timeline: 'Хронология',
  key_facts: 'Ключевые факты',
  discrepancy: 'Противоречия',
  risk: 'Риски',
  summary: 'Резюме',
  entity_extraction: 'Извлечение сущностей',
  classification: 'Классификация',
  supervisor: 'Координатор',
}

const AGENT_COLORS: Record<string, 'primary' | 'success' | 'warning' | 'error' | 'info'> = {
  timeline: 'info',
  key_facts: 'success',
  discrepancy: 'warning',
  risk: 'error',
  summary: 'primary',
  entity_extraction: 'info',
  classification: 'primary',
  supervisor: 'primary',
}

export function AgentInteractionModal({
  question,
  isOpen,
  onClose,
  onSubmit,
  timeoutSeconds = 300,
}: AgentInteractionModalProps) {
  const [response, setResponse] = useState('')
  const [selectedOption, setSelectedOption] = useState<string>('')
  const [timeLeft, setTimeLeft] = useState(timeoutSeconds)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Reset state when question changes
  useEffect(() => {
    if (question) {
      setResponse('')
      setSelectedOption('')
      setTimeLeft(timeoutSeconds)
      setIsSubmitting(false)
    }
  }, [question, timeoutSeconds])

  // Countdown timer
  useEffect(() => {
    if (!isOpen || !question) return

    const interval = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          clearInterval(interval)
          onClose()
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(interval)
  }, [isOpen, question, onClose])

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const handleSubmit = async () => {
    if (!question || !isValid()) return

    setIsSubmitting(true)
    try {
      const finalResponse = question.question_type === 'clarification' ? response : selectedOption
      await onSubmit(question.request_id, finalResponse)
      onClose()
    } catch (error) {
      console.error('Error submitting response:', error)
    } finally {
      setIsSubmitting(false)
    }
  }

  const isValid = () => {
    if (question?.question_type === 'clarification') {
      return response.trim().length > 0
    }
    return selectedOption !== ''
  }

  if (!question) return null

  const agentName = AGENT_NAMES[question.agent_name] || question.agent_name
  const agentColor = AGENT_COLORS[question.agent_name] || 'primary'
  const progress = (timeLeft / timeoutSeconds) * 100

  return (
    <Dialog open={isOpen} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        <Stack direction="row" spacing={2} alignItems="center">
          <Box
            sx={{
              p: 1,
              borderRadius: '50%',
              bgcolor: `${agentColor}.main`,
              color: 'white',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <BotIcon />
          </Box>
          <Box>
            <Typography variant="h6">Вопрос от агента</Typography>
            <Chip label={agentName} size="small" color={agentColor} sx={{ mt: 0.5 }} />
          </Box>
        </Stack>
      </DialogTitle>

      <DialogContent>
        <Stack spacing={3}>
          {/* Timer */}
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <ClockIcon fontSize="small" color="action" />
              <Typography
                variant="body2"
                color={timeLeft < 60 ? 'error' : 'text.secondary'}
                fontWeight={timeLeft < 60 ? 600 : 400}
              >
                {formatTime(timeLeft)}
              </Typography>
            </Stack>
            <LinearProgress
              variant="determinate"
              value={progress}
              sx={{ width: 100 }}
              color={timeLeft < 60 ? 'error' : 'primary'}
            />
          </Box>

          {/* Question */}
          <Card variant="outlined">
            <CardContent>
              <Typography variant="body1" sx={{ lineHeight: 1.75 }}>
                {question.question_text}
              </Typography>
            </CardContent>
          </Card>

          {/* Context */}
          {question.context && (
            <Alert severity="info" icon={<AlertCircleIcon />}>
              <Typography variant="subtitle2" sx={{ mb: 0.5, fontWeight: 600 }}>
                Контекст
              </Typography>
              <Typography variant="body2">{question.context}</Typography>
            </Alert>
          )}

          {/* Response Input */}
          <Fade in>
            <Box>
              {question.question_type === 'clarification' && (
                <TextField
                  fullWidth
                  multiline
                  rows={4}
                  placeholder="Введите ваш ответ..."
                  value={response}
                  onChange={(e) => setResponse(e.target.value)}
                  autoFocus
                />
              )}

              {question.question_type === 'confirmation' && (
                <Stack direction="row" spacing={2}>
                  <Button
                    variant={selectedOption === 'yes' ? 'contained' : 'outlined'}
                    fullWidth
                    size="large"
                    onClick={() => setSelectedOption('yes')}
                    startIcon={<CheckCircleIcon />}
                    color="success"
                  >
                    Да
                  </Button>
                  <Button
                    variant={selectedOption === 'no' ? 'contained' : 'outlined'}
                    fullWidth
                    size="large"
                    onClick={() => setSelectedOption('no')}
                    startIcon={<XCircleIcon />}
                    color="error"
                  >
                    Нет
                  </Button>
                </Stack>
              )}

              {question.question_type === 'choice' && question.options && (
                <RadioGroup
                  value={selectedOption}
                  onChange={(e) => setSelectedOption(e.target.value)}
                >
                  {question.options.map((option) => (
                    <Card
                      key={option.id}
                      variant="outlined"
                      sx={{
                        mb: 1,
                        cursor: 'pointer',
                        borderColor: selectedOption === option.id ? 'primary.main' : 'divider',
                        bgcolor: selectedOption === option.id ? 'action.selected' : 'background.paper',
                        '&:hover': {
                          bgcolor: 'action.hover',
                        },
                      }}
                      onClick={() => setSelectedOption(option.id)}
                    >
                      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                        <FormControlLabel
                          value={option.id}
                          control={<Radio />}
                          label={
                            <Box>
                              <Typography variant="body2" fontWeight={500}>
                                {option.label}
                              </Typography>
                              {option.description && (
                                <Typography variant="caption" color="text.secondary">
                                  {option.description}
                                </Typography>
                              )}
                            </Box>
                          }
                        />
                      </CardContent>
                    </Card>
                  ))}
                </RadioGroup>
              )}
            </Box>
          </Fade>
        </Stack>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} disabled={isSubmitting}>
          Пропустить
        </Button>
        <Button
          onClick={handleSubmit}
          disabled={!isValid() || isSubmitting}
          variant="contained"
        >
          {isSubmitting ? 'Отправка...' : 'Отправить'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default AgentInteractionModal
