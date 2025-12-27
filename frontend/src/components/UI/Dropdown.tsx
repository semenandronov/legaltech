import { ReactNode, useState, useRef } from 'react'
import { Menu, MenuItem, ListItemIcon, ListItemText, Box } from '@mui/material'

interface DropdownItem {
  label: string
  onClick: () => void
  icon?: ReactNode
  disabled?: boolean
  danger?: boolean
}

interface DropdownProps {
  trigger: ReactNode
  items: DropdownItem[]
  align?: 'left' | 'right'
  className?: string
}

const Dropdown = ({ trigger, items, align = 'right', className = '' }: DropdownProps) => {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const triggerRef = useRef<HTMLDivElement>(null)
  const isOpen = Boolean(anchorEl)

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
  }

  const handleClose = () => {
    setAnchorEl(null)
  }

  const handleItemClick = (item: DropdownItem) => {
    if (!item.disabled) {
      item.onClick()
      handleClose()
    }
  }

  return (
    <Box className={className} sx={{ position: 'relative', display: 'inline-block' }}>
      <Box ref={triggerRef} onClick={handleClick} sx={{ cursor: 'pointer' }}>
        {trigger}
      </Box>
      <Menu
        anchorEl={anchorEl}
        open={isOpen}
        onClose={handleClose}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: align,
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: align,
        }}
        PaperProps={{
          sx: {
            minWidth: 200,
            mt: 0.5,
          },
        }}
      >
        {items.map((item, index) => (
          <MenuItem
            key={index}
            onClick={() => handleItemClick(item)}
            disabled={item.disabled}
            sx={{
              color: item.danger ? 'error.main' : 'text.primary',
              '&:hover': {
                bgcolor: 'action.hover',
              },
            }}
          >
            {item.icon && <ListItemIcon>{item.icon}</ListItemIcon>}
            <ListItemText>{item.label}</ListItemText>
          </MenuItem>
        ))}
      </Menu>
    </Box>
  )
}

export default Dropdown
