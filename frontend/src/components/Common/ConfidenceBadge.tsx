import React from 'react'
import './Common.css'

interface ConfidenceBadgeProps {
  confidence: number
  showIcon?: boolean
  size?: 'small' | 'medium' | 'large'
}

const ConfidenceBadge: React.FC<ConfidenceBadgeProps> = ({
  confidence,
  showIcon = true,
  size = 'medium'
}) => {
  const getBadgeClass = (conf: number): string => {
    if (conf > 90) return 'high'
    if (conf > 60) return 'medium'
    return 'low'
  }

  const getBadgeIcon = (conf: number): string => {
    if (conf > 90) return '✅'
    if (conf > 60) return '⚠️'
    return '❌'
  }

  const badgeClass = getBadgeClass(confidence)
  const badgeIcon = showIcon ? getBadgeIcon(confidence) : ''
  const sizeClass = `confidence-badge-${size}`

  return (
    <span className={`confidence-badge ${badgeClass} ${sizeClass}`}>
      {badgeIcon} {Math.round(confidence)}%
    </span>
  )
}

export default ConfidenceBadge
