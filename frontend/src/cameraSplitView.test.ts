import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import cameraSource from './CamerasView.vue?raw'
import workspaceSource from './CamerasWorkspace.vue?raw'
import mainSource from './main.ts?raw'

const splitStylePath = fileURLToPath(new URL('./styles/camera-split-view.css', import.meta.url))
const splitStyleSource = existsSync(splitStylePath) ? readFileSync(splitStylePath, 'utf8') : ''

describe('camera split view', () => {
  it('uses a permanent desktop list/detail workspace instead of the legacy camera drawer', () => {
    expect(cameraSource).toContain('class="camera-split-layout"')
    expect(cameraSource).toContain('class="camera-list-pane"')
    expect(cameraSource).toContain('class="camera-detail-pane"')
    expect(cameraSource).not.toContain('<el-drawer')
  })

  it('keeps camera deep links and selects the first visible camera when no camera id is present', () => {
    expect(cameraSource).toContain('nextQuery.camera_id = String(cameraId)')
    expect(cameraSource).toContain("writeCameraDeepLink(firstCamera.id, 'replace')")
  })

  it('treats disabled devices as a separate filter state', () => {
    expect(cameraSource).toContain("'disabled'")
    expect(cameraSource).toContain('disabled: cameras.value.filter')
    expect(cameraSource).toContain("filter.value === 'disabled'")
  })

  it('provides stable workspace portal targets in the persistent detail pane', () => {
    expect(cameraSource).toContain('class="camera-detail-extension-slot"')
    expect(workspaceSource).toContain('.camera-detail-pane .camera-detail-extension-slot')
  })

  it('loads the split-view refinement and includes a narrow-screen list/detail fallback', () => {
    expect(mainSource).toContain("./styles/camera-split-view.css")
    expect(splitStyleSource).toContain('.camera-split-layout')
    expect(splitStyleSource).toContain('@media (max-width:')
    expect(splitStyleSource).toContain('.camera-detail-back')
  })
})
