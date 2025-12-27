// Legacy Sidebar component for backward compatibility
// This component wraps AppSidebar with default props for pages that haven't been migrated yet
import { AppSidebar } from './AppSidebar'

const Sidebar = () => {
  // For legacy pages, we keep the sidebar always open
  return <AppSidebar open={true} onClose={() => {}} variant="persistent" />
}

export default Sidebar
