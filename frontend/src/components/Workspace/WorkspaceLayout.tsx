"use client"

import React from 'react'
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/UI/resizable"
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
    <ResizablePanelGroup orientation="horizontal" className="workspace-layout h-full">
      <ResizablePanel defaultSize={20} minSize={15} maxSize={30}>
        <div className="workspace-left-panel h-full">
          {leftPanel}
        </div>
      </ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel defaultSize={60} minSize={40}>
        <div className="workspace-center-panel h-full">
          {centerPanel}
        </div>
      </ResizablePanel>
      {!rightPanelCollapsed && (
        <>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={20} minSize={15} maxSize={30}>
            <div className="workspace-right-panel h-full">
              {rightPanel}
              {onToggleRightPanel && (
                <button 
                  className="workspace-toggle-chat"
                  onClick={onToggleRightPanel}
                  aria-label="Свернуть чат"
                >
                  ◀
                </button>
              )}
            </div>
          </ResizablePanel>
        </>
      )}
    </ResizablePanelGroup>
  )
}

export default WorkspaceLayout
