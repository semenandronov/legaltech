import {
  Card,
  CardContent,
  CardHeader,
  Typography,
  Box,
  Stack,
  LinearProgress,
  Chip,
  Fade,
} from '@mui/material'
import {
  Psychology as BotIcon,
  CheckCircle as CheckCircleIcon,
  Cancel as XCircleIcon,
  AccessTime as ClockIcon,
  ErrorOutline as AlertTriangleIcon,
  ChevronRight as ChevronRightIcon,
  Refresh as Loader2Icon,
} from '@mui/icons-material'

export interface PlanStep {
  step_id: string
  agent_name: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped'
  reasoning?: string
  error?: string
}

export interface AgentLog {
  id: string
  agent_name: string
  log_type: 'start' | 'progress' | 'result' | 'error' | 'decision'
  message: string
  timestamp: string
}

interface AgentProgressViewProps {
  steps: PlanStep[]
  logs?: AgentLog[]
  currentStepId?: string
  isRunning?: boolean
  className?: string
}

const AGENT_NAMES: Record<string, string> = {
  timeline: 'Хронология',
  key_facts: 'Ключевые факты',
  discrepancy: 'Противоречия',
  risk: 'Риски',
  summary: 'Резюме',
  entity_extraction: 'Сущности',
  classification: 'Классификация',
  supervisor: 'Координатор',
}

const STATUS_CONFIG = {
  pending: {
    icon: ClockIcon,
    color: 'text.secondary',
    bgcolor: 'action.hover',
    label: 'Ожидает',
  },
  in_progress: {
    icon: Loader2Icon,
    color: 'primary.main',
    bgcolor: 'primary.light',
    label: 'Выполняется',
  },
  completed: {
    icon: CheckCircleIcon,
    color: 'success.main',
    bgcolor: 'success.light',
    label: 'Завершено',
  },
  failed: {
    icon: XCircleIcon,
    color: 'error.main',
    bgcolor: 'error.light',
    label: 'Ошибка',
  },
  skipped: {
    icon: AlertTriangleIcon,
    color: 'warning.main',
    bgcolor: 'warning.light',
    label: 'Пропущено',
  },
}

export function AgentProgressView({
  steps,
  logs = [],
  currentStepId,
  isRunning = false,
  className,
}: AgentProgressViewProps) {
  const completedCount = steps.filter(s => s.status === 'completed').length
  const totalCount = steps.length
  const progress = totalCount > 0 ? (completedCount / totalCount) * 100 : 0

  return (
    <Card sx={{ width: '100%', ...(className ? {} : {}) }} className={className}>
      <CardHeader
        title={
          <Stack direction="row" spacing={1} alignItems="center">
            <BotIcon />
            <Typography variant="h6">Прогресс анализа</Typography>
          </Stack>
        }
        action={
          isRunning && (
            <Chip
              icon={<Loader2Icon sx={{ animation: 'spin 1s linear infinite' }} />}
              label="Выполняется"
              size="small"
              color="primary"
              variant="outlined"
            />
          )
        }
      />
      <CardContent>
        <Stack spacing={1} sx={{ mb: 2 }}>
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="body2" color="text.secondary">
              {completedCount} из {totalCount} шагов
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {Math.round(progress)}%
            </Typography>
          </Stack>
          <LinearProgress variant="determinate" value={progress} />
        </Stack>

        <Box sx={{ maxHeight: 400, overflow: 'auto' }}>
          <Stack spacing={1}>
            {steps.map((step, index) => {
              const config = STATUS_CONFIG[step.status]
              const Icon = config.icon
              const isActive = step.step_id === currentStepId
              const agentName = AGENT_NAMES[step.agent_name] || step.agent_name

              return (
                <Fade
                  key={step.step_id}
                  in
                  style={{
                    transitionDelay: `${index * 50}ms`,
                  }}
                >
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 1.5,
                      p: 1.5,
                      borderRadius: 1,
                      border: 1,
                      borderColor: isActive ? 'primary.main' : 'divider',
                      bgcolor: isActive
                        ? 'primary.light'
                        : config.bgcolor,
                    }}
                  >
                    <Box
                      sx={{
                        flexShrink: 0,
                        mt: 0.5,
                        color: config.color,
                      }}
                    >
                      <Icon
                        sx={{
                          fontSize: 20,
                          ...(step.status === 'in_progress' ? {
                            animation: 'spin 1s linear infinite',
                            '@keyframes spin': {
                              '0%': { transform: 'rotate(0deg)' },
                              '100%': { transform: 'rotate(360deg)' },
                            },
                          } : {}),
                        }}
                      />
                    </Box>

                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 0.5 }}>
                        <Typography variant="body2" fontWeight={500}>
                          {agentName}
                        </Typography>
                        <Chip label={config.label} size="small" variant="outlined" />
                      </Stack>
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
                        {step.description}
                      </Typography>
                      {step.error && (
                        <Typography variant="body2" color="error.main" sx={{ mt: 0.5 }}>
                          {step.error}
                        </Typography>
                      )}
                      {step.reasoning && (
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ mt: 0.5, display: 'block', fontStyle: 'italic' }}
                        >
                          {step.reasoning}
                        </Typography>
                      )}
                    </Box>

                    {index < steps.length - 1 && (
                      <ChevronRightIcon fontSize="small" color="action" sx={{ flexShrink: 0, mt: 0.5 }} />
                    )}
                  </Box>
                </Fade>
              )
            })}
          </Stack>

          {/* Logs section */}
          {logs.length > 0 && (
            <Box sx={{ mt: 2, pt: 2, borderTop: 1, borderColor: 'divider' }}>
              <Typography variant="body2" fontWeight={500} color="text.secondary" sx={{ mb: 1 }}>
                Журнал выполнения
              </Typography>
              <Stack spacing={0.5}>
                {logs.slice(-10).map((log) => (
                  <Stack
                    key={log.id}
                    direction="row"
                    spacing={1}
                    alignItems="flex-start"
                    flexWrap="wrap"
                  >
                    <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </Typography>
                    <Chip
                      label={AGENT_NAMES[log.agent_name] || log.agent_name}
                      size="small"
                      variant="outlined"
                      sx={{ height: 18, fontSize: '0.65rem' }}
                    />
                    <Typography
                      variant="caption"
                      sx={{
                        color:
                          log.log_type === 'error'
                            ? 'error.main'
                            : log.log_type === 'decision'
                            ? 'primary.main'
                            : 'text.primary',
                      }}
                    >
                      {log.message}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            </Box>
          )}
        </Box>
      </CardContent>
    </Card>
  )
}

export default AgentProgressView
