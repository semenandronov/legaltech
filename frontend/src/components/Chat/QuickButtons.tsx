import React from 'react'
import { Box, Button, Flex, Text } from '@radix-ui/themes'
import './Chat.css'

interface QuickButtonsProps {
  onClassifyAll?: () => void
  onFindPrivilege?: () => void
  onTimeline?: () => void
  onStatistics?: () => void
  onExtractEntities?: () => void
}

const QuickButtons: React.FC<QuickButtonsProps> = ({
  onClassifyAll,
  onFindPrivilege,
  onTimeline,
  onStatistics,
  onExtractEntities
}) => {
  return (
    <Box 
      className="chat-quick-buttons"
      style={{
        padding: '16px 24px',
        borderBottom: '1px solid var(--color-border)',
        backgroundColor: 'var(--color-surface)',
      }}
    >
      <Text 
        className="chat-quick-buttons-title"
        size="1"
        weight="bold"
        style={{
          marginBottom: '12px',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
          color: 'var(--color-text-secondary)',
          display: 'block',
        }}
      >
        📌 Quick Start:
      </Text>
      <Flex 
        className="chat-quick-buttons-grid"
        wrap="wrap"
        gap="2"
      >
        {onClassifyAll && (
          <Button
            variant="soft"
            size="2"
            onClick={onClassifyAll}
            aria-label="Классифицировать все документы"
          >
            [Classify All]
          </Button>
        )}
        {onFindPrivilege && (
          <Button
            variant="soft"
            size="2"
            onClick={onFindPrivilege}
            aria-label="Найти привилегированные документы"
          >
            [Find Privilege]
          </Button>
        )}
        {onTimeline && (
          <Button
            variant="soft"
            size="2"
            onClick={onTimeline}
            aria-label="Показать таймлайн"
          >
            [Timeline]
          </Button>
        )}
        {onStatistics && (
          <Button
            variant="soft"
            size="2"
            onClick={onStatistics}
            aria-label="Показать статистику"
          >
            [Statistics]
          </Button>
        )}
        {onExtractEntities && (
          <Button
            variant="soft"
            size="2"
            onClick={onExtractEntities}
            aria-label="Извлечь сущности"
          >
            [Extract Entities]
          </Button>
        )}
      </Flex>
    </Box>
  )
}

export default QuickButtons
