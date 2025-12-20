import { TextareaHTMLAttributes, forwardRef } from 'react'

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  error?: string
  helperText?: string
}

const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, helperText, className = '', ...props }, ref) => {
    const baseClasses = 'w-full px-3 py-2.5 text-body bg-secondary border border-border rounded-md transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary focus:border-primary placeholder:text-secondary placeholder:opacity-60 disabled:opacity-50 disabled:cursor-not-allowed resize-y min-h-[100px]'
    
    const errorClasses = error ? 'border-error focus:ring-error focus:border-error' : ''
    
    const classes = `${baseClasses} ${errorClasses} ${className}`
    
    return (
      <div className="w-full">
        {label && (
          <label className="block text-small font-medium text-primary mb-1.5">
            {label}
          </label>
        )}
        <textarea
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

Textarea.displayName = 'Textarea'

export default Textarea
