import { describe, expect, it } from 'vitest'
import operationsViewSource from './OperationsView.vue?raw'
import settingsWorkspaceSource from './SystemSettingsWorkspace.vue?raw'
import { normalizeSettingsSection } from './utils/runtimeSettings'

describe('operations settings workspace', () => {
  it('exposes a dedicated operations section through the settings query route', () => {
    expect(normalizeSettingsSection('operations')).toBe('operations')
    expect(settingsWorkspaceSource).toContain("key: 'operations'")
    expect(settingsWorkspaceSource).toContain("activeSection === 'operations'")
    expect(settingsWorkspaceSource).toContain("import OperationsView from './OperationsView.vue'")
    expect(settingsWorkspaceSource).toContain('运维')
  })

  it('shows the bounded log retention policy from the operations API', () => {
    expect(operationsViewSource).toContain("'/api/operations/log-policy'")
    expect(operationsViewSource).toContain('摄像头日志')
    expect(operationsViewSource).toContain('部署日志每次部署重置')
  })
})
