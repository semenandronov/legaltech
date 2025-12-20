import { ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'

interface BreadcrumbItem {
  label: string
  href?: string
}

interface BreadcrumbsProps {
  items: BreadcrumbItem[]
  className?: string
}

const Breadcrumbs = ({ items, className = '' }: BreadcrumbsProps) => {
  return (
    <nav className={`flex items-center gap-2 text-small ${className}`}>
      {items.map((item, index) => (
        <div key={index} className="flex items-center gap-2">
          {index > 0 && <ChevronRight className="w-4 h-4 text-secondary" />}
          {item.href ? (
            <a
              href={item.href}
              className="text-secondary hover:text-primary transition-colors"
            >
              {item.label}
            </a>
          ) : (
            <span className={index === items.length - 1 ? 'text-primary font-medium' : 'text-secondary'}>
              {item.label}
            </span>
          )}
        </div>
      ))}
    </nav>
  )
}

export default Breadcrumbs
