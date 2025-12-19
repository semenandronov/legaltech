import React from 'react'
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
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

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#a855f7', '#6b7280']

const StatisticsChart: React.FC<StatisticsChartProps> = ({ data }) => {
  if (!data || !data.data || data.data.length === 0) {
    return null
  }

  return (
    <div className="chat-statistics-chart">
      {data.title && (
        <div className="chat-statistics-chart-title">{data.title}</div>
      )}
      <div className="chat-statistics-chart-container">
        {data.type === 'bar' ? (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data.data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey="value" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={data.data}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {data.data.map((_entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

export default StatisticsChart
