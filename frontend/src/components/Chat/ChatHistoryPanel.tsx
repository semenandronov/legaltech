import React, { useState, useEffect } from 'react'
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
  Stack,
  CircularProgress,
  Fade,
  Menu,
  MenuItem,
} from '@mui/material'
import {
  Search as SearchIcon,
  Close as CloseIcon,
  Chat as ChatIcon,
  MoreVert as MoreVertIcon,
  Delete as DeleteIcon,
} from '@mui/icons-material'
import { getChatSessionsForCase, deleteChatSession } from '@/services/api'
import { toast } from 'sonner'

interface HistoryItem {
  id: string
  content: string
  created_at: string
  session_id: string
  message_count: number
}

interface ChatHistoryPanelProps {
  isOpen: boolean
  onClose: () => void
  currentCaseId?: string
  onSelectQuery?: (query: string, sessionId?: string) => void
  onLoadHistory?: (sessionId?: string) => Promise<void>
}

export const ChatHistoryPanel: React.FC<ChatHistoryPanelProps> = ({
  isOpen,
  onClose,
  currentCaseId,
  onSelectQuery,
  onLoadHistory,
}) => {
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([])
  const [filteredItems, setFilteredItems] = useState<HistoryItem[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const [selectedItem, setSelectedItem] = useState<HistoryItem | null>(null)

  useEffect(() => {
    if (isOpen && currentCaseId) {
      loadHistory()
    }
  }, [isOpen, currentCaseId])

  useEffect(() => {
    if (searchQuery.trim()) {
      const filtered = historyItems.filter(
        (item) =>
          item.content.toLowerCase().includes(searchQuery.toLowerCase())
      )
      setFilteredItems(filtered)
    } else {
      setFilteredItems(historyItems)
    }
  }, [searchQuery, historyItems])

  const loadHistory = async () => {
    if (!currentCaseId) return
    setIsLoading(true)
    setError(null)
    try {
      const sessions = await getChatSessionsForCase(currentCaseId)

      // Use first_message directly from the sessions response — no extra API calls
      const items: HistoryItem[] = sessions
        .filter(s => s.first_message && s.first_message.trim())
        .map(session => ({
          id: `session-${session.session_id}`,
          content: session.first_message,
          created_at: session.first_message_at || session.last_message_at || '',
          session_id: session.session_id,
          message_count: session.message_count,
        }))

      // Sort by date (newest first) — backend already sorts, but be safe
      items.sort((a, b) => {
        const dateA = new Date(a.created_at).getTime()
        const dateB = new Date(b.created_at).getTime()
        return dateB - dateA
      })

      setHistoryItems(items)
      setFilteredItems(items)
    } catch (err: any) {
      console.error('Error loading chat history:', err)
      setError('Не удалось загрузить историю чата')
      toast.error('Ошибка загрузки истории')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSelectQuery = async (item: HistoryItem) => {
    if (onLoadHistory && item.session_id) {
      await onLoadHistory(item.session_id)
    }
    if (onSelectQuery) {
      onSelectQuery(item.content, item.session_id)
    }
    onClose()
  }

  const handleDeleteSession = async (item: HistoryItem) => {
    if (!currentCaseId) return
    if (!window.confirm('Удалить эту сессию чата?')) return

    try {
      await deleteChatSession(currentCaseId, item.session_id)
      setHistoryItems(prev => prev.filter(h => h.id !== item.id))
      toast.success('Сессия удалена')
    } catch (err: any) {
      console.error('Error deleting session:', err)
      toast.error('Не удалось удалить сессию')
    }
  }

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>, item: HistoryItem) => {
    event.stopPropagation()
    setAnchorEl(event.currentTarget)
    setSelectedItem(item)
  }

  const handleMenuClose = () => {
    setAnchorEl(null)
    setSelectedItem(null)
  }

  const formatDate = (dateString: string): string => {
    if (!dateString) return ''
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMinutes = Math.floor(diffMs / (1000 * 60))
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffMinutes < 60) {
      if (diffMinutes === 0) return 'только что'
      if (diffMinutes === 1) return '1 минуту назад'
      if (diffMinutes < 5) return `${diffMinutes} минуты назад`
      return `${diffMinutes} минут назад`
    }
    if (diffHours < 24) {
      if (diffHours === 1) return '1 час назад'
      if (diffHours < 5) return `${diffHours} часа назад`
      return `${diffHours} часов назад`
    }
    if (diffDays === 1) return 'вчера'
    if (diffDays < 7) return `${diffDays} дней назад`
    return date.toLocaleDateString('ru-RU', { month: 'short', day: 'numeric' })
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
            <Typography variant="h6" sx={{ fontWeight: 600 }}>История</Typography>
            <IconButton size="small" onClick={onClose} aria-label="Закрыть панель истории">
              <CloseIcon />
            </IconButton>
          </Stack>
        </Box>

        {/* Search */}
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
          <TextField
            fullWidth
            size="small"
            placeholder="Поиск по истории..."
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

        {/* History List */}
        <Box sx={{ flex: 1, overflow: 'auto' }}>
          {isLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 200 }}>
              <CircularProgress />
            </Box>
          ) : error ? (
            <Box sx={{ p: 4, textAlign: 'center' }}>
              <Typography variant="body2" color="error" sx={{ mb: 2 }}>
                {error}
              </Typography>
              <button
                onClick={loadHistory}
                className="text-sm text-blue-600 hover:underline"
              >
                Попробовать снова
              </button>
            </Box>
          ) : filteredItems.length === 0 ? (
            <Box sx={{ p: 4, textAlign: 'center' }}>
              <ChatIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2, opacity: 0.5 }} />
              <Typography variant="body2" color="text.secondary">
                {searchQuery ? 'Запросы не найдены' : 'История чатов пуста'}
              </Typography>
            </Box>
          ) : (
            <List>
              {filteredItems.map((item, idx) => (
                <React.Fragment key={item.id}>
                  <Fade in timeout={300}>
                    <ListItem
                      disablePadding
                      secondaryAction={
                        <IconButton
                          edge="end"
                          size="small"
                          onClick={(e) => handleMenuOpen(e, item)}
                        >
                          <MoreVertIcon fontSize="small" />
                        </IconButton>
                      }
                    >
                      <ListItemButton
                        onClick={() => handleSelectQuery(item)}
                        sx={{
                          '&:hover': {
                            bgcolor: 'action.hover',
                          },
                        }}
                      >
                        <ListItemText
                          primary={
                            <Typography
                              variant="body2"
                              sx={{
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                display: '-webkit-box',
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: 'vertical',
                                color: 'text.primary',
                              }}
                            >
                              {item.content}
                            </Typography>
                          }
                          secondary={
                            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
                              {formatDate(item.created_at)}
                              {item.message_count > 0 && ` · ${item.message_count} сообщ.`}
                            </Typography>
                          }
                        />
                      </ListItemButton>
                    </ListItem>
                  </Fade>
                  {idx < filteredItems.length - 1 && <Divider />}
                </React.Fragment>
              ))}
            </List>
          )}
        </Box>

        {/* Menu */}
        <Menu
          anchorEl={anchorEl}
          open={Boolean(anchorEl)}
          onClose={handleMenuClose}
        >
          <MenuItem onClick={() => {
            if (selectedItem) {
              handleSelectQuery(selectedItem)
            }
            handleMenuClose()
          }}>
            Открыть сессию
          </MenuItem>
          <MenuItem
            onClick={() => {
              if (selectedItem) {
                handleDeleteSession(selectedItem)
              }
              handleMenuClose()
            }}
            sx={{ color: 'error.main' }}
          >
            <DeleteIcon fontSize="small" sx={{ mr: 1 }} />
            Удалить
          </MenuItem>
        </Menu>
      </Box>
    </Drawer>
  )
}
