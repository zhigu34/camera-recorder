import { describe, expect, it } from 'vitest'

import { scopeLabel } from './camera-discovery/presentation'

describe('camera discovery presentation', () => {
  it('decodes common ONVIF scope labels', () => {
    expect(scopeLabel('onvif://www.onvif.org/name/Front%20Door')).toBe('名称：Front Door')
    expect(scopeLabel('onvif://www.onvif.org/location/Garage')).toBe('位置：Garage')
    expect(scopeLabel('onvif://www.onvif.org/hardware/IPC-123')).toBe('硬件：IPC-123')
  })

  it('keeps unknown scopes visible', () => {
    expect(scopeLabel('onvif://vendor.example/custom/value')).toBe('onvif://vendor.example/custom/value')
  })
})
