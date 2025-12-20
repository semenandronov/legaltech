import { InputHTMLAttributes, forwardRef } from 'react'

interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: string
}

const Radio = forwardRef<HTMLInputElement, RadioProps>(
  ({ label, className = '', ...props }, ref) => {
    return (
      <label className={`flex items-center gap-2 cursor-pointer ${className}`}>
        <input
          type="radio"
          ref={ref}
          className="w-5 h-5 rounded-full border-2 border-border bg-secondary text-primary focus:ring-2 focus:ring-primary focus:ring-offset-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          {...props}
        />
        {label && (
          <span className="text-body text-primary">
            {label}
          </span>
        )}
      </label>
    )
  }
)

Radio.displayName = 'Radio'

export default Radio
