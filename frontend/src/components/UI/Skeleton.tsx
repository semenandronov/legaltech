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
  className,
  variant,
  ...props
}: SkeletonProps) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted", className)}
      style={{ height, ...style }}
      {...props}
    />
  )
    <div
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  )
}

export { Skeleton }
export default Skeleton
