import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AppBar,
  Toolbar,
  IconButton,
  Button,
  Avatar,
  Menu,
  MenuItem,
  Divider,
  Typography,
  Box,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import {
  Search as SearchIcon,
  Add as AddIcon,
  Menu as MenuIcon,
  Settings as SettingsIcon,
  Logout as LogoutIcon,
} from '@mui/icons-material'
import { useAuth } from '../../contexts/AuthContext'
import UploadArea from '../UploadArea'
import ThemeToggle from '../UI/ThemeToggle'
import {
  Dialog,
  DialogContent,
  DialogTitle,
  Typography as DialogDescriptionTypography,
} from '@mui/material'
import { AppBreadcrumbs } from './Breadcrumbs'
import { CommandPalette } from './CommandPalette'

interface HeaderProps {
  onMenuClick?: () => void
}

const Header = ({ onMenuClick }: HeaderProps) => {
  const { user, logout } = useAuth()
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const navigate = useNavigate()
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'))

  const handleUpload = (caseId: string, _fileNames: string[]) => {
    setShowUploadModal(false)
    navigate(`/cases/${caseId}/chat`)
    window.location.reload()
  }

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
  }

  const handleMenuClose = () => {
    setAnchorEl(null)
  }

  const handleSettings = () => {
    handleMenuClose()
    navigate('/settings')
  }

  const handleLogout = async () => {
    handleMenuClose()
    await logout()
    navigate('/login')
  }

  const handleSearchClick = () => {
    const event = new KeyboardEvent('keydown', {
      key: 'k',
      metaKey: true,
      bubbles: true,
    })
    document.dispatchEvent(event)
  }

  const userInitials = user?.full_name?.[0]?.toUpperCase() || user?.email[0].toUpperCase() || 'U'

  return (
    <>
      <AppBar
        position="static"
        elevation={0}
        sx={{
          backgroundColor: 'background.paper',
          borderBottom: '1px solid',
          borderColor: 'divider',
        }}
      >
        <Toolbar sx={{ gap: 2 }}>
          {onMenuClick && (
            <IconButton
              edge="start"
              color="inherit"
              onClick={onMenuClick}
              sx={{ mr: 1 }}
            >
              <MenuIcon />
            </IconButton>
          )}

          <Box sx={{ flexGrow: 1, display: 'flex', alignItems: 'center', gap: 2 }}>
            <AppBreadcrumbs />
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {!isMobile && (
              <IconButton
                color="inherit"
                onClick={handleSearchClick}
                aria-label="Поиск"
              >
                <SearchIcon />
              </IconButton>
            )}

            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setShowUploadModal(true)}
              sx={{ textTransform: 'none' }}
            >
              {isMobile ? 'Новое' : 'Загрузить новое дело'}
            </Button>

            <ThemeToggle />

            {user && (
              <>
                <IconButton
                  onClick={handleMenuOpen}
                  size="small"
                  sx={{ ml: 1 }}
                  aria-label="Меню пользователя"
                >
                  <Avatar sx={{ width: 32, height: 32, bgcolor: 'primary.main' }}>
                    {userInitials}
                  </Avatar>
                </IconButton>
                <Menu
                  anchorEl={anchorEl}
                  open={Boolean(anchorEl)}
                  onClose={handleMenuClose}
                  anchorOrigin={{
                    vertical: 'bottom',
                    horizontal: 'right',
                  }}
                  transformOrigin={{
                    vertical: 'top',
                    horizontal: 'right',
                  }}
                >
                  <Box sx={{ px: 2, py: 1.5 }}>
                    <Typography variant="body2" fontWeight={500}>
                      {user.full_name || user.email}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {user.email}
                    </Typography>
                  </Box>
                  <Divider />
                  <MenuItem onClick={handleSettings}>
                    <SettingsIcon sx={{ mr: 1, fontSize: 20 }} />
                    Настройки
                  </MenuItem>
                  <Divider />
                  <MenuItem onClick={handleLogout}>
                    <LogoutIcon sx={{ mr: 1, fontSize: 20 }} />
                    Выйти
                  </MenuItem>
                </Menu>
              </>
            )}
          </Box>
        </Toolbar>
      </AppBar>

      <Dialog
        open={showUploadModal}
        onClose={() => setShowUploadModal(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Загрузить новое дело</DialogTitle>
        <DialogContent>
          <DialogDescriptionTypography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Загрузите документы для создания нового дела
          </DialogDescriptionTypography>
          <UploadArea onUpload={handleUpload} />
        </DialogContent>
      </Dialog>

      <CommandPalette />
    </>
  )
}

export default Header