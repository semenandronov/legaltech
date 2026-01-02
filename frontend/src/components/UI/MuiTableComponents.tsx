import React from 'react'
import {
  Box,
  TableContainer,
  Paper,
  TableHead,
  TableRow,
  TableCell,
  Typography,
  Toolbar,
  IconButton,
  Chip,
  Tooltip,
} from '@mui/material'
import {
  ArrowUpward,
  ArrowDownward,
  UnfoldMore,
  FilterList,
} from '@mui/icons-material'

interface TableContainerProps {
  children: React.ReactNode
  elevation?: number
  variant?: 'elevation' | 'outlined'
  sx?: any
}

/**
 * Обертка для контейнера таблицы с единым стилем
 */
export const MuiTableContainer: React.FC<TableContainerProps> = ({
  children,
  elevation = 0,
  variant = 'outlined',
  sx,
}) => {
  return (
    <TableContainer
      component={Paper}
      variant={variant}
      elevation={elevation}
      sx={{
        border: '1px solid #E5E7EB',
        borderRadius: '8px',
        overflow: 'hidden',
        ...sx,
      }}
    >
      {children}
    </TableContainer>
  )
}

interface TableHeaderProps {
  children: React.ReactNode
  sticky?: boolean
}

/**
 * Заголовок таблицы с единым стилем
 */
export const MuiTableHeader: React.FC<TableHeaderProps> = ({
  children,
  sticky = false,
}) => {
  return (
    <TableHead
      sx={{
        bgcolor: '#F9FAFB',
        borderBottom: '1px solid #E5E7EB',
        position: sticky ? 'sticky' : 'static',
        top: 0,
        zIndex: 10,
      }}
    >
      {children}
    </TableHead>
  )
}

interface TableHeaderRowProps {
  children: React.ReactNode
}

/**
 * Строка заголовка таблицы
 */
export const MuiTableHeaderRow: React.FC<TableHeaderRowProps> = ({ children }) => {
  return (
    <TableRow
      sx={{
        bgcolor: '#F9FAFB',
        borderBottom: '1px solid #E5E7EB',
        '&:hover': {
          bgcolor: '#F9FAFB',
        },
      }}
    >
      {children}
    </TableRow>
  )
}

interface TableHeaderCellProps {
  children: React.ReactNode
  align?: 'left' | 'center' | 'right'
  width?: number | string
  minWidth?: number | string
  sx?: any
}

/**
 * Ячейка заголовка таблицы
 */
export const MuiTableHeaderCell: React.FC<TableHeaderCellProps> = ({
  children,
  align = 'left',
  width,
  minWidth,
  sx,
}) => {
  return (
    <TableCell
      align={align}
      sx={{
        borderRight: '1px solid #E5E7EB',
        bgcolor: '#F9FAFB',
        py: 1.5,
        px: 2,
        fontWeight: 600,
        color: '#1F2937',
        width,
        minWidth,
        '&:last-child': {
          borderRight: 'none',
        },
        ...sx,
      }}
    >
      {children}
    </TableCell>
  )
}

interface TableBodyRowProps {
  children: React.ReactNode
  index?: number
  selected?: boolean
  onClick?: () => void
  sx?: any
}

/**
 * Строка тела таблицы
 */
export const MuiTableBodyRow: React.FC<TableBodyRowProps> = ({
  children,
  index,
  selected = false,
  onClick,
  sx,
}) => {
  return (
    <TableRow
      onClick={onClick}
      sx={{
        bgcolor: index !== undefined && index % 2 === 0 ? '#FFFFFF' : '#F9FAFB',
        borderBottom: '1px solid #E5E7EB',
        cursor: onClick ? 'pointer' : 'default',
        '&:hover': {
          bgcolor: '#F3F4F6',
        },
        ...(selected && {
          bgcolor: '#EFF6FF',
          '&:hover': {
            bgcolor: '#DBEAFE',
          },
        }),
        ...sx,
      }}
    >
      {children}
    </TableRow>
  )
}

interface TableBodyCellProps {
  children: React.ReactNode
  align?: 'left' | 'center' | 'right'
  sx?: any
}

/**
 * Ячейка тела таблицы
 */
export const MuiTableBodyCell: React.FC<TableBodyCellProps> = ({
  children,
  align = 'left',
  sx,
}) => {
  return (
    <TableCell
      align={align}
      sx={{
        borderRight: '1px solid #E5E7EB',
        px: 2,
        py: 1,
        color: '#1F2937',
        '&:last-child': {
          borderRight: 'none',
        },
        ...sx,
      }}
    >
      {children}
    </TableCell>
  )
}

