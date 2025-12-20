import { HTMLAttributes, ReactNode } from 'react'
import { motion } from 'framer-motion'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  variant?: 'default' | 'gradient' | 'accent'
  hoverable?: boolean
}

const Card = ({ children, variant = 'default', hoverable = false, className = '', ...props }: CardProps) => {
  const baseClasses = 'bg-secondary border border-border rounded-lg p-4 transition-all duration-200'
  
  const variantClasses = {
    default: '',
    gradient: 'bg-gradient-to-br from-secondary to-tertiary',
    accent: 'border-l-4 border-l-primary',
  }
  
  const hoverClasses = hoverable ? 'cursor-pointer hover:border-primary hover:shadow-card-hover hover:scale-[1.01]' : ''
  
  const classes = `${baseClasses} ${variantClasses[variant]} ${hoverClasses} ${className}`
  
  if (hoverable) {
    return (
      <motion.div
        className={classes}
        whileHover={{ scale: 1.01 }}
        transition={{ duration: 0.2 }}
        {...props}
      >
        {children}
      </motion.div>
    )
  }
  
  return (
    <div className={classes} {...props}>
      {children}
    </div>
  )
}

export default Card
