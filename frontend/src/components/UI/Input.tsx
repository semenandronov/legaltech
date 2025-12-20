import { InputHTMLAttributes, forwardRef } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, className = '', ...props }, ref) => {
    const baseClasses = 'w-full px-3 py-2.5 text-body bg-secondary border border-border rounded-md transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary focus:border-primary placeholder:text-secondary placeholder:opacity-60 disabled:opacity-50 disabled:cursor-not-allowed'
    
    const errorClasses = error ? 'border-error focus:ring-error focus:border-error' : ''
    
    const classes = `${baseClasses} ${errorClasses} ${className}`
    
    return (
      <div className="w-full">
        {label && (
          <label className="block text-small font-medium text-primary mb-1.5">
            {label}
          </label>
        )}
        <input
          ref={ref}
          className={classes}
          {...props}
        />
        {error && (
          <p className="mt-1.5 text-small text-error flex items-center gap-1">
            <span>❌</span>
            {error}
          </p>
        )}
        {helperText && !error && (
          <p className="mt-1.5 text-small text-secondary">
            {helperText}
          </p>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'

export default Input
