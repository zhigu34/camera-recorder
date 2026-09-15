import { describe, expect, it } from 'vitest'

import viewSource from './EventDetectionView.vue?raw'
import mainSource from './main.ts?raw'
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

  it('implements the approved event detection workspace without fake AI controls', () => {
    expect(viewSource).toContain('事件检测')
    expect(viewSource).toContain('检测摄像头')
    expect(viewSource).toContain('检测区域')
    expect(viewSource).toContain('移动检测')
    expect(viewSource).toContain('未安装 AI Provider')
    expect(viewSource).toContain('保存设置')
    expect(viewSource).toContain('重置')
    expect(viewSource).toContain('MotionZoneEditor')
    expect(viewSource).not.toContain('AI 模型 3')
  })

  it('uses aggregate event detection APIs and imports the dedicated workspace css', () => {
    expect(viewSource).toContain('/event-detection/sources/local.motion')
    expect(viewSource).toContain('/event-detection`')
    expect(viewSource).toContain('/motion-zones')
    expect(viewSource).toContain('preview.mjpeg?stream=auto')
    expect(mainSource).toContain("./styles/event-detection.css")
  })
})
