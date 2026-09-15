import { describe, expect, it } from 'vitest'
import {
  cloneRuntimeDraft,
  countRuntimeChanges,
  createRuntimeDraft,
  normalizeSettingsSection,
  rtspSecondsToUs,
  rtspUsToSeconds,
  serializeRuntimePayload,
  validateRuntimeDraft,
  type SystemSettingsRead,
} from './utils/runtimeSettings'

const loaded: SystemSettingsRead = {
  app_name: 'Camera Recorder',
  segment_duration_seconds: 600,
  remux_concurrency: 2,
  rtsp_timeout_us: 5_000_000,
  auto_start_enabled: true,
  align_segments_to_clock: true,
  storage_warning_percent: 80,
  storage_critical_percent: 90,
  upload_enabled: false,
  upload_concurrency: 2,
  upload_retry_max: 8,
  webdav_url: 'http://openlist:5244/dav',
  webdav_root: '监控录像',
  webdav_username: 'admin',
  webdav_password_set: true,
  local_retention_hours: 48,
  openlist_management_port: 5244,
}

describe('runtime settings model', () => {
  it('normalizes settings deep links including legacy archive', () => {
    expect(normalizeSettingsSection()).toBe('general')
    expect(normalizeSettingsSection('system')).toBe('general')
    expect(normalizeSettingsSection('archive')).toBe('openlist')
    expect(normalizeSettingsSection('alerts')).toBe('alerts')
    expect(normalizeSettingsSection('unknown')).toBe('general')
  })

  it('round-trips RTSP seconds and microseconds', () => {
    expect(rtspUsToSeconds(5_000_000)).toBe(5)
    expect(rtspSecondsToUs(5.5)).toBe(5_500_000)
  })

  it('creates a safe draft without exposing the saved WebDAV password', () => {
    const draft = createRuntimeDraft(loaded)
    expect(draft.rtsp_timeout_seconds).toBe(5)
    expect(draft.webdav_password).toBe('')
    expect(draft.webdav_password_set).toBe(true)
    expect(draft.clear_webdav_password).toBe(false)
  })

  it('counts logical changes and clones drafts independently', () => {
    const saved = createRuntimeDraft(loaded)
    const draft = cloneRuntimeDraft(saved)
    draft.app_name = 'NVR'
    draft.rtsp_timeout_seconds = 6
    expect(countRuntimeChanges(saved, draft)).toBe(2)
    expect(saved.app_name).toBe('Camera Recorder')
  })

  it('serializes the existing API payload and preserves password semantics', () => {
    const draft = createRuntimeDraft(loaded)
    draft.rtsp_timeout_seconds = 6
    expect(serializeRuntimePayload(draft)).toMatchObject({
      rtsp_timeout_us: 6_000_000,
      webdav_password: null,
      clear_webdav_password: false,
    })
    draft.webdav_password = 'new-secret'
    expect(serializeRuntimePayload(draft).webdav_password).toBe('new-secret')
    draft.webdav_password = ''
    draft.clear_webdav_password = true
    expect(serializeRuntimePayload(draft).clear_webdav_password).toBe(true)
  })

  it('blocks invalid storage thresholds before submission', () => {
    const draft = createRuntimeDraft(loaded)
    draft.storage_warning_percent = 90
    draft.storage_critical_percent = 90
    expect(validateRuntimeDraft(draft)).toContain('严重告警阈值')
  })
})
