import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-strong focus-visible:ring-offset-2 focus-visible:ring-offset-bg-primary disabled:pointer-events-none disabled:opacity-50 disabled:cursor-not-allowed [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        // Primary: белый текст на черном фоне (Harvey style)
        default: "bg-accent text-bg-primary hover:bg-accent-hover active:bg-accent-muted rounded-md",
        primary: "bg-accent text-bg-primary hover:bg-accent-hover active:bg-accent-muted rounded-md",
        // Secondary: прозрачный с тонкой рамкой
        secondary: "border border-border bg-transparent text-text-primary hover:bg-bg-hover hover:border-border-strong active:bg-bg-active rounded-md",
        outline: "border border-border bg-transparent text-text-primary hover:bg-bg-hover hover:border-border-strong active:bg-bg-active rounded-md",
        // Ghost: без фона, только текст
        ghost: "text-text-primary hover:bg-bg-hover active:bg-bg-active rounded-md",
        // Destructive: красный акцент
        destructive: "bg-error text-text-primary hover:bg-error/90 active:bg-error/80 rounded-md",
        danger: "bg-error text-text-primary hover:bg-error/90 active:bg-error/80 rounded-md",
        // Link: подчеркнутый текст
        link: "text-text-primary underline-offset-4 hover:underline hover:text-accent p-0 h-auto",
      } as const,
      size: {
        sm: "h-8 px-3 text-sm rounded-md",
        default: "h-10 px-4 text-sm rounded-md",
        md: "h-10 px-4 text-sm rounded-md",
        lg: "h-12 px-6 text-base rounded-lg",
        icon: "h-10 w-10 rounded-md",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export type ButtonVariant = "default" | "destructive" | "outline" | "secondary" | "ghost" | "link" | "primary" | "danger"

export interface ButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "variant"> {
  asChild?: boolean
  isLoading?: boolean
  variant?: ButtonVariant
  size?: "default" | "sm" | "lg" | "icon"
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, isLoading, disabled, children, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant: variant as any, size, className }))}
        ref={ref}
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading ? (
          <>
            <span className="mr-2">...</span>
            {children}
          </>
        ) : children}
      </Comp>
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
export default Button
