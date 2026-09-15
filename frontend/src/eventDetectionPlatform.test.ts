import { describe, expect, it } from 'vitest'

import rootSource from './Root.vue?raw'
import routerSource from './router.ts?raw'
import workspaceSource from './WorkspaceRoute.vue?raw'

describe('event detection platform shell contract', () => {
  it('keeps the legacy event center while adding a dedicated detection route', () => {
    expect(routerSource).toContain("path: '/event-detection'")
    expect(routerSource).toContain("navKey: 'detection'")
    expect(routerSource).toContain("path: '/events'")
  })

  it('adds the dedicated event detection item to the root navigation', () => {
    expect(rootSource).toContain('Aim')
    expect(rootSource).toContain("key: 'detection'")
    expect(rootSource).toContain("label: '事件检测'")
    expect(rootSource).toContain("target: '/event-detection'")
  })

  it('lazy-loads and renders EventDetectionView from the workspace shell', () => {
    expect(workspaceSource).toContain('EventDetectionView')
    expect(workspaceSource).toContain("renderKey === 'detection'")
  })
})
