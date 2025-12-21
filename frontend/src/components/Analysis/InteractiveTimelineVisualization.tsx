import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import { TimelineEvent } from '../../services/api'
import './Analysis.css'

interface InteractiveTimelineVisualizationProps {
  events: TimelineEvent[]
  onDocumentClick?: (documentName: string, page?: number | null) => void
}

const InteractiveTimelineVisualization = ({
  events,
  onDocumentClick
}: InteractiveTimelineVisualizationProps) => {
  const svgRef = useRef<SVGSVGElement>(null)
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null)
  const [hoveredEvent, setHoveredEvent] = useState<string | null>(null)

  useEffect(() => {
    if (!svgRef.current || events.length === 0) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const margin = { top: 40, right: 40, bottom: 60, left: 100 }
    const width = svgRef.current.clientWidth || 800
    const height = Math.max(400, events.length * 40 + margin.top + margin.bottom)

    svg.attr('width', width).attr('height', height)

    // Filter valid events
    const validEvents = events.filter(
      (e) => e.date && !isNaN(new Date(e.date).getTime())
    )

    if (validEvents.length === 0) {
      svg
        .append('text')
        .attr('x', width / 2)
        .attr('y', height / 2)
        .attr('text-anchor', 'middle')
        .attr('fill', '#6b7280')
        .text('Нет событий с валидными датами')
      return
    }

    // Sort events by date
    validEvents.sort(
      (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
    )

    // Create time scale
    const dates = validEvents.map((e) => new Date(e.date))
    const minDate = d3.min(dates)!
    const maxDate = d3.max(dates)!

    // Extend range slightly for better visualization
    const dateRange = maxDate.getTime() - minDate.getTime()
    const extendedMin = new Date(minDate.getTime() - dateRange * 0.1)
    const extendedMax = new Date(maxDate.getTime() + dateRange * 0.1)

    const xScale = d3
      .scaleTime()
      .domain([extendedMin, extendedMax])
      .range([margin.left, width - margin.right])

    // Create vertical positions for events
    const yScale = d3
      .scaleBand()
      .domain(validEvents.map((_, i) => i.toString()))
      .range([margin.top, height - margin.bottom])
      .padding(0.3)

    // Create axis
    const xAxis = d3.axisBottom(xScale).ticks(10).tickFormat(d3.timeFormat('%d.%m.%Y'))
    const axisGroup = svg
      .append('g')
      .attr('transform', `translate(0, ${height - margin.bottom})`)
      .call(xAxis)

    axisGroup.selectAll('text').attr('fill', '#6b7280').attr('font-size', '11px')
    axisGroup.selectAll('line, path').attr('stroke', '#d1d5db')

    // Create timeline line
    const timelineLine = svg
      .append('line')
      .attr('x1', margin.left)
      .attr('x2', width - margin.right)
      .attr('y1', margin.top + (height - margin.top - margin.bottom) / 2)
      .attr('y2', margin.top + (height - margin.top - margin.bottom) / 2)
      .attr('stroke', '#3b82f6')
      .attr('stroke-width', 2)

    // Create event markers and labels
    const eventGroup = svg.append('g').attr('class', 'interactive-timeline-events')

    // Tooltip (create before using it)
    const tooltip = d3
      .select('body')
      .append('div')
      .attr('class', 'interactive-timeline-tooltip')
      .style('opacity', 0)
      .style('position', 'absolute')
      .style('background', 'rgba(0, 0, 0, 0.8)')
      .style('color', 'white')
      .style('padding', '10px')
      .style('border-radius', '6px')
      .style('font-size', '12px')
      .style('pointer-events', 'none')
      .style('z-index', '1000')
      .style('max-width', '300px')
      .style('line-height', '1.5')

    validEvents.forEach((event, index) => {
      const x = xScale(new Date(event.date))
      const y = yScale(index.toString())! + yScale.bandwidth() / 2

      const eventGroupItem = eventGroup
        .append('g')
        .attr('class', 'interactive-timeline-event')
        .attr('data-event-id', event.id)
        .attr('transform', `translate(${x}, ${y})`)

      // Connection line to timeline
      eventGroupItem
        .append('line')
        .attr('x1', 0)
        .attr('y1', 0)
        .attr('x2', 0)
        .attr('y2', margin.top + (height - margin.top - margin.bottom) / 2 - y)
        .attr('stroke', '#9ca3af')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '3,3')

      // Event marker (circle)
      const marker = eventGroupItem
        .append('circle')
        .attr('r', 8)
        .attr('fill', '#3b82f6')
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)
        .attr('cursor', 'pointer')
        .style('transition', 'r 0.2s')

      // Highlight on hover/select
      if (selectedEvent === event.id) {
        marker.attr('r', 12).attr('fill', '#2563eb').attr('stroke-width', 3)
      } else if (hoveredEvent === event.id) {
        marker.attr('r', 10).attr('fill', '#60a5fa')
      }

      // Event label
      const label = eventGroupItem
        .append('text')
        .attr('x', 15)
        .attr('y', 5)
        .attr('fill', '#1f2937')
        .attr('font-size', '12px')
        .attr('font-weight', selectedEvent === event.id ? '600' : '400')
        .text(
          event.event_type
            ? `${event.event_type}: ${event.description.substring(0, 50)}${event.description.length > 50 ? '...' : ''}`
            : event.description.substring(0, 60)
        )

      // Click handler
      const handleClick = function (e: MouseEvent) {
        e.stopPropagation()
        setSelectedEvent(selectedEvent === event.id ? null : event.id)
        if (event.source_document && onDocumentClick) {
          onDocumentClick(event.source_document, event.source_page)
        }
      }

      const handleMouseOver = function (e: MouseEvent) {
        setHoveredEvent(event.id)
        d3.select(this).transition().duration(200).attr('r', 10).attr('fill', '#60a5fa')
        label.attr('font-weight', '600')
        
        const dateStr = new Date(event.date).toLocaleDateString('ru-RU', {
          year: 'numeric',
          month: 'long',
          day: 'numeric'
        })

        tooltip
          .transition()
          .duration(200)
          .style('opacity', 1)
          .html(
            `<strong>${event.event_type || 'Событие'}</strong><br/>` +
            `<em>${dateStr}</em><br/><br/>` +
            `${event.description}<br/><br/>` +
            (event.source_document
              ? `📄 ${event.source_document}${event.source_page ? `, стр. ${event.source_page}` : ''}`
              : '')
          )
          .style('left', (e.pageX + 10) + 'px')
          .style('top', (e.pageY - 10) + 'px')
      }

      const handleMouseOut = function () {
        if (selectedEvent !== event.id) {
          setHoveredEvent(null)
          d3.select(this).transition().duration(200).attr('r', selectedEvent === event.id ? 12 : 8).attr('fill', selectedEvent === event.id ? '#2563eb' : '#3b82f6')
          label.attr('font-weight', selectedEvent === event.id ? '600' : '400')
        }
        tooltip.transition().duration(200).style('opacity', 0)
      }

      marker
        .style('cursor', 'pointer')
        .on('click', handleClick)
        .on('mouseover', handleMouseOver)
        .on('mouseout', handleMouseOut)
      
      label
        .style('cursor', 'pointer')
        .on('click', handleClick)
        .on('mouseover', handleMouseOver)
        .on('mouseout', handleMouseOut)
    })

    // Cleanup
    return () => {
      tooltip.remove()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, selectedEvent, hoveredEvent])

  if (events.length === 0) {
    return (
      <div className="interactive-timeline-empty">
        <p>Нет событий для отображения</p>
      </div>
    )
  }

  return (
    <div className="interactive-timeline-container">
      <svg ref={svgRef} className="interactive-timeline-svg" />
    </div>
  )
}

export default InteractiveTimelineVisualization

