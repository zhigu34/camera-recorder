export type QueryValue = string | null | undefined | Array<string | null>

export function parsePositiveQueryId(value: QueryValue): number | null {
  const raw = Array.isArray(value) ? value[0] : value
  const parsed = Number(raw || 0)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export function uploadTaskLocation(taskId: number) {
  return {
    path: '/uploads',
    query: { task_id: String(taskId) },
  }
}

export function archiveSettingsLocation() {
  return {
    path: '/settings',
    query: { section: 'archive' },
  }
}
