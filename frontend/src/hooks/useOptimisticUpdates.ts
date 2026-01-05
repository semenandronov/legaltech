"use client"

import { useCallback, useRef } from "react"

export interface OptimisticUpdate<T> {
  id: string
  type: string
  data: T
  timestamp: number
  rollback: () => void
}

/**
 * Hook for managing optimistic updates
 * 
 * Provides utilities to:
 * - Apply optimistic updates immediately
 * - Rollback on error
 * - Track update history
 */
export function useOptimisticUpdates<T = any>() {
  const updatesRef = useRef<Map<string, OptimisticUpdate<T>>>(new Map())
  const rollbackStackRef = useRef<Array<() => void>>([])

  const applyOptimisticUpdate = useCallback(
    <TData = any>(
      id: string,
      type: string,
      optimisticData: TData,
      rollback: () => void
    ): TData => {
      const update: OptimisticUpdate<TData> = {
        id,
        type,
        data: optimisticData,
        timestamp: Date.now(),
        rollback,
      }

      updatesRef.current.set(id, update as any)
      rollbackStackRef.current.push(rollback)

      return optimisticData
    },
    []
  )

  const rollbackUpdate = useCallback((id: string) => {
    const update = updatesRef.current.get(id)
    if (update) {
      update.rollback()
      updatesRef.current.delete(id)
    }
  }, [])

  const rollbackLast = useCallback(() => {
    const rollback = rollbackStackRef.current.pop()
    if (rollback) {
      rollback()
    }
  }, [])

  const rollbackAll = useCallback(() => {
    while (rollbackStackRef.current.length > 0) {
      const rollback = rollbackStackRef.current.pop()
      if (rollback) {
        rollback()
      }
    }
    updatesRef.current.clear()
  }, [])

  const clearUpdate = useCallback((id: string) => {
    updatesRef.current.delete(id)
  }, [])

  const clearAll = useCallback(() => {
    updatesRef.current.clear()
    rollbackStackRef.current = []
  }, [])

  const getUpdate = useCallback((id: string) => {
    return updatesRef.current.get(id)
  }, [])

  const hasUpdates = useCallback(() => {
    return updatesRef.current.size > 0
  }, [])

  return {
    applyOptimisticUpdate,
    rollbackUpdate,
    rollbackLast,
    rollbackAll,
    clearUpdate,
    clearAll,
    getUpdate,
    hasUpdates,
  }
}

