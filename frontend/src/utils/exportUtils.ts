/**
 * Экспорт данных таблицы в CSV формат
 */
export function exportToCSV<T>(
  data: T[],
  columns: Array<{ id: string; header: string; accessorFn?: (row: T) => any }>,
  filename: string = 'export.csv'
): void {
  try {
    // Создаем заголовки
    const headers = columns.map(col => col.header).join(',')
    
    // Создаем строки данных
    const rows = data.map(row => {
      return columns.map(col => {
        let value: any
        if (col.accessorFn) {
          value = col.accessorFn(row)
        } else {
          value = (row as any)[col.id]
        }
        
        // Обработка значений для CSV
        if (value === null || value === undefined) {
          return ''
        }
        
        // Если значение содержит запятые, кавычки или переносы строк, оборачиваем в кавычки
        const stringValue = String(value)
        if (stringValue.includes(',') || stringValue.includes('"') || stringValue.includes('\n')) {
          return `"${stringValue.replace(/"/g, '""')}"`
        }
        
        return stringValue
      }).join(',')
    })
    
    // Объединяем все в CSV
    const csvContent = [headers, ...rows].join('\n')
    
    // Создаем BOM для правильного отображения кириллицы в Excel
    const BOM = '\uFEFF'
    const blob = new Blob([BOM + csvContent], { type: 'text/csv;charset=utf-8;' })
    
    // Создаем ссылку для скачивания
    const link = document.createElement('a')
    const url = URL.createObjectURL(blob)
    link.setAttribute('href', url)
    link.setAttribute('download', filename)
    link.style.visibility = 'hidden'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    
    // Освобождаем память
    URL.revokeObjectURL(url)
  } catch (error) {
    console.error('Error exporting to CSV:', error)
    throw error
  }
}

/**
 * Экспорт данных в JSON формат
 */
export function exportToJSON<T>(
  data: T[],
  filename: string = 'export.json'
): void {
  try {
    const jsonContent = JSON.stringify(data, null, 2)
    const blob = new Blob([jsonContent], { type: 'application/json' })
    
    const link = document.createElement('a')
    const url = URL.createObjectURL(blob)
    link.setAttribute('href', url)
    link.setAttribute('download', filename)
    link.style.visibility = 'hidden'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    
    URL.revokeObjectURL(url)
  } catch (error) {
    console.error('Error exporting to JSON:', error)
    throw error
  }
}

/**
 * Экспорт выбранных строк таблицы
 */
export function exportSelectedRows<T>(
  selectedRows: T[],
  columns: Array<{ id: string; header: string; accessorFn?: (row: T) => any }>,
  format: 'csv' | 'json' = 'csv',
  filename?: string
): void {
  if (selectedRows.length === 0) {
    throw new Error('No rows selected for export')
  }
  
  const defaultFilename = `export_${new Date().toISOString().split('T')[0]}.${format}`
  
  if (format === 'csv') {
    exportToCSV(selectedRows, columns, filename || defaultFilename)
  } else {
    exportToJSON(selectedRows, filename || defaultFilename)
  }
}

