import React from 'react'
import {
  Box,
  Typography,
  Stack,
  Card,
  CardContent,
  Button,
  Grow,
} from '@mui/material'
import {
  AutoAwesome as SparklesIcon,
  Chat as ChatIcon,
  Timeline as TimelineIcon,
  Search as SearchIcon,
} from '@mui/icons-material'

interface WelcomeScreenProps {
  onQuickAction?: (prompt: string) => void
}

const QUICK_ACTIONS = [
  {
    icon: <ChatIcon />,
    title: 'Краткое изложение',
    description: 'Сформулируй краткий обзор этого дела',
    prompt: 'Сформулируй краткий обзор этого дела',
  },
  {
    icon: <TimelineIcon />,
    title: 'Хронология событий',
    description: 'Создай хронологию событий из документов',
    prompt: 'Создай хронологию событий из документов',
  },
  {
    icon: <SearchIcon />,
    title: 'Найти противоречия',
    description: 'Найди противоречия между документами',
    prompt: 'Найди противоречия между документами',
  },
]

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({ onQuickAction }) => {
  return (
    <Grow in timeout={500}>
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          p: 4,
        }}
      >
        <Stack spacing={4} alignItems="center" sx={{ maxWidth: 600, width: '100%' }}>
          {/* Header */}
          <Stack spacing={2} alignItems="center">
            <Box
              sx={{
                width: 64,
                height: 64,
                borderRadius: '50%',
                bgcolor: 'primary.main',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                mb: 2,
              }}
            >
              <SparklesIcon sx={{ fontSize: 32, color: 'white' }} />
            </Box>
            <Typography variant="h4" fontWeight={600} textAlign="center">
              How can I assist?
            </Typography>
            <Typography variant="body1" color="text.secondary" textAlign="center">
              Задайте вопрос о ваших документах или выберите одно из быстрых действий
            </Typography>
          </Stack>

          {/* Quick Actions */}
          <Stack spacing={2} sx={{ width: '100%' }}>
            {QUICK_ACTIONS.map((action, idx) => (
              <Grow in timeout={600 + idx * 100} key={action.title}>
                <Card
                  sx={{
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    '&:hover': {
                      boxShadow: 4,
                      transform: 'translateY(-2px)',
                    },
                  }}
                  onClick={() => onQuickAction?.(action.prompt)}
                >
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <Box
                        sx={{
                          width: 48,
                          height: 48,
                          borderRadius: 2,
                          bgcolor: 'primary.light',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: 'primary.main',
                        }}
                      >
                        {action.icon}
                      </Box>
                      <Stack spacing={0.5} sx={{ flex: 1 }}>
                        <Typography variant="subtitle1" fontWeight={600}>
                          {action.title}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {action.description}
                        </Typography>
                      </Stack>
                    </Stack>
                  </CardContent>
                </Card>
              </Grow>
            ))}
          </Stack>

          {/* Help Text */}
          <Typography variant="caption" color="text.secondary" textAlign="center">
            Вы также можете задать свой вопрос в поле ввода ниже
          </Typography>
        </Stack>
      </Box>
    </Grow>
  )
}

