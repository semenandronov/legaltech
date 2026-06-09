import { ReactNode } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  IconButton,
  Box,
  Typography,
  Breakpoint,
} from '@mui/material'
import { Close as CloseIcon } from '@mui/icons-material'

interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  /** Убрать внутренний скролл — контент растягивает окно по высоте */
  fitContent?: boolean
}

const Modal = ({ isOpen, onClose, title, children, size = 'md', className = '', fitContent = false }: ModalProps) => {
  const maxWidthMap: Record<string, Breakpoint> = {
    sm: 'sm',
    md: 'md',
    lg: 'lg',
    xl: 'xl',
  }

  return (
    <Dialog
      open={isOpen}
      onClose={onClose}
      maxWidth={maxWidthMap[size]}
      fullWidth
      className={className}
      PaperProps={{
        sx: {
          borderRadius: 2,
          zIndex: 1300,
          ...(fitContent
            ? {
                maxHeight: 'calc(100vh - 32px)',
                height: 'auto',
                overflow: 'visible',
              }
            : {}),
        },
      }}
      slotProps={{
        backdrop: {
          sx: {
            zIndex: 1300, // Ensure backdrop doesn't block Select
          },
        },
      }}
    >
      {title && (
        <DialogTitle
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            pb: 1,
          }}
        >
          <Typography variant="h6" component="span">
            {title}
          </Typography>
          <IconButton
            aria-label="close"
            onClick={onClose}
            sx={{
              position: 'absolute',
              right: 8,
              top: 8,
              color: (theme) => theme.palette.grey[500],
            }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
      )}
      <DialogContent
        dividers
        sx={{
          pt: title ? 2 : 3,
          ...(fitContent
            ? { overflow: 'visible', maxHeight: 'none' }
            : {}),
        }}
      >
        <Box>{children}</Box>
      </DialogContent>
    </Dialog>
  )
}

export default Modal
