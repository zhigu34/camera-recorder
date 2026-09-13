import { describe, expect, it } from 'vitest'

import { canvasPointToNormalized, polygonToSvgPoints } from './utils/motionZones'

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
})
