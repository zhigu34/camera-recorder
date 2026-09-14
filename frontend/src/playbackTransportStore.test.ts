import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { usePlaybackTransportStore } from './stores/playbackTransport'

describe('playback transport store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('publishes skip, rate and interval commands in sequence', () => {
    const store = usePlaybackTransportStore()

    store.requestSkip(10)
    expect(store.command).toEqual({ sequence: 1, type: 'skip', value: 10 })

    store.requestRate(2)
    expect(store.command).toEqual({ sequence: 2, type: 'rate', value: 2 })

    store.requestInterval(30)
    expect(store.command).toEqual({ sequence: 3, type: 'interval', value: 30 })
  })
})
