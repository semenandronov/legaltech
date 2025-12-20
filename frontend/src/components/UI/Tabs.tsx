import { ReactNode, useState, createContext, useContext } from 'react'

interface TabsContextType {
  activeTab: string
  setActiveTab: (tab: string) => void
}

const TabsContext = createContext<TabsContextType | undefined>(undefined)

interface TabsProps {
  children: ReactNode
  defaultTab: string
  className?: string
}

export const Tabs = ({ children, defaultTab, className = '' }: TabsProps) => {
  const [activeTab, setActiveTab] = useState(defaultTab)
  
  return (
    <TabsContext.Provider value={{ activeTab, setActiveTab }}>
      <div className={className}>
        {children}
      </div>
    </TabsContext.Provider>
  )
}

interface TabListProps {
  children: ReactNode
  className?: string
}

export const TabList = ({ children, className = '' }: TabListProps) => {
  return (
    <div className={`flex border-b border-border ${className}`}>
      {children}
    </div>
  )
}

interface TabProps {
  id: string
  children: ReactNode
  className?: string
}

export const Tab = ({ id, children, className = '' }: TabProps) => {
  const context = useContext(TabsContext)
  if (!context) throw new Error('Tab must be used within Tabs')
  
  const { activeTab, setActiveTab } = context
  const isActive = activeTab === id
  
  return (
    <button
      onClick={() => setActiveTab(id)}
      className={`px-4 py-2 text-body font-medium border-b-2 transition-colors ${
        isActive
          ? 'border-primary text-primary'
          : 'border-transparent text-secondary hover:text-primary'
      } ${className}`}
    >
      {children}
    </button>
  )
}

interface TabPanelProps {
  id: string
  children: ReactNode
  className?: string
}

export const TabPanel = ({ id, children, className = '' }: TabPanelProps) => {
  const context = useContext(TabsContext)
  if (!context) throw new Error('TabPanel must be used within Tabs')
  
  const { activeTab } = context
  if (activeTab !== id) return null
  
  return (
    <div className={`mt-4 ${className}`}>
      {children}
    </div>
  )
}