interface SortIndicatorProps {
  sortDirection: 'asc' | 'desc' | false
  onClick?: () => void
}

/**
 * Индикатор сортировки
 */
export const SortIndicator: React.FC<SortIndicatorProps> = ({
  sortDirection,
  onClick,
}) => {
  const getIcon = () => {
    if (sortDirection === 'asc') {
      return <ArrowUpward fontSize="small" sx={{ color: '#2563EB' }} />
    }
    if (sortDirection === 'desc') {
      return <ArrowDownward fontSize="small" sx={{ color: '#2563EB' }} />
    }
    return <UnfoldMore fontSize="small" sx={{ color: '#9CA3AF' }} />
  }

  return (
    <Box
      component="span"
      onClick={onClick}
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        ml: 0.5,
        cursor: onClick ? 'pointer' : 'default',
      }}
    >
      {getIcon()}
    </Box>
  )
}

interface FilterIndicatorProps {
  active: boolean
  count?: number
}

/**
 * Индикатор активного фильтра
 */
export const FilterIndicator: React.FC<FilterIndicatorProps> = ({
  active,
  count,
}) => {
  if (!active) return null

  return (
    <Tooltip title={count ? `${count} активных фильтров` : 'Фильтр активен'}>
      <Chip
        icon={<FilterList fontSize="small" />}
        label={count}
        size="small"
        sx={{
          height: 20,
          ml: 1,
          bgcolor: '#DBEAFE',
          color: '#1E40AF',
          '& .MuiChip-icon': {
            color: '#2563EB',
          },
        }}
      />
    </Tooltip>
  )
}

interface TableToolbarProps {
  title?: string
  selectedCount?: number
  onClearSelection?: () => void
  actions?: React.ReactNode
  children?: React.ReactNode
}

/**
 * Toolbar для таблицы с действиями
 */
export const TableToolbar: React.FC<TableToolbarProps> = ({
  title,
  selectedCount = 0,
  onClearSelection,
  actions,
  children,
}) => {
  return (
    <Toolbar
      sx={{
        pl: { sm: 2 },
        pr: { xs: 1, sm: 1 },
        bgcolor: selectedCount > 0 ? '#EFF6FF' : 'transparent',
        borderBottom: '1px solid #E5E7EB',
        minHeight: '64px !important',
      }}
    >
      {selectedCount > 0 ? (
        <Typography
          sx={{ flex: '1 1 100%' }}
          color="inherit"
          variant="subtitle1"
          component="div"
        >
          Выбрано: {selectedCount}
        </Typography>
      ) : (
        <Typography
          sx={{ flex: '1 1 100%' }}
          variant="h6"
          id="tableTitle"
          component="div"
        >
          {title}
        </Typography>
      )}
      {selectedCount > 0 && onClearSelection && (
        <IconButton onClick={onClearSelection} size="small">
          <Typography variant="body2" sx={{ color: '#6B7280' }}>
            Сбросить
          </Typography>
        </IconButton>
      )}
      {actions}
      {children}
    </Toolbar>
  )
}

interface EmptyTableRowProps {
  colSpan: number
  message?: string
}

/**
 * Пустая строка таблицы (нет данных)
 */
export const EmptyTableRow: React.FC<EmptyTableRowProps> = ({
  colSpan,
  message = 'Нет данных',
}) => {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} align="center" sx={{ py: 4 }}>
        <Typography variant="body2" sx={{ color: '#6B7280' }}>
          {message}
        </Typography>
      </TableCell>
    </TableRow>
  )
}

interface LoadingTableRowProps {
  colSpan: number
  rows?: number
}

/**
 * Строки загрузки таблицы
 */
export const LoadingTableRow: React.FC<LoadingTableRowProps> = ({
  colSpan,
  rows = 5,
}) => {
  return (
    <>
      {Array.from({ length: rows }).map((_, index) => (
        <TableRow key={index}>
          <TableCell colSpan={colSpan} sx={{ py: 2 }}>
            <Box
              sx={{
                display: 'flex',
                gap: 1,
                alignItems: 'center',
              }}
            >
              <Box
                sx={{
                  width: '100%',
                  height: 20,
                  bgcolor: '#F3F4F6',
                  borderRadius: 1,
                  animation: 'pulse 1.5s ease-in-out infinite',
                  '@keyframes pulse': {
                    '0%, 100%': { opacity: 1 },
                    '50%': { opacity: 0.5 },
                  },
                }}
              />
            </Box>
          </TableCell>
        </TableRow>
      ))}
    </>
  )
}

