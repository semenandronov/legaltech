import { useMemo } from 'react'

interface RulerProps {
  length: number
  orientation: 'horizontal' | 'vertical'
  zoom?: number
}

export const Ruler = ({ length, orientation, zoom = 100 }: RulerProps) => {
  const pixelsPerInch = 96 * (zoom / 100)
  
  const marks = useMemo(() => {
    const marksList: Array<{ position: number; value: number; isMajor: boolean }> = []
    const maxInches = Math.ceil(length / pixelsPerInch)
    const seenPositions = new Set<number>()
    
    // Генерируем все метки (каждые 0.25 дюйма)
    for (let i = 0; i <= maxInches * 4; i++) {
      const position = (i * pixelsPerInch) / 4
      if (position <= length && !seenPositions.has(position)) {
        seenPositions.add(position)
        const isMajor = i % 4 === 0
        marksList.push({
          position,
          value: i / 4,
          isMajor,
        })
      }
    }
    
    return marksList
  }, [length, pixelsPerInch])

  const isHorizontal = orientation === 'horizontal'

  return (
    <div
      className="bg-white border-b border-r"
      style={{
        width: isHorizontal ? `${length}px` : '20px',
        height: isHorizontal ? '20px' : `${length}px`,
        borderColor: '#dadce0',
        position: 'relative',
        flexShrink: 0,
      }}
    >
      {marks.map((mark, idx) => {
        const isMajor = mark.isMajor
        const markHeight = isMajor ? '20px' : '10px'
        
        return (
          <div
            key={`${mark.position}-${idx}`}
            className="absolute"
            style={{
              [isHorizontal ? 'left' : 'top']: `${mark.position}px`,
              [isHorizontal ? 'height' : 'width']: markHeight,
              [isHorizontal ? 'width' : 'height']: '1px',
              borderLeft: isHorizontal ? '1px solid #dadce0' : 'none',
              borderTop: !isHorizontal ? '1px solid #dadce0' : 'none',
              fontSize: '10px',
              color: '#5f6368',
            }}
          >
            {isMajor && (
              <span
                style={{
                  position: 'absolute',
                  [isHorizontal ? 'top' : 'left']: '2px',
                  [isHorizontal ? 'left' : 'top']: '2px',
                  whiteSpace: 'nowrap',
                  ...(isHorizontal ? {} : {
                    transform: 'rotate(-90deg)',
                    transformOrigin: 'left top',
                  }),
                }}
              >
                {Math.floor(mark.value)}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

