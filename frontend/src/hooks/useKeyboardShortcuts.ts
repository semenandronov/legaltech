import { useEffect, useCallback } from 'react'

export interface KeyboardShortcutsConfig {
  onNext?: () => void
  onPrev?: () => void
  onConfirm?: () => void
  onReject?: () => void
  onWithhold?: () => void
  onQueue?: () => void
  onFlag?: () => void
  onComment?: () => void
  onCommandPalette?: () => void
  onQuickSearch?: () => void
  enabled?: boolean
}

export const useKeyboardShortcuts = (config: KeyboardShortcutsConfig) => {
  const {
    onNext,
    onPrev,
    onConfirm,
    onReject,
    onWithhold,
    onQueue,
    onFlag,
    onComment,
    onCommandPalette,
    onQuickSearch,
    enabled = true
  } = config

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (!enabled) return

    // Игнорируем если пользователь вводит текст в input/textarea
    const target = e.target as HTMLElement
    if (
      target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.isContentEditable
    ) {
      // Разрешаем только специальные команды
      if (e.key === ':' && onCommandPalette) {
        e.preventDefault()
        onCommandPalette()
        return
      }
      if (e.key === '/' && onQuickSearch) {
        e.preventDefault()
        onQuickSearch()
        return
      }
      return
    }

    // Navigation
    if (e.key === 'ArrowRight' || e.key === 'End') {
      if (onNext) {
        e.preventDefault()
        onNext()
      }
      return
    }

    if (e.key === 'ArrowLeft' || e.key === 'Home') {
      if (onPrev) {
        e.preventDefault()
        onPrev()
      }
      return
    }

    if (e.key === ' ' && !e.shiftKey) {
      if (onNext) {
        e.preventDefault()
        onNext()
      }
      return
    }

    if (e.key === ' ' && e.shiftKey) {
      if (onPrev) {
        e.preventDefault()
        onPrev()
      }
      return
    }

    if (e.key === 'n' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      if (onNext) {
        e.preventDefault()
        onNext()
      }
      return
    }

    if (e.key === 'p' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      if (onPrev) {
        e.preventDefault()
        onPrev()
      }
      return
    }

    // Actions
    if (e.key === 'y' || e.key === 'a') {
      if (onConfirm) {
        e.preventDefault()
        onConfirm()
      }
      return
    }

    if (e.key === 'n' && e.shiftKey) {
      if (onReject) {
        e.preventDefault()
        onReject()
      }
      return
    }

    if (e.key === 'w') {
      if (onWithhold) {
        e.preventDefault()
        onWithhold()
      }
      return
    }

    if (e.key === 'q') {
      if (onQueue) {
        e.preventDefault()
        onQueue()
      }
      return
    }

    if (e.key === 'f') {
      if (onFlag) {
        e.preventDefault()
        onFlag()
      }
      return
    }

    if (e.key === 'c' && !e.ctrlKey && !e.metaKey) {
      if (onComment) {
        e.preventDefault()
        onComment()
      }
      return
    }

    // Commands
    if (e.key === ':' && !e.shiftKey) {
      if (onCommandPalette) {
        e.preventDefault()
        onCommandPalette()
      }
      return
    }

    if (e.key === '/' && !e.shiftKey) {
      if (onQuickSearch) {
        e.preventDefault()
        onQuickSearch()
      }
      return
    }

    // Help
    if (e.key === '?' || (e.key === 'h' && e.shiftKey)) {
      // TODO: Показать справку по shortcuts
      return
    }
  }, [
    enabled,
    onNext,
    onPrev,
    onConfirm,
    onReject,
    onWithhold,
    onQueue,
    onFlag,
    onComment,
    onCommandPalette,
    onQuickSearch
  ])

  useEffect(() => {
    if (enabled) {
      window.addEventListener('keydown', handleKeyDown)
      return () => {
        window.removeEventListener('keydown', handleKeyDown)
      }
    }
  }, [enabled, handleKeyDown])
}

export default useKeyboardShortcuts
