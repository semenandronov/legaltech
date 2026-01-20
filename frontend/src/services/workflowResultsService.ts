/**
 * Сервис для передачи результатов Workflow в чат
 * 
 * После завершения workflow результаты сохраняются здесь,
 * затем пользователь перенаправляется на /chat, где
 * результаты автоматически отображаются как сообщение от ИИ.
 */

export interface WorkflowResultData {
  execution_id: string
  workflow_id: string
  workflow_name: string
  case_id: string
  status: 'completed' | 'failed'
  // Основная информация
  summary: string
  documents_processed: number
  elapsed_time: string
  started_at: string
  completed_at: string
  // Артефакты
  artifacts: {
    reports: Array<{ id: string; name: string; type: string; url?: string }>
    tables: Array<{ id: string; name: string; review_id?: string }>
    documents: Array<{ id: string; name: string }>
    checks: Array<{ id: string; document_id: string; playbook_name?: string }>
  }
  // Детальные результаты
  results?: Record<string, any>
  steps_completed: number
  total_steps: number
  // Ошибка (если failed)
  error?: string
}

const STORAGE_KEY = 'pending_workflow_result'

/**
 * Сохранить результат workflow для отображения в чате
 */
export const savePendingWorkflowResult = (result: WorkflowResultData): void => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(result))
  } catch (error) {
    console.error('Failed to save workflow result:', error)
  }
}

/**
 * Получить и удалить pending результат workflow
 * (результат удаляется после получения, чтобы не показывать повторно)
 */
export const consumePendingWorkflowResult = (): WorkflowResultData | null => {
  try {
    const data = localStorage.getItem(STORAGE_KEY)
    if (data) {
      localStorage.removeItem(STORAGE_KEY)
      return JSON.parse(data) as WorkflowResultData
    }
  } catch (error) {
    console.error('Failed to get workflow result:', error)
  }
  return null
}

/**
 * Проверить есть ли pending результат
 */
export const hasPendingWorkflowResult = (): boolean => {
  return localStorage.getItem(STORAGE_KEY) !== null
}

/**
 * Форматировать результат workflow в красивое markdown сообщение
 */
export const formatWorkflowResultMessage = (result: WorkflowResultData): string => {
  const isSuccess = result.status === 'completed'
  const statusEmoji = isSuccess ? '✅' : '❌'
  const statusText = isSuccess ? 'успешно завершён' : 'завершён с ошибкой'
  
  let message = `## ${statusEmoji} Workflow "${result.workflow_name}" ${statusText}\n\n`
  
  // Основная статистика
  message += `### 📊 Статистика выполнения\n`
  message += `- **Обработано документов:** ${result.documents_processed}\n`
  message += `- **Выполнено шагов:** ${result.steps_completed} из ${result.total_steps}\n`
  message += `- **Время выполнения:** ${result.elapsed_time}\n`
  message += `- **Начало:** ${new Date(result.started_at).toLocaleString('ru-RU')}\n`
  message += `- **Завершение:** ${new Date(result.completed_at).toLocaleString('ru-RU')}\n\n`
  
  // Краткое резюме
  if (result.summary) {
    message += `### 📝 Резюме\n${result.summary}\n\n`
  }
  
  // Созданные артефакты
  const hasArtifacts = 
    result.artifacts.reports.length > 0 ||
    result.artifacts.tables.length > 0 ||
    result.artifacts.documents.length > 0 ||
    result.artifacts.checks.length > 0
  
  if (hasArtifacts) {
    message += `### 📁 Созданные материалы\n\n`
    
    // Отчёты
    if (result.artifacts.reports.length > 0) {
      message += `**📄 Отчёты:**\n`
      result.artifacts.reports.forEach(report => {
        message += `- ${report.name} (${report.type})\n`
      })
      message += '\n'
    }
    
    // Таблицы
    if (result.artifacts.tables.length > 0) {
      message += `**📊 Таблицы (Tabular Review):**\n`
      result.artifacts.tables.forEach(table => {
        if (table.review_id) {
          message += `- [${table.name}](/cases/${result.case_id}/tabular-review/${table.review_id})\n`
        } else {
          message += `- ${table.name}\n`
        }
      })
      message += '\n'
    }
    
    // Документы
    if (result.artifacts.documents.length > 0) {
      message += `**📑 Документы:**\n`
      result.artifacts.documents.forEach(doc => {
        message += `- ${doc.name}\n`
      })
      message += '\n'
    }
    
    // Проверки Playbook
    if (result.artifacts.checks.length > 0) {
      message += `**✅ Проверки Playbook:**\n`
      result.artifacts.checks.forEach(check => {
        message += `- ${check.playbook_name || 'Проверка'} для документа ${check.document_id}\n`
      })
      message += '\n'
    }
  }
  
  // Ошибка
  if (result.error) {
    message += `### ⚠️ Ошибка\n\`\`\`\n${result.error}\n\`\`\`\n\n`
  }
  
  // Призыв к действию
  if (isSuccess) {
    message += `---\n\n`
    message += `💡 **Что дальше?**\n`
    message += `- Изучите созданные материалы по ссылкам выше\n`
    message += `- Задайте мне вопросы по результатам анализа\n`
    message += `- Запросите дополнительный анализ или уточнения\n`
  }
  
  return message
}

/**
 * Создать объект сообщения для чата из результата workflow
 */
export const createWorkflowResultChatMessage = (result: WorkflowResultData) => {
  return {
    id: `workflow-result-${result.execution_id}-${Date.now()}`,
    role: 'assistant' as const,
    content: formatWorkflowResultMessage(result),
    // Добавляем карточки таблиц если есть
    tableCards: result.artifacts.tables.map(table => ({
      reviewId: table.review_id || table.id,
      caseId: result.case_id,
      tableData: {
        id: table.id,
        name: table.name,
        description: `Создано workflow "${result.workflow_name}"`,
      }
    })),
    // Источники - созданные документы
    sources: result.artifacts.documents.map(doc => ({
      title: doc.name,
      file: doc.name,
    })),
  }
}

/**
 * Сохранить результат workflow как сообщение в истории чата на сервере
 */
export const saveWorkflowMessageToHistory = async (result: WorkflowResultData): Promise<{ success: boolean; session_id?: string }> => {
  try {
    const token = localStorage.getItem('access_token')
    if (!token) {
      console.error('No access token found')
      return { success: false }
    }

    const { getApiUrl } = await import('./api')
    
    const response = await fetch(getApiUrl('/api/assistant/chat/workflow-message'), {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        case_id: result.case_id,
        content: formatWorkflowResultMessage(result),
        workflow_id: result.workflow_id,
        workflow_name: result.workflow_name,
        artifacts: result.artifacts,
      }),
    })

    if (!response.ok) {
      console.error('Failed to save workflow message:', response.status)
      return { success: false }
    }

    const data = await response.json()
    return { success: true, session_id: data.session_id }
  } catch (error) {
    console.error('Error saving workflow message to history:', error)
    return { success: false }
  }
}

