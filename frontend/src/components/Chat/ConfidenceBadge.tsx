// Re-export для обратной совместимости
export { default } from '../Common/ConfidenceBadge'

interface ConfidenceBadgeProps {
  confidence: number
  showIcon?: boolean
}

const ConfidenceBadge: React.FC<ConfidenceBadgeProps> = ({
  confidence,
  showIcon = true
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

  return (
    <span className={`chat-confidence-badge ${badgeClass}`}>
      {badgeIcon} {Math.round(confidence)}%
    </span>
  )
}

export default ConfidenceBadge
