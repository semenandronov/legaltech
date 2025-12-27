import { Drawer, Box, Typography, Divider, DrawerProps } from '@mui/material'
import { NavUser } from './NavUser'
import { SearchForm } from './SearchForm'

interface AppSidebarProps {
  open: boolean
  onClose: () => void
  variant?: DrawerProps['variant']
}

const DRAWER_WIDTH = 280

export function AppSidebar({ open, onClose, variant = 'persistent' }: AppSidebarProps) {
  return (
    <Drawer
      variant={variant}
      open={open}
      onClose={onClose}
      sx={{
        width: DRAWER_WIDTH,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: DRAWER_WIDTH,
          boxSizing: 'border-box',
          borderRight: '1px solid',
          borderColor: 'divider',
        },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
        }}
      >
        {/* Header */}
        <Box
          sx={{
            p: 2,
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
          }}
        >
          <Box
            component="a"
            href="/"
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              textDecoration: 'none',
              color: 'text.primary',
              '&:hover': {
                opacity: 0.8,
              },
            }}
          >
            <Typography variant="h5" component="span">
              ⚖️
            </Typography>
            <Typography variant="h6" component="span" sx={{ fontWeight: 600 }}>
              Legal AI
            </Typography>
          </Box>
          <SearchForm />
        </Box>

        <Divider />

        {/* Content */}
        <Box
          sx={{
            flexGrow: 1,
            overflow: 'auto',
            p: 2,
          }}
        >
          {/* Меню удалено - показывается только когда выбрано дело */}
        </Box>

        <Divider />

        {/* Footer */}
        <Box
          sx={{
            p: 1,
          }}
        >
          <NavUser />
        </Box>
      </Box>
    </Drawer>
  )
}



