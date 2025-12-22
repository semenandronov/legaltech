import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Plus } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'
import UploadArea from '../UploadArea'
import ThemeToggle from '../UI/ThemeToggle'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../UI/dialog'
import { Button } from '../UI/Button'
import { AppBreadcrumbs } from './Breadcrumbs'
import { CommandPalette } from './CommandPalette'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/UI/dropdown-menu'
import { Avatar, AvatarFallback } from '@/components/UI/avatar'

const Header = () => {
  const { user, logout } = useAuth()
  const [showUploadModal, setShowUploadModal] = useState(false)
  const navigate = useNavigate()

  const handleUpload = (caseId: string, _fileNames: string[]) => {
    setShowUploadModal(false)
    navigate(`/cases/${caseId}/workspace`)
    window.location.reload()
  }

  return (
    <>
      <header className="bg-secondary border-b border-border px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4 flex-1">
            <AppBreadcrumbs />
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={() => {
                const event = new KeyboardEvent('keydown', {
                  key: 'k',
                  metaKey: true,
                  bubbles: true,
                })
                document.dispatchEvent(event)
              }}
              className="hidden sm:flex"
            >
              <Search className="h-4 w-4" />
              <span className="sr-only">Поиск</span>
            </Button>
            <Button variant="primary" onClick={() => setShowUploadModal(true)}>
              <Plus className="mr-2 h-4 w-4" />
              <span className="hidden sm:inline">Загрузить новое дело</span>
              <span className="sm:hidden">Новое</span>
            </Button>
            <ThemeToggle />
            {user && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" className="relative h-8 w-8 rounded-full">
                    <Avatar className="h-8 w-8">
                      <AvatarFallback>
                        {user.full_name?.[0]?.toUpperCase() || user.email[0].toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-56" align="end" forceMount>
                  <DropdownMenuLabel className="font-normal">
                    <div className="flex flex-col space-y-1">
                      <p className="text-sm font-medium leading-none">
                        {user.full_name || user.email}
                      </p>
                      <p className="text-xs leading-none text-muted-foreground">
                        {user.email}
                      </p>
                    </div>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => navigate('/settings')}>
                    Настройки
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={async () => {
                    await logout()
                    navigate('/login')
                  }}>
                    Выйти
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>
      </header>

      <Dialog open={showUploadModal} onOpenChange={setShowUploadModal}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>Загрузить новое дело</DialogTitle>
            <DialogDescription>
              Загрузите документы для создания нового дела
            </DialogDescription>
          </DialogHeader>
          <UploadArea onUpload={handleUpload} />
        </DialogContent>
      </Dialog>
      <CommandPalette />
    </>
  )
}

export default Header