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
  FormControlLabel,
  Checkbox,
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
} from '@mui/icons-material'
import { fetchHistory, getChatSessionsForCase, getChatSessions } from '@/services/api'
import { toast } from 'sonner'

interface HistoryItem {
  id: string
  content: string
  created_at: string
  case_id?: string
  session_id?: string
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
  const [showAllProjects, setShowAllProjects] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const [selectedItem, setSelectedItem] = useState<HistoryItem | null>(null)

  useEffect(() => {
    if (isOpen) {
      if (showAllProjects) {
        loadAllProjectsHistory()
      } else if (currentCaseId) {
        loadHistory()
      }
    }
  }, [isOpen, currentCaseId, showAllProjects])

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
    try {
      // Загружаем сессии для текущего дела
      const sessions = await getChatSessionsForCase(currentCaseId)
      
      // Преобразуем сессии в элементы истории (берем первое сообщение каждой сессии)
      const historyItemsList: HistoryItem[] = []
      
      for (const session of sessions) {
        // Загружаем первое сообщение сессии для превью
        const sessionMessages = await fetchHistory(currentCaseId, session.session_id)
        const firstUserMessage = sessionMessages.find((msg: any) => msg.role === 'user')
        
        if (firstUserMessage) {
          historyItemsList.push({
            id: `session-${session.session_id}`,
            content: firstUserMessage.content,
            created_at: session.first_message_at || session.last_message_at || '',
            case_id: currentCaseId,
            session_id: session.session_id,
          })
        }
      }
      
      // Сортируем по дате (новые сверху)
      historyItemsList.sort((a, b) => {
        const dateA = new Date(a.created_at).getTime()
        const dateB = new Date(b.created_at).getTime()
        return dateB - dateA
      })
      
      setHistoryItems(historyItemsList)
      setFilteredItems(historyItemsList)
    } catch (error: any) {
      console.error('Error loading chat history:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const loadAllProjectsHistory = async () => {
    setIsLoading(true)
    try {
      // Загружаем все сессии всех дел пользователя
      const allSessions = await getChatSessions()
      
      // Преобразуем в элементы истории
      const historyItemsList: HistoryItem[] = []
      
      for (const session of allSessions) {
        // Загружаем сессии для этого дела
        const caseSessions = await getChatSessionsForCase(session.case_id)
        
        for (const caseSession of caseSessions) {
          const sessionMessages = await fetchHistory(session.case_id, caseSession.session_id)
          const firstUserMessage = sessionMessages.find((msg: any) => msg.role === 'user')
          
          if (firstUserMessage) {
            historyItemsList.push({
              id: `session-${caseSession.session_id}`,
              content: firstUserMessage.content,
              created_at: caseSession.first_message_at || caseSession.last_message_at || '',
              case_id: session.case_id,
              session_id: caseSession.session_id,
            })
          }
        }
      }
      
      // Сортируем по дате (новые сверху)
      historyItemsList.sort((a, b) => {
        const dateA = new Date(a.created_at).getTime()
        const dateB = new Date(b.created_at).getTime()
        return dateB - dateA
      })
      
      setHistoryItems(historyItemsList)
      setFilteredItems(historyItemsList)
    } catch (error: any) {
      console.error('Error loading all projects history:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleSelectQuery = async (item: HistoryItem) => {
    // Загружаем только сессию этого сообщения, а не всю историю
    if (onLoadHistory && item.session_id) {
      await onLoadHistory(item.session_id)
    }
    if (onSelectQuery) {
      onSelectQuery(item.content, item.session_id)
    }
    onClose()
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
      if (diffMinutes === 0) return 'just now'
      return `${diffMinutes} ${diffMinutes === 1 ? 'minute' : 'minutes'} ago`
    }
    if (diffHours < 24) {
      if (diffHours === 1) return 'about 1 hour ago'
      return `about ${diffHours} hours ago`
    }
    if (diffDays === 1) return 'about 1 day ago'
    if (diffDays < 7) return `about ${diffDays} days ago`
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
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
            <Typography variant="h6" sx={{ fontWeight: 600 }}>History</Typography>
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
            placeholder="Search"
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

        {/* Show history from all projects toggle */}
        <Box sx={{ px: 2, py: 1.5, borderBottom: 1, borderColor: 'divider' }}>
          <FormControlLabel
            control={
              <Checkbox
                size="small"
                checked={showAllProjects}
                onChange={(e) => setShowAllProjects(e.target.checked)}
              />
            }
            label="Show history from all projects"
            sx={{ '& .MuiFormControlLabel-label': { fontSize: '0.875rem' } }}
          />
        </Box>

        {/* History List */}
        <Box sx={{ flex: 1, overflow: 'auto' }}>
          {isLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 200 }}>
              <CircularProgress />
            </Box>
          ) : filteredItems.length === 0 ? (
            <Box sx={{ p: 4, textAlign: 'center' }}>
              <ChatIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 2, opacity: 0.5 }} />
              <Typography variant="body2" color="text.secondary">
                {searchQuery ? 'No queries found' : 'No chat history'}
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
            Use this query
          </MenuItem>
          <MenuItem onClick={() => {
            toast.info("Удаление сообщений из истории будет реализовано позже")
            handleMenuClose()
          }}>
            Delete
          </MenuItem>
        </Menu>
      </Box>
    </Drawer>
  )
}

