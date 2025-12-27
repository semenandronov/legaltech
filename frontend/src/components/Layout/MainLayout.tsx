import { ReactNode, useState, useEffect } from 'react'
import { 
  Box, 
  Container,
  useMediaQuery, 
  useTheme,
  Backdrop,
} from '@mui/material'
import Header from './Header'
import { AppSidebar } from './AppSidebar'

interface MainLayoutProps {
  children: ReactNode
}

const DRAWER_WIDTH = 280

const MainLayout = ({ children }: MainLayoutProps) => {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))
  const [sidebarOpen, setSidebarOpen] = useState(!isMobile)

  // Close sidebar on mobile by default
  useEffect(() => {
    if (isMobile) {
      setSidebarOpen(false)
    } else {
      setSidebarOpen(true)
    }
  }, [isMobile])

  const handleSidebarToggle = () => {
    setSidebarOpen(!sidebarOpen)
  }

  return (
    <Box 
      sx={{ 
        display: 'flex', 
        height: '100vh', 
        overflow: 'hidden',
        bgcolor: 'background.default'
      }}
    >
      <AppSidebar 
        open={sidebarOpen} 
        onClose={() => setSidebarOpen(false)}
        variant={isMobile ? 'temporary' : 'persistent'}
      />
      
      {/* Backdrop for mobile */}
      {isMobile && sidebarOpen && (
        <Backdrop
          open={sidebarOpen}
          onClick={() => setSidebarOpen(false)}
          sx={{
            zIndex: (theme) => theme.zIndex.drawer - 1,
            bgcolor: 'rgba(0, 0, 0, 0.5)',
          }}
        />
      )}

      {/* Main content area */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          width: { 
            xs: '100%', 
            md: sidebarOpen ? `calc(100% - ${DRAWER_WIDTH}px)` : '100%' 
          },
          marginLeft: { 
            xs: 0, 
            md: sidebarOpen ? `${DRAWER_WIDTH}px` : 0 
          },
          transition: (theme) => theme.transitions.create(['margin', 'width'], {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.enteringScreen,
          }),
        }}
      >
        <Header onMenuClick={handleSidebarToggle} />
        
        <Box
          sx={{
            flexGrow: 1,
            overflow: 'auto',
            bgcolor: 'background.default',
          }}
        >
          <Container 
            maxWidth={false}
            sx={{
              height: '100%',
              py: 3,
              px: { xs: 2, sm: 3, md: 4 },
            }}
          >
            {children}
          </Container>
        </Box>
      </Box>
    </Box>
  )
}

export default MainLayout
