import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Drawer,
  Box,
  Typography,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  TextField,
  InputAdornment,
  IconButton,
  Divider,
  Chip,
  Stack,
  FormControlLabel,
  Switch,
  CircularProgress,
  Fade,
} from '@mui/material'
import {
  Search as SearchIcon,
  Close as CloseIcon,
  History as HistoryIcon,
  Chat as ChatIcon,
} from '@mui/icons-material'
import { getChatSessions } from '@/services/api'

interface ChatSession {
  case_id: string
  case_name: string
  last_message: string
  last_message_at: string
  message_count: number
}

interface ChatHistoryPanelProps {
  isOpen: boolean
  onClose: () => void
  currentCaseId?: string
  onSelectCase?: (caseId: string) => void
}

export const ChatHistoryPanel: React.FC<ChatHistoryPanelProps> = ({
  isOpen,
  onClose,
  currentCaseId,
  onSelectCase,
}) => {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [filteredSessions, setFilteredSessions] = useState<ChatSession[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [crossProjectHistory, setCrossProjectHistory] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (isOpen) {
      loadSessions()
    }
  }, [isOpen])

  useEffect(() => {
    if (searchQuery.trim()) {
      const filtered = sessions.filter(
        (session) =>
          session.case_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          session.last_message.toLowerCase().includes(searchQuery.toLowerCase())
      )
      setFilteredSessions(filtered)
    } else {
      setFilteredSessions(sessions)
    }
  }, [searchQuery, sessions])

  const loadSessions = async () => {
    setIsLoading(true)
    try {
      const data = await getChatSessions()
      setSessions(data)
      setFilteredSessions(data)
    } catch (error: any) {
      console.error('Error loading chat sessions:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleSelectCase = (caseId: string) => {
    if (onSelectCase) {
      onSelectCase(caseId)
    } else {
      navigate(`/cases/${caseId}`)
    }
    onClose()
  }

  const formatDate = (dateString: string): string => {
    if (!dateString) return ''
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffDays === 0) return 'Сегодня'
    if (diffDays === 1) return 'Вчера'
    if (diffDays < 7) return `${diffDays} дн. назад`
    return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
  }

  return (
    <Drawer
      anchor="right"
      open={isOpen}
      onClose={onClose}
      PaperProps={{
        sx: { width: 400, maxWidth: '90vw' },
      }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Header */}
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
            <Stack direction="row" spacing={1} alignItems="center">
              <HistoryIcon color="primary" />
              <Typography variant="h6">История чатов</Typography>
            </Stack>
            <IconButton size="small" onClick={onClose}>
              <CloseIcon />
            </IconButton>
          </Stack>
        </Box>

        {/* Search */}
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
          <TextField
            fullWidth
            size="small"
            placeholder="Поиск по делам..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
              endAdornment: searchQuery ? (
                <InputAdornment position="end">
                  <IconButton
                    size="small"
                    onClick={() => setSearchQuery('')}
                  >
                    <CloseIcon fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ) : null,
            }}
          />
        </Box>

        {/* Cross-project toggle */}
        <Box sx={{ px: 2, py: 1, borderBottom: 1, borderColor: 'divider' }}>
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={crossProjectHistory}
                onChange={(e) => setCrossProjectHistory(e.target.checked)}
              />
            }
            label="Все проекты"
          />
        </Box>

        {/* Sessions List */}
        <Box sx={{ flex: 1, overflow: 'auto' }}>
          {isLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 200 }}>
              <CircularProgress />
            </Box>
          ) : filteredSessions.length === 0 ? (
            <Box sx={{ p: 4, textAlign: 'center' }}>
              <ChatIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2, opacity: 0.5 }} />
              <Typography variant="body2" color="text.secondary">
                {searchQuery ? 'Чаты не найдены' : 'Нет истории чатов'}
              </Typography>
            </Box>
          ) : (
            <List>
              {filteredSessions.map((session, idx) => (
                <React.Fragment key={session.case_id}>
                  <Fade in timeout={300}>
                    <ListItem disablePadding>
                      <ListItemButton
                        selected={session.case_id === currentCaseId}
                        onClick={() => handleSelectCase(session.case_id)}
                        sx={{
                          '&.Mui-selected': {
                            bgcolor: 'action.selected',
                            '&:hover': {
                              bgcolor: 'action.selected',
                            },
                          },
                        }}
                      >
                        <ListItemText
                          primary={
                            <Stack direction="row" spacing={1} alignItems="center">
                              <Typography variant="subtitle2" fontWeight={600}>
                                {session.case_name}
                              </Typography>
                              {session.case_id === currentCaseId && (
                                <Chip label="Текущий" size="small" color="primary" />
                              )}
                            </Stack>
                          }
                          secondary={
                            <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                              {session.last_message && (
                                <Typography
                                  variant="body2"
                                  color="text.secondary"
                                  sx={{
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    display: '-webkit-box',
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: 'vertical',
                                  }}
                                >
                                  {session.last_message}
                                </Typography>
                              )}
                              <Stack direction="row" spacing={1} alignItems="center">
                                <Typography variant="caption" color="text.secondary">
                                  {formatDate(session.last_message_at)}
                                </Typography>
                                <Chip
                                  label={`${session.message_count} сообщений`}
                                  size="small"
                                  variant="outlined"
                                />
                              </Stack>
                            </Stack>
                          }
                        />
                      </ListItemButton>
                    </ListItem>
                  </Fade>
                  {idx < filteredSessions.length - 1 && <Divider />}
                </React.Fragment>
              ))}
            </List>
          )}
        </Box>
      </Box>
    </Drawer>
  )
}

