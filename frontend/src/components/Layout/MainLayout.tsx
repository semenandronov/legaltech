import { ReactNode } from 'react'
import Header from './Header'
import { AppSidebar } from './AppSidebar'
import { SidebarProvider, SidebarInset } from '@/components/UI/sidebar'

interface MainLayoutProps {
  children: ReactNode
}

const MainLayout = ({ children }: MainLayoutProps) => {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <Header />
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}

export default MainLayout
