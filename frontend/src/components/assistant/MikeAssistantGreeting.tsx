import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { MikeIcon } from '@/components/Chat/MikeIcon'

const ICON_SIZE = 30
const GAP = 12

export function MikeAssistantGreeting() {
  const { user } = useAuth()
  const [loaded, setLoaded] = useState(false)
  const [iconOffset, setIconOffset] = useState(0)
  const [textOffset, setTextOffset] = useState(0)
  const textRef = useRef<HTMLHeadingElement>(null)

  const username =
    user?.full_name?.trim() || user?.email?.split('@')[0] || 'друг'

  useLayoutEffect(() => {
    if (!textRef.current) return
    const h1Width = textRef.current.offsetWidth
    setIconOffset((h1Width + GAP) / 2)
    setTextOffset((ICON_SIZE + GAP) / 2)
  }, [username])

  useEffect(() => {
    if (!iconOffset) return
    const timer = window.setTimeout(() => setLoaded(true), 100)
    return () => window.clearTimeout(timer)
  }, [iconOffset])

  return (
    <div className="relative mb-10 flex items-center justify-center">
      <div
        className="absolute top-[-14px] h-[30px] w-[30px]"
        style={{
          left: '50%',
          transform: loaded
            ? `translateX(calc(-50% - ${iconOffset}px))`
            : 'translateX(-50%)',
          transition: 'transform 900ms cubic-bezier(0.25, 0.46, 0.45, 0.94)',
        }}
      >
        <MikeIcon size={ICON_SIZE} />
      </div>
      <h1
        ref={textRef}
        className="absolute whitespace-nowrap font-serif text-4xl font-light text-gray-900"
        style={{
          left: '50%',
          transform: loaded
            ? `translateX(calc(-50% + ${textOffset}px))`
            : 'translateX(-50%)',
          opacity: loaded ? 1 : 0,
          transition:
            'transform 900ms cubic-bezier(0.25, 0.46, 0.45, 0.94), opacity 800ms ease-in-out 300ms',
        }}
      >
        Привет, {username}
      </h1>
    </div>
  )
}

export function MikeAssistantDisclaimer() {
  return (
    <p className="py-3 text-center text-xs text-gray-500">
      ИИ может ошибаться. Ответы не являются юридической консультацией.
    </p>
  )
}
