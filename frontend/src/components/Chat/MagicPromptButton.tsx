import { useState } from 'react'
import {
  Button,
  Popover,
  Box,
  Typography,
  Stack,
  Divider,
  Chip,
  CircularProgress,
  Alert,
  Fade,
  Grow,
} from '@mui/material'
import {
  AutoAwesome as SparklesIcon,
  Check as CheckIcon,
  Close as CloseIcon,
  Lightbulb as LightbulbIcon,
  ArrowForward as ArrowRightIcon,
} from '@mui/icons-material'
import api from '@/services/api'

interface MagicPromptButtonProps {
  prompt: string
  onImprovedPrompt: (improved: string) => void
  disabled?: boolean
  className?: string
}

interface ImprovementResult {
  improved_prompt: string
  suggestions: string[]
  reasoning: string
  improvements_made: string[]
}

export function MagicPromptButton({
  prompt,
  onImprovedPrompt,
  disabled = false,
  className,
}: MagicPromptButtonProps) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [result, setResult] = useState<ImprovementResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const isOpen = Boolean(anchorEl)
  const isDisabled = disabled || !prompt.trim()

  const handleClick = async (event: React.MouseEvent<HTMLElement>) => {
    if (isOpen) {
      setAnchorEl(null)
      return
    }

    setAnchorEl(event.currentTarget)

    if (!prompt.trim() || isLoading) return

    setIsLoading(true)
    setError(null)
    setResult(null)

    try {
      const response = await api.post('/chat/improve-prompt', {
        prompt: prompt,
      })
      setResult(response.data)
    } catch (err: any) {
      console.error('Error improving prompt:', err)
      setError(err.response?.data?.detail || 'Ошибка улучшения запроса')
    } finally {
      setIsLoading(false)
    }
  }

  const handleClose = () => {
    setAnchorEl(null)
    setResult(null)
    setError(null)
  }

  const handleAccept = () => {
    if (result?.improved_prompt) {
      onImprovedPrompt(result.improved_prompt)
      handleClose()
    }
  }

  return (
    <>
      <Button
        variant="text"
        size="small"
        disabled={isDisabled}
        onClick={handleClick}
        sx={{
          minWidth: 'auto',
          ...(className ? {} : {}),
        }}
        className={className}
      >
        {isLoading ? (
          <CircularProgress size={16} />
        ) : (
          <SparklesIcon fontSize="small" />
        )}
      </Button>

      <Popover
        open={isOpen}
        anchorEl={anchorEl}
        onClose={handleClose}
        anchorOrigin={{
          vertical: 'top',
          horizontal: 'right',
        }}
        transformOrigin={{
          vertical: 'bottom',
          horizontal: 'right',
        }}
        PaperProps={{
          sx: {
            width: 384,
            p: 0,
          },
        }}
      >
        <Box>
          {isLoading ? (
            <Fade in={isLoading}>
              <Box sx={{ p: 3, textAlign: 'center' }}>
                <CircularProgress sx={{ mb: 2 }} />
                <Typography variant="body2" color="text.secondary">
                  Анализируем и улучшаем запрос...
                </Typography>
              </Box>
            </Fade>
          ) : error ? (
            <Fade in={!!error}>
              <Box sx={{ p: 3, textAlign: 'center' }}>
                <Alert severity="error" sx={{ mb: 2 }}>
                  {error}
                </Alert>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={() => setError(null)}
                >
                  Попробовать снова
                </Button>
              </Box>
            </Fade>
          ) : result ? (
            <Grow in={!!result}>
              <Box>
                {/* Header */}
                <Box
                  sx={{
                    p: 2,
                    borderBottom: 1,
                    borderColor: 'divider',
                    bgcolor: (theme) => theme.palette.mode === 'dark'
                      ? 'rgba(138, 36, 170, 0.1)'
                      : 'rgba(138, 36, 170, 0.05)',
                  }}
                >
                  <Stack direction="row" spacing={1} alignItems="center">
                    <SparklesIcon color="primary" />
                    <Typography variant="subtitle2" fontWeight={600}>
                      Улучшенный запрос
                    </Typography>
                  </Stack>
                </Box>

                {/* Original vs Improved */}
                <Box sx={{ p: 2 }}>
                  <Stack spacing={2}>
                    {/* Original */}
                    <Box>
                      <Typography variant="caption" fontWeight={500} color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
                        Исходный запрос
                      </Typography>
                      <Box
                        sx={{
                          bgcolor: 'action.hover',
                          borderRadius: 1,
                          p: 1.5,
                        }}
                      >
                        <Typography
                          variant="body2"
                          sx={{
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                          }}
                        >
                          {prompt}
                        </Typography>
                      </Box>
                    </Box>

                    <Box sx={{ display: 'flex', justifyContent: 'center' }}>
                      <ArrowRightIcon fontSize="small" color="action" />
                    </Box>

                    {/* Improved */}
                    <Box>
                      <Typography variant="caption" fontWeight={500} color="primary.main" sx={{ mb: 0.5, display: 'block' }}>
                        Улучшенный запрос
                      </Typography>
                      <Box
                        sx={{
                          bgcolor: (theme) => theme.palette.mode === 'dark'
                            ? 'rgba(138, 36, 170, 0.1)'
                            : 'rgba(138, 36, 170, 0.05)',
                          border: 1,
                          borderColor: 'primary.main',
                          borderRadius: 1,
                          p: 1.5,
                        }}
                      >
                        <Typography variant="body2">
                          {result.improved_prompt}
                        </Typography>
                      </Box>
                    </Box>

                    {/* Improvements made */}
                    {result.improvements_made.length > 0 && (
                      <Box>
                        <Typography variant="caption" fontWeight={500} color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
                          Что изменилось
                        </Typography>
                        <Stack direction="row" spacing={0.5} flexWrap="wrap">
                          {result.improvements_made.map((imp, idx) => (
                            <Chip key={idx} label={imp} size="small" variant="outlined" />
                          ))}
                        </Stack>
                      </Box>
                    )}

                    {/* Suggestions */}
                    {result.suggestions.length > 0 && (
                      <>
                        <Divider />
                        <Box>
                          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mb: 1 }}>
                            <LightbulbIcon fontSize="small" color="action" />
                            <Typography variant="caption" fontWeight={500} color="text.secondary">
                              Рекомендации
                            </Typography>
                          </Stack>
                          <Stack spacing={0.5} component="ul" sx={{ pl: 2, m: 0 }}>
                            {result.suggestions.map((sug, idx) => (
                              <Typography key={idx} variant="caption" color="text.secondary" component="li">
                                {sug}
                              </Typography>
                            ))}
                          </Stack>
                        </Box>
                      </>
                    )}
                  </Stack>
                </Box>

                {/* Actions */}
                <Box
                  sx={{
                    p: 1.5,
                    borderTop: 1,
                    borderColor: 'divider',
                    bgcolor: 'action.hover',
                  }}
                >
                  <Stack direction="row" spacing={1}>
                    <Button
                      variant="outlined"
                      size="small"
                      fullWidth
                      startIcon={<CloseIcon />}
                      onClick={handleClose}
                    >
                      Отменить
                    </Button>
                    <Button
                      variant="contained"
                      size="small"
                      fullWidth
                      startIcon={<CheckIcon />}
                      onClick={handleAccept}
                    >
                      Применить
                    </Button>
                  </Stack>
                </Box>
              </Box>
            </Grow>
          ) : null}
        </Box>
      </Popover>
    </>
  )
}

export default MagicPromptButton
