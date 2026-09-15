import axios from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import mainSource from './main.ts?raw'
import {
  applicationTimeZone,
  configureApplicationTimeZone,
} from './utils/dateTime'
import { bootstrapApplicationTimeZone } from './utils/applicationBootstrap'

vi.mock('axios', () => ({
  default: {
    get: vi.fn(),
  },
}))

const mockedGet = vi.mocked(axios.get)

beforeEach(() => {
  mockedGet.mockReset()
  configureApplicationTimeZone('Asia/Shanghai')
})

describe('frontend timezone bootstrap', () => {
  it('uses the runtime timezone returned by backend', async () => {
    mockedGet.mockResolvedValue({ data: { timezone: 'Asia/Shanghai' } })

    await expect(bootstrapApplicationTimeZone()).resolves.toBe('Asia/Shanghai')
    expect(applicationTimeZone()).toBe('Asia/Shanghai')
    expect(mockedGet).toHaveBeenCalledWith(
      '/api/settings/runtime',
      expect.objectContaining({ timeout: expect.any(Number) }),
    )
    const options = mockedGet.mock.calls[0]?.[1] as { timeout?: number } | undefined
    expect(options?.timeout).toBeGreaterThan(0)
  })

  it('falls back to Shanghai when runtime settings cannot be loaded', async () => {
    configureApplicationTimeZone('UTC')
    mockedGet.mockRejectedValue(new Error('offline'))

    await expect(bootstrapApplicationTimeZone()).resolves.toBe('Asia/Shanghai')
    expect(applicationTimeZone()).toBe('Asia/Shanghai')
  })

  it('mounts Vue only after timezone bootstrap resolves', () => {
    const bootstrapIndex = mainSource.indexOf('await bootstrapApplicationTimeZone()')
    const mountIndex = mainSource.indexOf("app.mount('#app')")
    expect(bootstrapIndex).toBeGreaterThanOrEqual(0)
    expect(mountIndex).toBeGreaterThan(bootstrapIndex)
  })
})
