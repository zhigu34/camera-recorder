export type SettingsSection =
  | 'general'
  | 'recording'
  | 'storage'
  | 'openlist'
  | 'alerts'
  | 'operations'
  | 'advanced'

export interface SystemSettingsRead {
  app_name: string
  segment_duration_seconds: number
  remux_concurrency: number
  rtsp_timeout_us: number
  auto_start_enabled: boolean
  align_segments_to_clock: boolean
  storage_warning_percent: number
  storage_critical_percent: number
  upload_enabled: boolean
  upload_concurrency: number
  upload_retry_max: number
  webdav_url: string
  webdav_root: string
  webdav_username: string
  webdav_password_set: boolean
  local_retention_hours: number
  openlist_management_port: number
}

export interface RuntimeSettingsDraft {
  app_name: string
  segment_duration_seconds: number
  remux_concurrency: number
  rtsp_timeout_seconds: number
  auto_start_enabled: boolean
  align_segments_to_clock: boolean
  storage_warning_percent: number
  storage_critical_percent: number
  upload_enabled: boolean
  upload_concurrency: number
  upload_retry_max: number
  webdav_url: string
  webdav_root: string
  webdav_username: string
  webdav_password: string
  webdav_password_set: boolean
  clear_webdav_password: boolean
  local_retention_hours: number
  openlist_management_port: number
}

export interface SystemSettingsPayload {
  app_name: string
  segment_duration_seconds: number
  remux_concurrency: number
  rtsp_timeout_us: number
  auto_start_enabled: boolean
  align_segments_to_clock: boolean
  storage_warning_percent: number
  storage_critical_percent: number
  upload_enabled: boolean
  upload_concurrency: number
  upload_retry_max: number
  webdav_url: string
  webdav_root: string
  webdav_username: string
  webdav_password: string | null
  clear_webdav_password: boolean
  local_retention_hours: number
}

const SECTIONS = new Set<SettingsSection>([
  'general', 'recording', 'storage', 'openlist', 'alerts', 'operations', 'advanced',
])

const EDITABLE_FIELDS: Array<keyof RuntimeSettingsDraft> = [
  'app_name', 'segment_duration_seconds', 'remux_concurrency', 'rtsp_timeout_seconds',
  'auto_start_enabled', 'align_segments_to_clock', 'storage_warning_percent',
  'storage_critical_percent', 'upload_enabled', 'upload_concurrency', 'upload_retry_max',
  'webdav_url', 'webdav_root', 'webdav_username', 'webdav_password',
  'clear_webdav_password', 'local_retention_hours',
]

export function normalizeSettingsSection(raw?: string | null): SettingsSection {
  if (!raw || raw === 'system') return 'general'
  if (raw === 'archive') return 'openlist'
  return SECTIONS.has(raw as SettingsSection) ? raw as SettingsSection : 'general'
}

export function isRuntimeSettingsSection(section: SettingsSection) {
  return section === 'general' || section === 'recording' || section === 'storage' || section === 'openlist'
}

export function rtspUsToSeconds(value: number) { return value / 1_000_000 }
export function rtspSecondsToUs(value: number) { return Math.round(value * 1_000_000) }

export function createRuntimeDraft(data: SystemSettingsRead): RuntimeSettingsDraft {
  return {
    app_name: data.app_name,
    segment_duration_seconds: data.segment_duration_seconds,
    remux_concurrency: data.remux_concurrency,
    rtsp_timeout_seconds: rtspUsToSeconds(data.rtsp_timeout_us),
    auto_start_enabled: data.auto_start_enabled,
    align_segments_to_clock: data.align_segments_to_clock,
    storage_warning_percent: data.storage_warning_percent,
    storage_critical_percent: data.storage_critical_percent,
    upload_enabled: data.upload_enabled,
    upload_concurrency: data.upload_concurrency,
    upload_retry_max: data.upload_retry_max,
    webdav_url: data.webdav_url,
    webdav_root: data.webdav_root,
    webdav_username: data.webdav_username,
    webdav_password: '',
    webdav_password_set: data.webdav_password_set,
    clear_webdav_password: false,
    local_retention_hours: data.local_retention_hours,
    openlist_management_port: data.openlist_management_port || 5244,
  }
}

export function cloneRuntimeDraft(draft: RuntimeSettingsDraft): RuntimeSettingsDraft { return { ...draft } }

export function serializeRuntimePayload(draft: RuntimeSettingsDraft): SystemSettingsPayload {
  return {
    app_name: draft.app_name,
    segment_duration_seconds: draft.segment_duration_seconds,
    remux_concurrency: draft.remux_concurrency,
    rtsp_timeout_us: rtspSecondsToUs(draft.rtsp_timeout_seconds),
    auto_start_enabled: draft.auto_start_enabled,
    align_segments_to_clock: draft.align_segments_to_clock,
    storage_warning_percent: draft.storage_warning_percent,
    storage_critical_percent: draft.storage_critical_percent,
    upload_enabled: draft.upload_enabled,
    upload_concurrency: draft.upload_concurrency,
    upload_retry_max: draft.upload_retry_max,
    webdav_url: draft.webdav_url,
    webdav_root: draft.webdav_root,
    webdav_username: draft.webdav_username,
    webdav_password: draft.webdav_password || null,
    clear_webdav_password: draft.clear_webdav_password,
    local_retention_hours: draft.local_retention_hours,
  }
}

export function countRuntimeChanges(saved: RuntimeSettingsDraft, draft: RuntimeSettingsDraft) {
  return EDITABLE_FIELDS.reduce((count, field) => count + (Object.is(saved[field], draft[field]) ? 0 : 1), 0)
}

export function validateRuntimeDraft(draft: RuntimeSettingsDraft): string | null {
  if (!draft.app_name.trim()) return '系统名称不能为空'
  if (draft.storage_critical_percent <= draft.storage_warning_percent) return '磁盘严重告警阈值必须大于普通告警阈值'
  if (draft.rtsp_timeout_seconds < 0.5 || draft.rtsp_timeout_seconds > 120) return 'RTSP 超时必须在 0.5 到 120 秒之间'
  return null
}
