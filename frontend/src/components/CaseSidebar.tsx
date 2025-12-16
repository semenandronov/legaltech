interface CaseSidebarProps {
  caseId: string
  fileNames: string[]
}

const CaseSidebar = ({ caseId, fileNames }: CaseSidebarProps) => {
  return (
    <aside className="case-sidebar">
      <div className="case-sidebar-section">
        <div className="case-sidebar-title-row">
          <span className="case-sidebar-label">Дело</span>
          <span className="case-sidebar-id">#{caseId.slice(0, 8)}</span>
        </div>
        <p className="case-sidebar-meta">
          Загружено файлов: {fileNames.length || 0}
        </p>
      </div>

      <div className="case-sidebar-section">
        <p className="case-sidebar-label">Документы</p>
        <ul className="case-sidebar-files">
          {fileNames.length === 0 && (
            <li className="case-sidebar-file-empty">Файлы не загружены</li>
          )}
          {fileNames.map((name) => (
            <li key={name} className="case-sidebar-file">
              <span className="case-sidebar-file-icon">📄</span>
              <span className="case-sidebar-file-name">{name}</span>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  )
}

export default CaseSidebar


