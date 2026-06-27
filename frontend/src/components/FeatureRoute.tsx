import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { isProductFeatureEnabled, type ProductFeatureKey } from '@/lib/productFeatures'

interface FeatureRouteProps {
  feature: ProductFeatureKey
  redirectTo: string
  children: ReactNode
}

/** Редирект, если product feature выключен на сборке. */
export function FeatureRoute({ feature, redirectTo, children }: FeatureRouteProps) {
  if (!isProductFeatureEnabled(feature)) {
    return <Navigate to={redirectTo} replace />
  }
  return <>{children}</>
}
