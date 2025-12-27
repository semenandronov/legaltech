import React from 'react'
import {
  Box,
  IconButton,
  Divider,
  useTheme,
  useMediaQuery,
} from '@mui/material'
import {
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
} from '@mui/icons-material'

interface WorkspaceLayoutProps {
  leftPanel: React.ReactNode
  centerPanel: React.ReactNode
  rightPanel: React.ReactNode
  rightPanelCollapsed?: boolean
  onToggleRightPanel?: () => void
}

const WorkspaceLayout: React.FC<WorkspaceLayoutProps> = ({
  leftPanel,
  centerPanel,
  rightPanel,
  rightPanelCollapsed = false,
  onToggleRightPanel
}) => {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))

  return (
    <Box
      sx={{
        height: '100%',
        display: 'flex',
        overflow: 'hidden',
      }}
    >
      {/* Left Panel */}
      <Box
        sx={{
          width: { xs: '100%', md: '20%' },
          minWidth: { md: '250px' },
          maxWidth: { md: '350px' },
          height: '100%',
          overflow: 'auto',
          borderRight: { md: '1px solid' },
          borderColor: { md: 'divider' },
          display: { xs: rightPanelCollapsed ? 'none' : 'block', md: 'block' },
        }}
      >
        {leftPanel}
      </Box>

      {!isMobile && <Divider orientation="vertical" flexItem />}

      {/* Center Panel */}
      <Box
        sx={{
          flexGrow: 1,
          height: '100%',
          overflow: 'auto',
          display: { xs: rightPanelCollapsed ? 'block' : 'none', md: 'block' },
        }}
      >
        {centerPanel}
      </Box>

      {/* Right Panel */}
      {!rightPanelCollapsed && (
        <>
          {!isMobile && <Divider orientation="vertical" flexItem />}
          <Box
            sx={{
              width: { xs: '100%', md: '30%' },
              minWidth: { md: '300px' },
              maxWidth: { md: '400px' },
              height: '100%',
              overflow: 'auto',
              borderLeft: { md: '1px solid' },
              borderColor: { md: 'divider' },
              position: 'relative',
              display: { xs: 'block', md: 'block' },
            }}
          >
            {rightPanel}
            {onToggleRightPanel && (
              <IconButton
                onClick={onToggleRightPanel}
                aria-label="Свернуть чат"
                sx={{
                  position: 'absolute',
                  top: 8,
                  left: 8,
                  zIndex: 1,
                  bgcolor: 'background.paper',
                  boxShadow: 1,
                  '&:hover': {
                    bgcolor: 'action.hover',
                  },
                }}
                size="small"
              >
                <ChevronRightIcon />
              </IconButton>
            )}
          </Box>
        </>
      )}

      {/* Toggle button when right panel is collapsed */}
      {rightPanelCollapsed && onToggleRightPanel && (
        <IconButton
          onClick={onToggleRightPanel}
          aria-label="Развернуть чат"
          sx={{
            position: 'fixed',
            right: 8,
            bottom: 80,
            zIndex: 1000,
            bgcolor: 'primary.main',
            color: 'primary.contrastText',
            boxShadow: 3,
            '&:hover': {
              bgcolor: 'primary.dark',
            },
          }}
        >
          <ChevronLeftIcon />
        </IconButton>
      )}
    </Box>
  )
}

export default WorkspaceLayout
