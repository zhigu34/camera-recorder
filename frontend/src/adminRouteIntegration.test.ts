import { describe, expect, it } from 'vitest'
import uploadSource from './UploadManagementView.vue?raw'
import settingsWorkspaceSource from './SystemSettingsWorkspace.vue?raw'
import workspaceRouteSource from './WorkspaceRoute.vue?raw'

describe('admin route integration', () => {
  it('syncs upload detail selection with task_id and reuses the shared camera store', () => {
    expect(uploadSource).toContain('useRoute')
    expect(uploadSource).toContain('route.query.task_id')
    expect(uploadSource).toContain('uploadTaskLocation(task.id)')
    expect(uploadSource).toContain('useCameraStore')
  })

  it('keeps legacy upload settings links compatible with the OpenList section', () => {
    expect(workspaceRouteSource).toContain("@open-settings=\"go('/settings?section=archive')\"")
    expect(settingsWorkspaceSource).toContain('normalizeSettingsSection')
    expect(settingsWorkspaceSource).toContain("'openlist'")
  })

  it('protects unsaved runtime settings from accidental navigation and unload', () => {
    expect(settingsWorkspaceSource).toContain('onBeforeRouteLeave')
    expect(settingsWorkspaceSource).toContain("window.addEventListener('beforeunload'")
    expect(settingsWorkspaceSource).toContain('dirtyCount')
  })
})
