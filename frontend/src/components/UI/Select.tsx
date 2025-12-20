import { SelectHTMLAttributes, forwardRef } from 'react'

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  error?: string
  helperText?: string
  options: { value: string; label: string }[]
}

const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, error, helperText, options, className = '', ...props }, ref) => {
    const baseClasses = 'w-full px-3 py-2.5 text-body bg-secondary border border-border rounded-md transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed appearance-none bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'12\' viewBox=\'0 0 12 12\'%3E%3Cpath fill=\'%23666B78\' d=\'M6 9L1 4h10z\'/%3E%3C/svg%3E")] bg-[length:12px_12px] bg-[right_12px_center] bg-no-repeat pr-10'
    
    const errorClasses = error ? 'border-error focus:ring-error focus:border-error' : ''
    
    const classes = `${baseClasses} ${errorClasses} ${className}`
    
    return (
      <div className="w-full">
        {label && (
          <label className="block text-small font-medium text-primary mb-1.5">
            {label}
          </label>
        )}
        <select
          ref={ref}
          className={classes}
          {...props}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
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

Select.displayName = 'Select'

export default Select
