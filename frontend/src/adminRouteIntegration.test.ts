import { describe, expect, it } from 'vitest'
import uploadSource from './UploadManagementView.vue?raw'
import settingsWorkspaceSource from './SystemSettingsWorkspace.vue?raw'
import settingsSource from './SystemSettingsView.vue?raw'
import workspaceRouteSource from './WorkspaceRoute.vue?raw'

describe('admin route integration', () => {
  it('syncs upload detail selection with task_id and reuses the shared camera store', () => {
    expect(uploadSource).toContain('useRoute')
    expect(uploadSource).toContain('route.query.task_id')
    expect(uploadSource).toContain('uploadTaskLocation(task.id)')
    expect(uploadSource).toContain('useCameraStore')
  })

  it('routes upload settings directly to the archive settings section', () => {
    expect(workspaceRouteSource).toContain("@open-settings=\"go('/settings?section=archive')\"")
    expect(settingsWorkspaceSource).toContain("section === 'archive'")
    expect(settingsWorkspaceSource).toContain("document.getElementById('archive-settings')")
  })

  it('protects unsaved system settings from accidental navigation and unload', () => {
    expect(settingsSource).toContain('onBeforeRouteLeave')
    expect(settingsSource).toContain("window.addEventListener('beforeunload'")
    expect(settingsSource).toContain('settingsDirty')
  })
})
