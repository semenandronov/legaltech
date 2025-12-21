import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import { RelationshipNode, RelationshipLink } from '../../services/api'
import './Analysis.css'

interface RelationshipGraphProps {
  nodes: RelationshipNode[]
  links: RelationshipLink[]
  onDocumentClick?: (documentName: string, page?: number | null) => void
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

    // Convert link source/target strings to node references
    const formattedLinks = links.map(link => ({
      ...link,
      source: nodeMap.get(link.source) || link.source,
      target: nodeMap.get(link.target) || link.target
    })).filter(link => link.source !== link.target && (typeof link.source !== 'string') && (typeof link.target !== 'string'))

    // Create force simulation
    const simulation = d3
      .forceSimulation(nodes as any)
      .force(
        'link',
        d3
          .forceLink(formattedLinks)
          .id((d: any) => d.id)
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
      .attr('stroke-width', (d: any) => {
        const linkKey = `${typeof d.source === 'object' ? d.source.id : d.source}-${typeof d.target === 'object' ? d.target.id : d.target}`
        return selectedLink === linkKey ? 3 : 2
      })
      .on('mouseover', function (event, d: any) {
        const linkKey = `${typeof d.source === 'object' ? d.source.id : d.source}-${typeof d.target === 'object' ? d.target.id : d.target}`
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
      .text((d) => d.label || d.type)
      .attr('font-size', '10px')
      .attr('fill', '#666')
      .attr('text-anchor', 'middle')
      .attr('pointer-events', 'none')

    // Create nodes
    const node = container
      .append('g')
      .attr('class', 'relationship-nodes')
      .selectAll('circle')
      .data(nodes)
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
          .drag<SVGCircleElement, RelationshipNode>()
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
      .on('mouseover', function (event, d) {
        setHoveredNode(d.id)
        d3.select(this).attr('stroke-width', 3).attr('stroke', '#fff')
      })
      .on('mouseout', function (event, d) {
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
      .data(nodes)
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

      node.attr('cx', (d: any) => d.x).attr('cy', (d: any) => d.y)

      nodeLabels.attr('x', (d: any) => d.x).attr('y', (d: any) => d.y)
    })

    function dragstarted(event: d3.D3DragEvent<SVGCircleElement, RelationshipNode, RelationshipNode>) {
      if (!event.active) simulation.alphaTarget(0.3).restart()
      event.subject.fx = event.subject.x
      event.subject.fy = event.subject.y
    }

    function dragged(event: d3.D3DragEvent<SVGCircleElement, RelationshipNode, RelationshipNode>) {
      event.subject.fx = event.x
      event.subject.fy = event.y
    }

    function dragended(event: d3.D3DragEvent<SVGCircleElement, RelationshipNode, RelationshipNode>) {
      if (!event.active) simulation.alphaTarget(0)
      event.subject.fx = null
      event.subject.fy = null
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

