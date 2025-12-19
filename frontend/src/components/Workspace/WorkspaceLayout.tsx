import React from 'react'
import './WorkspaceLayout.css'

interface WorkspaceLayoutProps {
  leftPanel: React.ReactNode
  centerPanel: React.ReactNode
  rightPanel: React.ReactNode
  rightPanelCollapsed?: boolean
  onToggleRightPanel?: () => void
}

const WorkspaceLayout: React.FC<WorkspaceLayoutProps> = ({
  leftPanel,
  centerPanel,
  rightPanel,
  rightPanelCollapsed = false,
  onToggleRightPanel
}) => {
  return (
    <div className="workspace-layout">
      <div className="workspace-left-panel">
        {leftPanel}
      </div>
      <div className="workspace-center-panel">
        {centerPanel}
      </div>
      <div className={`workspace-right-panel ${rightPanelCollapsed ? 'collapsed' : ''}`}>
        {rightPanel}
        {onToggleRightPanel && (
          <button 
            className="workspace-toggle-chat"
            onClick={onToggleRightPanel}
            aria-label={rightPanelCollapsed ? "Развернуть чат" : "Свернуть чат"}
          >
            {rightPanelCollapsed ? '💬' : '◀'}
          </button>
        )}
      </div>
    </div>
  )
}

export default WorkspaceLayout
