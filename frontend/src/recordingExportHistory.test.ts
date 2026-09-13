import { describe, expect, it } from 'vitest'

import drawerSource from './RecordingExportHistoryDrawer.vue?raw'
import workspaceSource from './RecordingsWorkspace.vue?raw'

describe('recording export history', () => {
  it('surfaces export history from the recording management workspace', () => {
    expect(workspaceSource).toContain('导出记录')
    expect(workspaceSource).toContain('<RecordingExportHistoryDrawer')
    expect(workspaceSource).toContain(':camera-id="selectedCameraId"')
  })

  it('loads recent jobs and ready artifacts for the selected camera', () => {
    expect(drawerSource).toContain("axios.get<ExportJob[]>('/api/exports'")
    expect(drawerSource).toContain('camera_id: props.cameraId, limit: 20')
    expect(drawerSource).toContain('`/api/exports/${jobId}/artifacts`')
  })

  it('downloads artifacts through the guarded export download endpoint', () => {
    expect(drawerSource).toContain('`/api/exports/${job.id}/artifacts/${artifact.id}/download`')
    expect(drawerSource).toContain("window.open(url, '_blank', 'noopener,noreferrer')")
  })

  it('returns to playback to create another range export without starting media itself', () => {
    expect(drawerSource).toContain("path: '/recordings/playback'")
    expect(drawerSource).not.toContain('.play()')
    expect(drawerSource).not.toContain('autoplay')
  })
})
