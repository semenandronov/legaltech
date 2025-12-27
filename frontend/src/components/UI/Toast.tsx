import { useEffect } from 'react'
import { Snackbar, Alert, Slide, SlideProps } from '@mui/material'
import {
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Warning as WarningIcon,
  Info as InfoIcon,
} from '@mui/icons-material'

type ToastType = 'success' | 'error' | 'warning' | 'info'

interface ToastProps {
  type: ToastType
  message: string
  isVisible: boolean
  onClose: () => void
  duration?: number
}

function SlideTransition(props: SlideProps) {
  return <Slide {...props} direction="up" />
}

const Toast = ({ type, message, isVisible, onClose, duration = 4000 }: ToastProps) => {
  useEffect(() => {
    if (isVisible && duration > 0) {
      const timer = setTimeout(() => {
        onClose()
      }, duration)
      return () => clearTimeout(timer)
    }
  }, [isVisible, duration, onClose])
  
  const severityMap: Record<ToastType, 'success' | 'error' | 'warning' | 'info'> = {
    success: 'success',
    error: 'error',
    warning: 'warning',
    info: 'info',
  }
  
  const iconMap: Record<ToastType, React.ReactElement> = {
    success: <CheckCircleIcon />,
    error: <ErrorIcon />,
    warning: <WarningIcon />,
    info: <InfoIcon />,
  }
  
  return (
    <Snackbar
      open={isVisible}
      autoHideDuration={duration > 0 ? duration : undefined}
      onClose={onClose}
      TransitionComponent={SlideTransition}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      sx={{
        bottom: { xs: 90, sm: 24 },
      }}
    >
      <Alert
        onClose={onClose}
        severity={severityMap[type]}
        icon={iconMap[type]}
        variant="filled"
        sx={{
          minWidth: 300,
          maxWidth: 500,
        }}
      >
        {message}
      </Alert>
    </Snackbar>
  )
}

export default Toast
