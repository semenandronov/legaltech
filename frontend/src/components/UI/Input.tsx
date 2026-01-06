import { InputHTMLAttributes, forwardRef } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, className = '', ...props }, ref) => {
    // Harvey style: минималистичный стиль, тонкая граница, плавные переходы
    const baseClasses = [
      'w-full px-3 py-2.5',
      'text-sm font-normal',
      'bg-bg-elevated text-text-primary',
      'border border-border rounded-md',
      'transition-all duration-150',
      'focus:outline-none focus:border-border-strong focus:ring-1 focus:ring-border-strong',
      'placeholder:text-text-muted',
      'disabled:opacity-50 disabled:cursor-not-allowed disabled:bg-bg-tertiary',
    ].join(' ')
    
    const errorClasses = error 
      ? 'border-error focus:border-error focus:ring-error' 
      : ''
    
    const classes = `${baseClasses} ${errorClasses} ${className}`.trim()
    
    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-text-primary mb-1.5">
            {label}
          </label>
        )}
        <input
          ref={ref}
          className={classes}
          {...props}
        />
        {error && (
          <p className="mt-1.5 text-xs text-error flex items-center gap-1">
            {error}
          </p>
        )}
        {helperText && !error && (
          <p className="mt-1.5 text-xs text-text-muted">
            {helperText}
          </p>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'

export default Input
