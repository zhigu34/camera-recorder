import { describe, expect, it } from 'vitest'
import settingsWorkspaceSource from './SystemSettingsWorkspace.vue?raw'

describe('operations settings workspace', () => {
  it('exposes a dedicated operations section through the settings query route', () => {
    expect(settingsWorkspaceSource).toContain("'operations'")
    expect(settingsWorkspaceSource).toContain("section === 'operations'")
    expect(settingsWorkspaceSource).toContain("{ section: 'operations' }")
    expect(settingsWorkspaceSource).toContain("import OperationsView from './OperationsView.vue'")
    expect(settingsWorkspaceSource).toContain('运维工具')
  })
})
