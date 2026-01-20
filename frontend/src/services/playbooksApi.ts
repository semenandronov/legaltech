/**
 * API сервис для Playbooks
 */
import api from './api'

// Типы
export interface PlaybookRule {
  id: string
  playbook_id: string
  rule_type: 'red_line' | 'fallback' | 'no_go'
  clause_category: string
  rule_name: string
  description?: string
  condition_type: string
  condition_config: Record<string, any>
  extraction_prompt?: string
  validation_prompt?: string
  suggested_clause_template?: string
  fallback_options?: any[]
  priority: number
  severity: 'low' | 'medium' | 'high' | 'critical'
  is_active: boolean
  created_at: string
}

export interface Playbook {
  id: string
  name: string
  display_name: string
  description?: string
  document_type: string
  jurisdiction?: string
  is_system: boolean
  is_public: boolean
  user_id?: string
  usage_count: number
  last_used_at?: string
  version: number
  created_at: string
  updated_at: string
  rules?: PlaybookRule[]
  rules_count?: number
}

export interface RuleCheckResult {
  rule_id: string
  rule_name: string
  rule_type: string
  status: 'passed' | 'failed' | 'warning' | 'skipped' | 'violation' | 'not_found' | 'error'
  clause_found?: boolean
  clause_text?: string
  clause_location?: { start: number; end: number }
  found_text?: string
  location?: { start?: number; end?: number }
  message?: string
  issue_description?: string
  suggestion?: string
  suggested_fix?: string
  confidence: number
  reasoning?: string
}

export interface Redline {
  id?: string
  type?: 'insert' | 'delete' | 'modify' | 'comment' | 'replace' | 'add'
  change_type?: string
  original_text?: string
  suggested_text?: string
  reason?: string
  rule_id?: string
  rule_name?: string
  issue_description?: string
  location?: { start?: number; end?: number }
  severity?: string
  accepted?: boolean
}

export interface PlaybookCheck {
  id: string
  playbook_id?: string
  playbook_name?: string
  document_id: string
  document_name?: string
  case_id?: string
  user_id: string
  overall_status: 'compliant' | 'non_compliant' | 'needs_review' | 'in_progress' | 'failed'
  compliance_score?: number
  total_rules?: number
  red_line_violations: number
  fallback_issues: number
  no_go_violations: number
  passed_rules: number
  results: RuleCheckResult[]
  redlines: Redline[]
  extracted_clauses?: any[]
  error_message?: string
  started_at?: string
  completed_at?: string
  processing_time_seconds?: number
  created_at: string
}

// API методы

// Playbooks CRUD
export const getPlaybooks = async (params?: {
  document_type?: string
  include_system?: boolean
  include_public?: boolean
}): Promise<Playbook[]> => {
  const response = await api.get('/api/playbooks', { params })
  // Ensure we always return an array
  return Array.isArray(response.data) ? response.data : []
}

export const getPlaybook = async (playbookId: string): Promise<Playbook> => {
  const response = await api.get(`/api/playbooks/${playbookId}`)
  return response.data
}

export const createPlaybook = async (data: {
  name: string
  display_name: string
  description?: string
  document_type: string
  jurisdiction?: string
  is_public?: boolean
  rules?: Omit<PlaybookRule, 'id' | 'playbook_id' | 'created_at'>[]
}): Promise<Playbook> => {
  const response = await api.post('/api/playbooks', data)
  return response.data
}

export const updatePlaybook = async (
  playbookId: string,
  data: Partial<Playbook>
): Promise<Playbook> => {
  // Update playbook metadata (without rules)
  const { rules, ...playbookData } = data
  const response = await api.put(`/api/playbooks/${playbookId}`, playbookData)
  return response.data
}

/**
 * Update playbook with full rules synchronization
 * This will add new rules, update existing ones, and delete removed ones
 */
export const updatePlaybookWithRules = async (
  playbookId: string,
  data: Partial<Playbook>
): Promise<Playbook> => {
  // 1. Update playbook metadata
  const { rules: newRules, ...playbookData } = data
  await api.put(`/api/playbooks/${playbookId}`, playbookData)
  
  // 2. Get current playbook with rules
  const currentPlaybook = await getPlaybook(playbookId)
  const currentRules = currentPlaybook.rules || []
  
  // 3. Sync rules
  if (newRules) {
    const currentRuleIds = new Set(currentRules.map(r => r.id))
    const newRuleIds = new Set(newRules.filter(r => !r.id.startsWith('new_')).map(r => r.id))
    
    // Delete removed rules
    for (const rule of currentRules) {
      if (!newRuleIds.has(rule.id)) {
        await deleteRule(playbookId, rule.id)
      }
    }
    
    // Add or update rules
    for (const rule of newRules) {
      if (rule.id.startsWith('new_')) {
        // New rule - add it
        await addRule(playbookId, {
          rule_type: rule.rule_type,
          clause_category: rule.clause_category,
          rule_name: rule.rule_name,
          description: rule.description,
          condition_type: rule.condition_type,
          condition_config: rule.condition_config,
          priority: rule.priority,
          severity: rule.severity,
          is_active: rule.is_active
        })
      } else if (currentRuleIds.has(rule.id)) {
        // Existing rule - update it
        await updateRule(playbookId, rule.id, {
          rule_type: rule.rule_type,
          clause_category: rule.clause_category,
          rule_name: rule.rule_name,
          description: rule.description,
          condition_type: rule.condition_type,
          condition_config: rule.condition_config,
          priority: rule.priority,
          severity: rule.severity,
          is_active: rule.is_active
        })
      }
    }
  }
  
  // 4. Return updated playbook
  return getPlaybook(playbookId)
}

