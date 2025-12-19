import { useState, useCallback } from 'react'

export interface UseBatchSelectionReturn {
  selectedItems: Set<string>
  isSelected: (id: string) => boolean
  toggleSelection: (id: string) => void
  selectAll: () => void
  selectVisible: (visibleIds: string[]) => void
  clearSelection: () => void
  selectItems: (ids: string[]) => void
}

export const useBatchSelection = (
  allItems: string[],
  visibleItems?: string[]
): UseBatchSelectionReturn => {
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set())

  const isSelected = useCallback((id: string) => {
    return selectedItems.has(id)
  }, [selectedItems])

  const toggleSelection = useCallback((id: string) => {
    setSelectedItems(prev => {
      const newSet = new Set(prev)
      if (newSet.has(id)) {
        newSet.delete(id)
      } else {
        newSet.add(id)
      }
      return newSet
    })
  }, [])

  const selectAll = useCallback(() => {
    if (selectedItems.size === allItems.length) {
      setSelectedItems(new Set())
    } else {
      setSelectedItems(new Set(allItems))
    }
  }, [allItems, selectedItems.size])

  const selectVisible = useCallback((visibleIds: string[]) => {
    const visibleSet = new Set(visibleIds)
    const allVisibleSelected = visibleIds.every(id => selectedItems.has(id))
    
    if (allVisibleSelected) {
      // Если все видимые выбраны, снимаем выбор с видимых
      setSelectedItems(prev => {
        const newSet = new Set(prev)
        visibleIds.forEach(id => newSet.delete(id))
        return newSet
      })
    } else {
      // Иначе выбираем все видимые
      setSelectedItems(prev => {
        const newSet = new Set(prev)
        visibleIds.forEach(id => newSet.add(id))
        return newSet
      })
    }
  }, [selectedItems])

  const clearSelection = useCallback(() => {
    setSelectedItems(new Set())
  }, [])

  const selectItems = useCallback((ids: string[]) => {
    setSelectedItems(new Set(ids))
  }, [])

  return {
    selectedItems,
    isSelected,
    toggleSelection,
    selectAll,
    selectVisible,
    clearSelection,
    selectItems
  }
}

export default useBatchSelection
