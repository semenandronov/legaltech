import { ReactNode, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, CheckCircle, XCircle, AlertCircle, Info } from 'lucide-react'

type ToastType = 'success' | 'error' | 'warning' | 'info'

interface ToastProps {
  type: ToastType
  message: string
  isVisible: boolean
  onClose: () => void
  duration?: number
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
  
  const typeConfig = {
    success: {
      bg: 'bg-success',
      icon: CheckCircle,
    },
    error: {
      bg: 'bg-error',
      icon: XCircle,
    },
    warning: {
      bg: 'bg-warning',
      icon: AlertCircle,
    },
    info: {
      bg: 'bg-info',
      icon: Info,
    },
  }
  
  const config = typeConfig[type]
  const Icon = config.icon
  
  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ opacity: 0, y: -20, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -20, scale: 0.95 }}
          transition={{ duration: 0.2 }}
          className={`fixed bottom-4 right-4 ${config.bg} text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 min-w-[300px] max-w-[500px] z-50`}
        >
          <Icon className="w-5 h-5 flex-shrink-0" />
          <p className="flex-1 text-body">{message}</p>
          <button
            onClick={onClose}
            className="flex-shrink-0 hover:opacity-80 transition-opacity"
            aria-label="Закрыть"
          >
            <X className="w-4 h-4" />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default Toast
