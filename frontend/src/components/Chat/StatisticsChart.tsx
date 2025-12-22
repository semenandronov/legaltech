"use client"

import React from 'react'
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid } from 'recharts'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/UI/chart"
import './Chat.css'

interface StatisticsChartProps {
  data: {
    type: 'bar' | 'pie'
    title?: string
    data: Array<{
      name: string
      value: number
      [key: string]: any
    }>
  }
}

const COLORS = ['hsl(var(--primary))', '#10b981', '#f59e0b', '#ef4444', '#a855f7', '#6b7280']

const StatisticsChart: React.FC<StatisticsChartProps> = ({ data }) => {
  if (!data || !data.data || data.data.length === 0) {
    return null
  }

  const chartConfig: ChartConfig = {
    value: {
      label: "Значение",
      color: "hsl(var(--primary))",
    },
  }

  return (
    <div className="chat-statistics-chart">
      {data.title && (
        <div className="chat-statistics-chart-title">{data.title}</div>
      )}
      <div className="chat-statistics-chart-container">
        {data.type === 'bar' ? (
          <ChartContainer config={chartConfig} className="h-[300px] w-full">
            <BarChart data={data.data}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis 
                dataKey="name" 
                tickLine={false}
                axisLine={false}
                tickMargin={8}
              />
              <YAxis 
                tickLine={false}
                axisLine={false}
                tickMargin={8}
              />
              <ChartTooltip
                cursor={false}
                content={<ChartTooltipContent indicator="dot" />}
              />
              <Bar 
                dataKey="value" 
                fill="var(--color-value)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ChartContainer>
        ) : (
          <ChartContainer config={chartConfig} className="h-[300px] w-full">
            <PieChart>
              <Pie
                data={data.data}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                outerRadius={80}
                fill="var(--color-value)"
                dataKey="value"
              >
                {data.data.map((_entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <ChartTooltip
                content={<ChartTooltipContent indicator="dot" />}
              />
            </PieChart>
          </ChartContainer>
        )}
      </div>
    </div>
  )
}

export default StatisticsChart
