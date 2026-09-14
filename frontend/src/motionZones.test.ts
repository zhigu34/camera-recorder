import { describe, expect, it } from 'vitest'

import editorSource from './MotionZoneEditor.vue?raw'
import {
  canvasPointToNormalized,
  polygonToSvgPoints,
  replaceNormalizedPoint,
} from './utils/motionZones'

describe('motion zone coordinate helpers', () => {
  it('converts pointer coordinates to normalized coordinates', () => {
    const rect = { left: 100, top: 50, width: 800, height: 450 }
    expect(canvasPointToNormalized(500, 275, rect)).toEqual([0.5, 0.5])
  })

  it('clamps pointer coordinates to the image bounds', () => {
    const rect = { left: 100, top: 50, width: 800, height: 450 }
    expect(canvasPointToNormalized(20, 800, rect)).toEqual([0, 1])
  })

  it('maps normalized polygons into svg percentage coordinates', () => {
    expect(polygonToSvgPoints([[0.1, 0.2], [0.75, 0.8], [1, 0]])).toBe('10,20 75,80 100,0')
  })

  it('moves only the selected anchor', () => {
    const original = [[0.1, 0.2], [0.5, 0.5], [0.9, 0.8]] as [number, number][]
    expect(replaceNormalizedPoint(original, 1, [0.6, 0.7])).toEqual([
      [0.1, 0.2],
      [0.6, 0.7],
      [0.9, 0.8],
    ])
    expect(original[1]).toEqual([0.5, 0.5])
  })

  it('uses pointer capture and stops anchor drags from adding points', () => {
    expect(editorSource).toContain('@pointerdown.stop.prevent="startPointDrag($event, index)"')
    expect(editorSource).toContain('@pointermove="movePointDrag"')
    expect(editorSource).toContain('setPointerCapture')
    expect(editorSource).toContain('releasePointerCapture')
  })
})
