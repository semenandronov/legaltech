import { getApiUrl } from './api'

export interface CaseWorkflow {
  id: string
  case_id: string
  title: string
  description?: string | null
  user_task: string
  default_file_ids: string[]
  created_at?: string
  updated_at?: string
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('access_token')
  return {
    'Content-Type': 'application/json',
    'X-Access-Token': token || '',
  }
}

export async function listCaseWorkflows(caseId: string): Promise<CaseWorkflow[]> {
  const res = await fetch(getApiUrl(`/api/cases/${caseId}/workflows`), {
    headers: authHeaders(),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `listCaseWorkflows failed: ${res.status}`)
  }
  return res.json()
}

export async function createCaseWorkflow(
  caseId: string,
  body: {
    title: string
    user_task: string
    description?: string
    default_file_ids?: string[]
  },
): Promise<CaseWorkflow> {
  const res = await fetch(getApiUrl(`/api/cases/${caseId}/workflows`), {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `createCaseWorkflow failed: ${res.status}`)
  }
  return res.json()
}

export async function deleteCaseWorkflow(caseId: string, workflowId: string): Promise<void> {
  const res = await fetch(getApiUrl(`/api/cases/${caseId}/workflows/${workflowId}`), {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok && res.status !== 204) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `deleteCaseWorkflow failed: ${res.status}`)
  }
}
