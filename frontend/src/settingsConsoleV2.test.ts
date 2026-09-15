import { describe, expect, it } from 'vitest'
import settingsWorkspaceSource from './SystemSettingsWorkspace.vue?raw'
import settingsSource from './SystemSettingsView.vue?raw'

describe('settings console v2', () => {
  it('uses a persistent settings console navigation with seven first-level sections', () => {
    expect(settingsWorkspaceSource).toContain('settings-console-nav')
    for (const label of ['常规', '录像', '存储', 'OpenList', '通知与告警', '运维', '高级']) {
      expect(settingsWorkspaceSource).toContain(label)
    }
  })

  it('maps legacy archive deep links through a section normalizer', () => {
    expect(settingsWorkspaceSource).toContain('normalizeSettingsSection')
    expect(settingsWorkspaceSource).toContain("'openlist'")
    expect(settingsWorkspaceSource).not.toContain("document.getElementById('archive-settings')")
  })

  it('moves OpenList out of the legacy all-in-one system settings view', () => {
    expect(settingsSource).not.toContain('OpenList / WebDAV 归档')
    expect(settingsSource).not.toContain('webdav_url')
    expect(settingsWorkspaceSource).toContain('SettingsOpenListPanel')
  })

  it('owns runtime dirty state and navigation protection at workspace level', () => {
    expect(settingsWorkspaceSource).toContain('dirtyCount')
    expect(settingsWorkspaceSource).toContain('onBeforeRouteLeave')
    expect(settingsWorkspaceSource).toContain("window.addEventListener('beforeunload'")
    expect(settingsWorkspaceSource).toContain('保存更改')
    expect(settingsWorkspaceSource).toContain('放弃修改')
  })

  it('uses a seconds-based RTSP editor while preserving the API boundary conversion', () => {
    expect(settingsWorkspaceSource).toContain('rtsp_timeout_seconds')
    expect(settingsWorkspaceSource).toContain('serializeRuntimePayload')
  })
})
