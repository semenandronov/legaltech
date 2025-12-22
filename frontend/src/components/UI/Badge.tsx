import * as React from "react"
import { cva } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
        outline: "text-foreground",
        // Additional variants for backward compatibility
        completed: "border-transparent bg-green-500 text-white hover:bg-green-600",
        pending: "border-transparent bg-yellow-500 text-white hover:bg-yellow-600",
        flagged: "border-transparent bg-red-500 text-white hover:bg-red-600",
        "high-risk": "border-transparent bg-red-600 text-white hover:bg-red-700",
        "medium-risk": "border-transparent bg-yellow-500 text-white hover:bg-yellow-600",
        "low-risk": "border-transparent bg-green-500 text-white hover:bg-green-600",
      } as const,
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export type BadgeVariant = "default" | "secondary" | "destructive" | "outline" | "completed" | "pending" | "flagged" | "high-risk" | "medium-risk" | "low-risk"

export interface BadgeProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "variant"> {
  variant?: BadgeVariant
}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant: variant as any }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
export default Badge
