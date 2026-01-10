import React from 'react'
import {
  Box,
  Typography,
  Stack,
  Card,
  CardContent,
  Grow,
  CircularProgress,
  Chip,
} from '@mui/material'
import {
  AutoAwesome as SparklesIcon,
  Chat as ChatIcon,
  Timeline as TimelineIcon,
  Search as SearchIcon,
  FactCheck as FactCheckIcon,
  Warning as WarningIcon,
  TableChart as TableChartIcon,
  Description as DescriptionIcon,
} from '@mui/icons-material'

interface WelcomeScreenProps {
  onQuickAction?: (prompt: string) => void
  caseTitle?: string
  documentCount?: number
  isLoading?: boolean
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
  {
    icon: <FactCheckIcon />,
    title: 'Извлечь ключевые факты',
    description: 'Извлеки ключевые факты из документов дела',
    prompt: 'Извлеки ключевые факты из документов дела',
  },
  {
    icon: <WarningIcon />,
    title: 'Проанализировать риски',
    description: 'Проанализируй риски в этом деле',
    prompt: 'Проанализируй риски в этом деле',
  },
  {
    icon: <TableChartIcon />,
    title: 'Создать таблицу',
    description: 'Создай таблицу с данными из документов',
    prompt: 'Создай таблицу с данными из документов',
  },
]

const EXAMPLE_QUESTIONS = [
  'Какие ключевые сроки важны в этом деле?',
  'Что говорится в договоре о сроках?',
  'Какие документы относятся к судебным заседаниям?',
  'Какие суммы упоминаются в документах?',
]

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({ 
  onQuickAction, 
  caseTitle, 
  documentCount, 
  isLoading = false 
}) => {
  return (
    <Grow in timeout={500}>
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'flex-start',
          width: '100%',
          maxHeight: '100%',
          overflowY: 'auto',
          p: 4,
        }}
      >
        <Stack spacing={3} alignItems="center" sx={{ maxWidth: 700, width: '100%', py: 2 }}>
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
              Чем могу помочь?
            </Typography>
            <Typography variant="body1" color="text.secondary" textAlign="center">
              Задайте вопрос о ваших документах
            </Typography>
            
            {/* Case Info */}
            {(caseTitle || documentCount !== undefined) && (
              <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 1 }}>
                {caseTitle && (
                  <Chip 
                    icon={<DescriptionIcon />}
                    label={caseTitle}
                    size="small"
                    sx={{ bgcolor: 'primary.light', color: 'primary.main' }}
                  />
                )}
                {documentCount !== undefined && (
                  <Chip 
                    label={`${documentCount} ${documentCount === 1 ? 'документ' : documentCount < 5 ? 'документа' : 'документов'}`}
                    size="small"
                    sx={{ bgcolor: 'grey.100', color: 'text.secondary' }}
                  />
                )}
                {isLoading && (
                  <CircularProgress size={16} sx={{ color: 'text.secondary' }} />
                )}
              </Stack>
            )}
          </Stack>

          {/* Example Questions */}
          <Stack spacing={1} sx={{ width: '100%', mt: 2 }}>
            <Typography variant="caption" color="text.secondary" textAlign="center" fontWeight={600}>
              Примеры вопросов:
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" justifyContent="center">
              {EXAMPLE_QUESTIONS.map((question, idx) => (
                <Chip
                  key={idx}
                  label={question}
                  size="small"
                  onClick={() => onQuickAction?.(question)}
                  sx={{
                    cursor: 'pointer',
                    '&:hover': {
                      bgcolor: 'primary.light',
                      color: 'primary.main',
                    },
                  }}
                />
              ))}
            </Stack>
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

