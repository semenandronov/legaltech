import React from 'react'
import './ShortcutsHelp.css'

interface ShortcutsHelpProps {
  onClose: () => void
}

const ShortcutsHelp: React.FC<ShortcutsHelpProps> = ({ onClose }) => {
  return (
    <div className="shortcuts-help-overlay" onClick={onClose}>
      <div className="shortcuts-help-modal" onClick={(e) => e.stopPropagation()}>
        <div className="shortcuts-help-header">
          <h2>Keyboard Shortcuts</h2>
          <button className="shortcuts-help-close" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>

        <div className="shortcuts-help-content">
          <div className="shortcuts-help-section">
            <h3>Navigation</h3>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">→ / End</span>
              <span className="shortcuts-help-desc">Next document</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">← / Home</span>
              <span className="shortcuts-help-desc">Previous document</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">Space / n</span>
              <span className="shortcuts-help-desc">Next</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">Shift+Space / p</span>
              <span className="shortcuts-help-desc">Previous</span>
            </div>
          </div>

          <div className="shortcuts-help-section">
            <h3>Actions</h3>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">y / a</span>
              <span className="shortcuts-help-desc">Confirm (Yes/Accept)</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">n</span>
              <span className="shortcuts-help-desc">Reject (No)</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">w</span>
              <span className="shortcuts-help-desc">Withhold</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">q</span>
              <span className="shortcuts-help-desc">Queue for manual review</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">f</span>
              <span className="shortcuts-help-desc">Flag for attorney</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">c</span>
              <span className="shortcuts-help-desc">Add comment</span>
            </div>
          </div>

          <div className="shortcuts-help-section">
            <h3>Commands</h3>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">:</span>
              <span className="shortcuts-help-desc">Command palette (like Vim)</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">/</span>
              <span className="shortcuts-help-desc">Quick search in document</span>
            </div>
            <div className="shortcuts-help-item">
              <span className="shortcuts-help-key">? / Shift+h</span>
              <span className="shortcuts-help-desc">Show this help</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ShortcutsHelp
