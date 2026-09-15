import { describe, expect, it } from 'vitest'

import runtimeStoreSource from './stores/runtime.ts?raw'

describe('runtime health store contract', () => {
  it('uses the lightweight realtime REST and websocket contracts', () => {
    expect(runtimeStoreSource).toContain("'/api/health/realtime'")
    expect(runtimeStoreSource).toContain("message.type === 'health.realtime'")
    expect(runtimeStoreSource).not.toContain("'/api/health/summary'")
    expect(runtimeStoreSource).not.toContain("message.type === 'health.snapshot'")
  })
})
