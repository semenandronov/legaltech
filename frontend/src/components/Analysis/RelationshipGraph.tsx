import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import { RelationshipNode, RelationshipLink } from '../../services/api'
import './Analysis.css'

interface RelationshipGraphProps {
  nodes: RelationshipNode[]
  links: RelationshipLink[]
  onDocumentClick?: (documentName: string, page?: number | null) => void
}

// Extended node type for D3 force simulation
interface SimulationNode extends RelationshipNode, d3.SimulationNodeDatum {
  x?: number
  y?: number
  fx?: number | null
  fy?: number | null
}

const RelationshipGraph = ({ nodes, links, onDocumentClick }: RelationshipGraphProps) => {
  const svgRef = useRef<SVGSVGElement>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [selectedLink, setSelectedLink] = useState<string | null>(null)
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)

  // Color scheme for node types
  const nodeTypeColors: Record<string, string> = {
    Person: '#3b82f6',
    Organization: '#10b981',
    Contract: '#f59e0b',
    Event: '#ef4444',
    default: '#6b7280'
  }

  // Get color for node type
  const getNodeColor = (type: string): string => {
    return nodeTypeColors[type] || nodeTypeColors.default
  }

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const width = svgRef.current.clientWidth || 800
    const height = svgRef.current.clientHeight || 600

    // Create container for zoom/pan
    const container = svg.append('g')

    // Setup zoom behavior
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        container.attr('transform', event.transform.toString())
      })

    svg.call(zoom)

    // Create node map for quick lookup
    const nodeMap = new Map(nodes.map(n => [n.id, n]))
    
    const simulationNodes: SimulationNode[] = nodes.map(node => ({ ...node }))
    
    const formattedLinks: d3.SimulationLinkDatum<SimulationNode>[] = links
      .map((link) => {
        const sourceNode = nodeMap.get(link.source)
        const targetNode = nodeMap.get(link.target)
        if (sourceNode && targetNode && sourceNode.id !== targetNode.id) {
          return {
            source: sourceNode,
            target: targetNode,
            type: link.type,
            label: link.label
          } as d3.SimulationLinkDatum<SimulationNode> & { type: string; label?: string | null }
        }
        return null
      })
      .filter((link): link is d3.SimulationLinkDatum<SimulationNode> & { type: string; label?: string | null } => link !== null)

    // Create force simulation
    const simulation = d3
      .forceSimulation(simulationNodes)
      .force(
        'link',
        d3
          .forceLink(formattedLinks)
          .id((d) => (d as SimulationNode).id)
          .distance(100)
      )
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(30))

    // Create links
    const link = container
      .append('g')
      .attr('class', 'relationship-links')
      .selectAll('line')
      .data(formattedLinks)
      .enter()
      .append('line')
      .attr('class', 'relationship-link')
      .attr('stroke', '#999')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', (d) => {
        const sourceId = (d.source as SimulationNode).id
        const targetId = (d.target as SimulationNode).id
        const linkKey = `${sourceId}-${targetId}`
        return selectedLink === linkKey ? 3 : 2
      })
      .on('mouseover', function (_event, d) {
        const sourceId = (d.source as SimulationNode).id
        const targetId = (d.target as SimulationNode).id
        const linkKey = `${sourceId}-${targetId}`
        setSelectedLink(linkKey)
        d3.select(this).attr('stroke-width', 3).attr('stroke-opacity', 1)
      })
      .on('mouseout', function () {
        setSelectedLink(null)
        d3.select(this).attr('stroke-width', 2).attr('stroke-opacity', 0.6)
      })

    // Create link labels
    const linkLabels = container
      .append('g')
      .attr('class', 'relationship-link-labels')
      .selectAll('text')
      .data(formattedLinks)
      .enter()
      .append('text')
      .attr('class', 'relationship-link-label')
      .text((d) => {
        const linkData = d as d3.SimulationLinkDatum<SimulationNode> & { type: string; label?: string | null }
        return linkData.label || linkData.type
      })
      .attr('font-size', '10px')
      .attr('fill', '#666')
      .attr('text-anchor', 'middle')
      .attr('pointer-events', 'none')

    // Create nodes
    const node = container
      .append('g')
      .attr('class', 'relationship-nodes')
      .selectAll('circle')
      .data(simulationNodes)
      .enter()
      .append('circle')
      .attr('class', 'relationship-node')
      .attr('r', 15)
      .attr('fill', (d) => getNodeColor(d.type))
      .attr('stroke', (d) => (selectedNode === d.id || hoveredNode === d.id ? '#fff' : '#000'))
      .attr('stroke-width', (d) => (selectedNode === d.id || hoveredNode === d.id ? 3 : 1))
      .attr('cursor', 'pointer')
      .call(
        d3
          .drag<SVGCircleElement, SimulationNode>()
          .on('start', dragstarted)
          .on('drag', dragged)
          .on('end', dragended)
      )
      .on('click', (event, d) => {
        event.stopPropagation()
        setSelectedNode(selectedNode === d.id ? null : d.id)
        if (d.source_document && onDocumentClick) {
          onDocumentClick(d.source_document, d.source_page)
        }
      })
      .on('mouseover', function (_event, d) {
        setHoveredNode(d.id)
        d3.select(this).attr('stroke-width', 3).attr('stroke', '#fff')
      })
      .on('mouseout', function (_event, d) {
        if (selectedNode !== d.id) {
          setHoveredNode(null)
          d3.select(this).attr('stroke-width', selectedNode === d.id ? 3 : 1).attr('stroke', '#000')
        }
      })

    // Create node labels
    const nodeLabels = container
      .append('g')
      .attr('class', 'relationship-node-labels')
      .selectAll('text')
      .data(simulationNodes)
      .enter()
      .append('text')
      .attr('class', 'relationship-node-label')
      .text((d) => d.label)
      .attr('font-size', '12px')
      .attr('fill', '#1f2937')
      .attr('text-anchor', 'middle')
      .attr('dy', 30)
      .attr('pointer-events', 'none')

    // Tooltip
    const tooltip = d3
      .select('body')
      .append('div')
      .attr('class', 'relationship-tooltip')
      .style('opacity', 0)
      .style('position', 'absolute')
      .style('background', 'rgba(0, 0, 0, 0.8)')
      .style('color', 'white')
      .style('padding', '8px')
      .style('border-radius', '4px')
      .style('font-size', '12px')
      .style('pointer-events', 'none')
      .style('z-index', '1000')

    node
      .on('mouseover', function (event, d) {
        tooltip
          .transition()
          .duration(200)
          .style('opacity', 1)
        tooltip
          .html(
            `<strong>${d.label}</strong><br/>` +
            `Тип: ${d.type}<br/>` +
            (d.source_document ? `Документ: ${d.source_document}<br/>` : '') +
            (d.source_page ? `Стр. ${d.source_page}` : '')
          )
          .style('left', event.pageX + 10 + 'px')
          .style('top', event.pageY - 10 + 'px')
      })
      .on('mouseout', function () {
        tooltip.transition().duration(200).style('opacity', 0)
      })

    // Update positions on simulation tick
    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y)

      linkLabels
        .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
        .attr('y', (d: any) => (d.source.y + d.target.y) / 2)

      node.attr('cx', (d) => (d as SimulationNode).x ?? 0).attr('cy', (d) => (d as SimulationNode).y ?? 0)

      nodeLabels.attr('x', (d) => (d as SimulationNode).x ?? 0).attr('y', (d) => ((d as SimulationNode).y ?? 0) + 25)
    })

    function dragstarted(event: d3.D3DragEvent<SVGCircleElement, SimulationNode, SimulationNode>) {
      if (!event.active) simulation.alphaTarget(0.3).restart()
      const node = event.subject as SimulationNode
      node.fx = node.x ?? 0
      node.fy = node.y ?? 0
    }

    function dragged(event: d3.D3DragEvent<SVGCircleElement, SimulationNode, SimulationNode>) {
      const node = event.subject as SimulationNode
      node.fx = event.x
      node.fy = event.y
    }

    function dragended(event: d3.D3DragEvent<SVGCircleElement, SimulationNode, SimulationNode>) {
      if (!event.active) simulation.alphaTarget(0)
      const node = event.subject as SimulationNode
      node.fx = null
      node.fy = null
    }

    // Cleanup
    return () => {
      simulation.stop()
      tooltip.remove()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, links, selectedNode, selectedLink, hoveredNode])

  if (nodes.length === 0) {
    return (
      <div className="relationship-graph-empty">
        <p>Нет данных для отображения графа связей</p>
      </div>
    )
  }

  return (
    <div className="relationship-graph-container">
      <svg ref={svgRef} className="relationship-graph-svg" width="100%" height="600" />
    </div>
  )
}

export default RelationshipGraph

