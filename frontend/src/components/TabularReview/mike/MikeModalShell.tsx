"use client"

import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

interface MikeModalShellProps {
  open: boolean
  onClose: () => void
  breadcrumbs?: string[]
  children: ReactNode
  footer?: ReactNode
  className?: string
  bodyClassName?: string
}

export function MikeModalShell({
  open,
  onClose,
  breadcrumbs = ['Табличный обзор'],
  children,
  footer,
  className = '',
  bodyClassName = '',
}: MikeModalShellProps) {
  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div className="ws-mike-modal-overlay" onClick={onClose}>
      <div
        className={`ws-mike-modal-panel ${className}`.trim()}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="ws-mike-modal-header">
          <div className="ws-mike-modal-breadcrumbs">
            {breadcrumbs.map((crumb, index) => (
              <span key={`${crumb}-${index}`} className="flex items-center gap-1.5">
                {index > 0 && <span aria-hidden>›</span>}
                <span>{crumb}</span>
              </span>
            ))}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ws-mike-modal-close"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className={`ws-mike-modal-body ${bodyClassName}`.trim()}>{children}</div>

        {footer && <div className="ws-mike-modal-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
