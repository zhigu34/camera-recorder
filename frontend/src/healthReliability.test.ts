import axios from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useHealthReliabilityStore } from './stores/healthReliability'

function report(hours: 24 | 72) {
  return {
    generated_at: `2026-09-15T00:00:00+00:00`,
    hours,
    criteria: {},
    overall: {
      verdict: 'pass',
      monitored_cameras: 1,
      passed_cameras: 1,
      failed_cameras: 0,
      collecting_cameras: 0,
      recorder_availability_rate: 100,
      recording_completeness: 100,
      recording_gap_count: 0,
      missing_recording_seconds: 0,
      unexplained_recording_gaps: 0,
      ffmpeg_failures: 0,
      failure_streaks: 0,
      outage_count: 0,
      total_offline_seconds: 0,
      longest_offline_seconds: 0,
    },
    issues: [],
    cameras: [],
  }
}

describe('health reliability store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('caches 24h and 72h reports independently and force refresh bypasses cache', async () => {
    const get = vi.spyOn(axios, 'get').mockImplementation(async (_url, config) => {
      const params = config?.params as { hours?: number } | undefined
      const hours = Number(params?.hours) as 24 | 72
      return { data: report(hours) }
    })
    const store = useHealthReliabilityStore()

    await store.refresh()
    expect(get).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenLastCalledWith('/api/health/reliability', { params: { hours: 24 } })
    expect(store.report?.hours).toBe(24)

    await store.setWindow(72)
    expect(get).toHaveBeenCalledTimes(2)
    expect(store.report?.hours).toBe(72)

    await store.setWindow(24)
    expect(get).toHaveBeenCalledTimes(2)
    expect(store.report?.hours).toBe(24)

    await store.refresh(true)
    expect(get).toHaveBeenCalledTimes(3)
  })

  it('keeps the last valid report when a refresh fails', async () => {
    const get = vi.spyOn(axios, 'get').mockResolvedValueOnce({ data: report(24) })
    const store = useHealthReliabilityStore()
    await store.refresh()

    get.mockRejectedValueOnce(new Error('network down'))
    await store.refresh(true)

    expect(store.report?.hours).toBe(24)
    expect(store.error).toContain('network down')
    expect(store.loading).toBe(false)
  })
})