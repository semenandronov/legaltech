import { HTMLAttributes, ReactNode } from 'react'
import { motion, HTMLMotionProps } from 'framer-motion'

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, keyof HTMLMotionProps<'div'>> {
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
    // Filter out drag handlers that conflict with framer-motion
    const { onDrag, onDragStart, onDragEnd, onDragEnter, onDragExit, onDragLeave, onDragOver, onDrop, ...motionProps } = props as any
    return (
      <motion.div
        className={classes}
        whileHover={{ scale: 1.01 }}
        transition={{ duration: 0.2 }}
        {...motionProps}
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
