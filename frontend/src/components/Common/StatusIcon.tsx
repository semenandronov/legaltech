import React from 'react'
import './Common.css'

export type DocumentStatus = 'reviewed' | 'privileged' | 'rejected' | 'processing' | 'flagged' | 'bookmarked' | 'confirmed'

interface StatusIconProps {
  status: DocumentStatus
  size?: 'small' | 'medium' | 'large'
}

const StatusIcon: React.FC<StatusIconProps> = ({
  status,
  size = 'medium'
}) => {
  const getStatusIcon = (status: DocumentStatus): string => {
    switch (status) {
      case 'reviewed':
        return '⭐'
      case 'privileged':
        return '🔒'
      case 'rejected':
        return '❌'
      case 'processing':
        return '⏳'
      case 'flagged':
        return '🚩'
      case 'bookmarked':
        return '📍'
      case 'confirmed':
        return '✅'
      default:
        return '📄'
    }
  }

  const getStatusLabel = (status: DocumentStatus): string => {
    switch (status) {
      case 'reviewed':
        return 'Reviewed by human'
      case 'privileged':
        return 'Withheld (privileged)'
      case 'rejected':
        return 'Rejected (not relevant)'
      case 'processing':
        return 'Processing'
      case 'flagged':
        return 'Flagged for attorney'
      case 'bookmarked':
        return 'Bookmarked'
      case 'confirmed':
        return 'Confirmed (relevant)'
      default:
        return 'Unknown'
    }
  }

  const sizeClass = `status-icon-${size}`

  return (
    <span
      className={`status-icon ${sizeClass}`}
      title={getStatusLabel(status)}
      aria-label={getStatusLabel(status)}
    >
      {getStatusIcon(status)}
    </span>
  )
}

export default StatusIcon
