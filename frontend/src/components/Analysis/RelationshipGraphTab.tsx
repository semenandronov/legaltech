import { useEffect, useState, useMemo } from 'react'
import { getRelationshipGraph, RelationshipGraph, RelationshipNode, RelationshipLink } from '../../services/api'
import RelationshipGraphComponent from './RelationshipGraph'
import { useNavigate } from 'react-router-dom'
import './Analysis.css'

interface RelationshipGraphTabProps {
  caseId: string
}

const RelationshipGraphTab = ({ caseId }: RelationshipGraphTabProps) => {
  const [graphData, setGraphData] = useState<RelationshipGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedNodeType, setSelectedNodeType] = useState<string>('all')
  const [selectedLinkType, setSelectedLinkType] = useState<string>('all')
  const navigate = useNavigate()

  useEffect(() => {
    loadGraphData()
  }, [caseId])

  const loadGraphData = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getRelationshipGraph(caseId)
      setGraphData(data)
    } catch (err: any) {
      console.error('Ошибка при загрузке графа связей:', err)
      setError(err.response?.data?.detail || 'Ошибка при загрузке графа связей')
    } finally {
      setLoading(false)
    }
  }

  // Get unique node types
  const nodeTypes = useMemo(() => {
    if (!graphData) return []
    const types = new Set(graphData.nodes.map((n) => n.type))
    return Array.from(types).sort()
  }, [graphData])

  // Get unique link types
  const linkTypes = useMemo(() => {
    if (!graphData) return []
    const types = new Set(graphData.links.map((l) => l.type))
    return Array.from(types).sort()
  }, [graphData])

  // Filter graph data
  const filteredGraphData = useMemo(() => {
    if (!graphData) return null

    let filteredNodes = graphData.nodes
    let filteredLinks = graphData.links

    // Filter by node type
    if (selectedNodeType !== 'all') {
      filteredNodes = graphData.nodes.filter((n) => n.type === selectedNodeType)
      // Only include links where both source and target are in filtered nodes
      const nodeIds = new Set(filteredNodes.map((n) => n.id))
      filteredLinks = graphData.links.filter(
        (l) => nodeIds.has(l.source) && nodeIds.has(l.target)
      )
    }

    // Filter by link type
    if (selectedLinkType !== 'all') {
      filteredLinks = filteredLinks.filter((l) => l.type === selectedLinkType)
      // Include all nodes that are connected by filtered links
      const connectedNodeIds = new Set<string>()
      filteredLinks.forEach((l) => {
        connectedNodeIds.add(l.source)
        connectedNodeIds.add(l.target)
      })
      filteredNodes = filteredNodes.filter((n) => connectedNodeIds.has(n.id))
    }

    return {
      nodes: filteredNodes,
      links: filteredLinks
    }
  }, [graphData, selectedNodeType, selectedLinkType])

  const handleDocumentClick = (documentName: string, page?: number | null) => {
    // Navigate to documents page with document name
    navigate(`/cases/${caseId}/documents?highlight=${encodeURIComponent(documentName)}${page ? `&page=${page}` : ''}`)
  }

  // Statistics
  const stats = useMemo(() => {
    if (!graphData) return null

    const nodeTypeCounts: Record<string, number> = {}
    graphData.nodes.forEach((node) => {
      nodeTypeCounts[node.type] = (nodeTypeCounts[node.type] || 0) + 1
    })

    const linkTypeCounts: Record<string, number> = {}
    graphData.links.forEach((link) => {
      linkTypeCounts[link.type] = (linkTypeCounts[link.type] || 0) + 1
    })

    return {
      totalNodes: graphData.nodes.length,
      totalLinks: graphData.links.length,
      nodeTypeCounts,
      linkTypeCounts
    }
  }, [graphData])

  if (loading) {
    return <div className="analysis-tab-loading">Загрузка графа связей...</div>
  }

  if (error) {
    return (
      <div className="analysis-tab-empty">
        <div className="analysis-tab-empty-icon">⚠️</div>
        <h3>Ошибка загрузки</h3>
        <p>{error}</p>
        <button
          onClick={loadGraphData}
          style={{
            marginTop: '16px',
            padding: '8px 16px',
            background: '#4299e1',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer'
          }}
        >
          Попробовать снова
        </button>
      </div>
    )
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="analysis-tab-empty">
        <div className="analysis-tab-empty-icon">🔗</div>
        <h3>Граф связей не найден</h3>
        <p>Запустите анализ с типом "relationship" для извлечения связей между сущностями</p>
      </div>
    )
  }

  return (
    <div className="relationship-graph-tab">
      <div className="relationship-graph-tab-header">
        <div className="relationship-graph-tab-header-left">
          <h2>Граф связей</h2>
          <button
            className="relationship-refresh-btn"
            onClick={loadGraphData}
            title="Обновить граф"
          >
            🔄 Обновить
          </button>
        </div>
        {stats && (
          <div className="relationship-stats">
            <span className="relationship-stat-item">
              Нод: <strong>{stats.totalNodes}</strong>
            </span>
            <span className="relationship-stat-item">
              Связей: <strong>{stats.totalLinks}</strong>
            </span>
          </div>
        )}
      </div>

      <div className="relationship-controls">
        <div className="relationship-control-group">
          <label htmlFor="node-type-filter">Тип нод:</label>
          <select
            id="node-type-filter"
            className="relationship-filter-select"
            value={selectedNodeType}
            onChange={(e) => setSelectedNodeType(e.target.value)}
          >
            <option value="all">Все ({graphData.nodes.length})</option>
            {nodeTypes.map((type) => (
              <option key={type} value={type}>
                {type} ({stats?.nodeTypeCounts[type] || 0})
              </option>
            ))}
          </select>
        </div>

        <div className="relationship-control-group">
          <label htmlFor="link-type-filter">Тип связей:</label>
          <select
            id="link-type-filter"
            className="relationship-filter-select"
            value={selectedLinkType}
            onChange={(e) => setSelectedLinkType(e.target.value)}
          >
            <option value="all">Все ({graphData.links.length})</option>
            {linkTypes.map((type) => (
              <option key={type} value={type}>
                {type} ({stats?.linkTypeCounts[type] || 0})
              </option>
            ))}
          </select>
        </div>
      </div>

      {filteredGraphData && filteredGraphData.nodes.length > 0 ? (
        <RelationshipGraphComponent
          nodes={filteredGraphData.nodes}
          links={filteredGraphData.links}
          onDocumentClick={handleDocumentClick}
        />
      ) : (
        <div className="relationship-graph-empty">
          <p>Нет данных для отображения с выбранными фильтрами</p>
        </div>
      )}

      {/* Legend */}
      <div className="relationship-legend">
        <h4>Легенда</h4>
        <div className="relationship-legend-item">
          <div
            className="relationship-legend-color"
            style={{ background: '#3b82f6' }}
          />
          <span>Person</span>
        </div>
        <div className="relationship-legend-item">
          <div
            className="relationship-legend-color"
            style={{ background: '#10b981' }}
          />
          <span>Organization</span>
        </div>
        <div className="relationship-legend-item">
          <div
            className="relationship-legend-color"
            style={{ background: '#f59e0b' }}
          />
          <span>Contract</span>
        </div>
        <div className="relationship-legend-item">
          <div
            className="relationship-legend-color"
            style={{ background: '#ef4444' }}
          />
          <span>Event</span>
        </div>
      </div>
    </div>
  )
}

export default RelationshipGraphTab

