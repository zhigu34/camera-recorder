import { describe, expect, it } from 'vitest'
import { cameraIdFromRouteQuery } from './utils/cameraMotionPortal'

describe('cameraIdFromRouteQuery', () => {
  it('returns a positive integer camera id', () => {
    expect(cameraIdFromRouteQuery('42')).toBe(42)
    expect(cameraIdFromRouteQuery(['7', '8'])).toBe(7)
  })

  it('rejects missing, zero, negative, fractional and malformed values', () => {
    expect(cameraIdFromRouteQuery(undefined)).toBeNull()
    expect(cameraIdFromRouteQuery('0')).toBeNull()
    expect(cameraIdFromRouteQuery('-2')).toBeNull()
    expect(cameraIdFromRouteQuery('1.5')).toBeNull()
    expect(cameraIdFromRouteQuery('camera-1')).toBeNull()
  })
})
