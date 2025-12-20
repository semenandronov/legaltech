import { ReactNode } from 'react'

type BadgeVariant = 'high-risk' | 'medium-risk' | 'low-risk' | 'contract' | 'email' | 'court' | 'compliance' | 'sanction' | 'pending' | 'completed' | 'flagged'

interface BadgeProps {
  variant: BadgeVariant
  children: ReactNode
  icon?: ReactNode
  className?: string
}

const Badge = ({ variant, children, icon, className = '' }: BadgeProps) => {
  const variantClasses = {
    'high-risk': 'bg-error text-white',
    'medium-risk': 'bg-warning text-white',
    'low-risk': 'bg-success text-white',
    'contract': 'bg-doc-contract text-white',
    'email': 'bg-doc-email text-white',
    'court': 'bg-doc-court text-white',
    'compliance': 'bg-doc-compliance text-white',
    'sanction': 'bg-doc-sanction text-white',
    'pending': 'bg-info text-white',
    'completed': 'bg-success text-white',
    'flagged': 'bg-warning text-white',
  }
  
  const baseClasses = 'inline-flex items-center gap-1.5 px-2 py-1 rounded text-small font-semibold'
  
  return (
    <span className={`${baseClasses} ${variantClasses[variant]} ${className}`}>
      {icon && <span className="flex items-center">{icon}</span>}
      {children}
    </span>
  )
}

export default Badge