export const deletePlaybook = async (playbookId: string): Promise<void> => {
  await api.delete(`/api/playbooks/${playbookId}`)
}

export const duplicatePlaybook = async (playbookId: string): Promise<Playbook> => {
  const response = await api.post(`/api/playbooks/${playbookId}/duplicate`)
  return response.data
}

// Rules CRUD
export const getRules = async (playbookId: string): Promise<PlaybookRule[]> => {
  const response = await api.get(`/api/playbooks/${playbookId}/rules`)
  return response.data
}

export const addRule = async (
  playbookId: string,
  data: Omit<PlaybookRule, 'id' | 'playbook_id' | 'created_at'>
): Promise<PlaybookRule> => {
  const response = await api.post(`/api/playbooks/${playbookId}/rules`, data)
  return response.data
}

export const updateRule = async (
  playbookId: string,
  ruleId: string,
  data: Partial<PlaybookRule>
): Promise<PlaybookRule> => {
  const response = await api.put(`/api/playbooks/${playbookId}/rules/${ruleId}`, data)
  return response.data
}

export const deleteRule = async (playbookId: string, ruleId: string): Promise<void> => {
  await api.delete(`/api/playbooks/${playbookId}/rules/${ruleId}`)
}

// Response type for checkDocument (abbreviated response from API)
export interface CheckDocumentResponse {
  check_id: string
  playbook_id: string
  document_id: string
  overall_status: string
  compliance_score: number
  red_line_violations: number
  fallback_issues: number
  no_go_violations: number
  passed_rules: number
  results: Array<{
    rule_id: string
    rule_name: string
    rule_type: string
    status: string
    issue_description?: string
    confidence: number
  }>
  redlines_count: number
  processing_time_seconds: number
}

// Checks
export const checkDocument = async (
  playbookId: string,
  documentId: string,
  caseId?: string
): Promise<CheckDocumentResponse> => {
  const response = await api.post(`/api/playbooks/${playbookId}/check`, {
    document_id: documentId,
    case_id: caseId
  })
  return response.data
}

export const getChecks = async (params?: {
  playbook_id?: string
  document_id?: string
  case_id?: string
  status?: string
  limit?: number
  offset?: number
}): Promise<PlaybookCheck[]> => {
  const response = await api.get('/api/playbooks/checks', { params })
  // Ensure we always return an array
  return Array.isArray(response.data) ? response.data : []
}

export const getCheck = async (checkId: string): Promise<PlaybookCheck> => {
  const response = await api.get(`/api/playbooks/checks/${checkId}`)
  return response.data
}

export const getCheckRedlines = async (checkId: string): Promise<{
  document_id: string
  redlines: Redline[]
  original_text: string
  annotated_text: string
}> => {
  const response = await api.get(`/api/playbooks/checks/${checkId}/redlines`)
  return response.data
}

export const applyRedline = async (
  checkId: string,
  redlineId: string,
  accepted: boolean
): Promise<void> => {
  await api.post(`/api/playbooks/checks/${checkId}/redlines/${redlineId}`, { accepted })
}

// Utility functions
export const getStatusColor = (status: string): string => {
  switch (status) {
    case 'compliant':
    case 'passed':
      return '#22c55e'
    case 'non_compliant':
    case 'failed':
      return '#ef4444'
    case 'needs_review':
    case 'warning':
      return '#eab308'
    case 'in_progress':
      return '#6366f1'
    default:
      return '#9ca3af'
  }
}

export const getStatusLabel = (status: string): string => {
  switch (status) {
    case 'compliant':
      return 'Соответствует'
    case 'non_compliant':
      return 'Не соответствует'
    case 'needs_review':
      return 'Требует проверки'
    case 'in_progress':
      return 'В процессе'
    case 'failed':
      return 'Ошибка'
    case 'passed':
      return 'Пройдено'
    case 'warning':
      return 'Предупреждение'
    case 'skipped':
      return 'Пропущено'
    default:
      return status
  }
}

export const getRuleTypeLabel = (type: string): string => {
  switch (type) {
    case 'red_line':
      return 'Обязательное'
    case 'fallback':
      return 'Рекомендуемое'
    case 'no_go':
      return 'Запрещённое'
    default:
      return type
  }
}

export const getSeverityColor = (severity: string): string => {
  switch (severity) {
    case 'critical':
      return '#dc2626'
    case 'high':
      return '#ef4444'
    case 'medium':
      return '#eab308'
    case 'low':
      return '#22c55e'
    default:
      return '#9ca3af'
  }
}

