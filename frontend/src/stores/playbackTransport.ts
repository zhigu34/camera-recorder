import { defineStore } from 'pinia'
import { ref } from 'vue'

export type PlaybackTransportCommandType = 'skip' | 'rate' | 'interval'

export interface PlaybackTransportCommand {
  sequence: number
  type: PlaybackTransportCommandType
  value: number
}

export const usePlaybackTransportStore = defineStore('playback-transport', () => {
  const command = ref<PlaybackTransportCommand | null>(null)
  let sequence = 0

  function publish(type: PlaybackTransportCommandType, value: number) {
    sequence += 1
    command.value = { sequence, type, value }
  }

  function requestSkip(value: number) { publish('skip', value) }
  function requestRate(value: number) { publish('rate', value) }
  function requestInterval(value: number) { publish('interval', value) }

  return { command, requestSkip, requestRate, requestInterval }
})
