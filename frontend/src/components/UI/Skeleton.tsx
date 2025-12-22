import { cn } from "@/lib/utils"

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: string
  height?: number | string
}

function Skeleton({
  className,
  variant,
  height,
  style,
  ...props
}: SkeletonProps) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted", className)}
      style={{ height, ...style }}
      {...props}
    />
  )
}

export { Skeleton }
export type { SkeletonProps }
export default Skeleton
