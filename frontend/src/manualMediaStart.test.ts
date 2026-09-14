import { describe, expect, it } from 'vitest'

import previewSource from './PreviewViewV2.vue?raw'
import playerSource from './PlaybackPlayer.vue?raw'
import playbackWorkspaceSource from './PlaybackWorkspace.vue?raw'
import managementSource from './RecordingManagementView.vue?raw'
import recordingsTypesSource from './types/recordings.ts?raw'

describe('manual media start', () => {
  it('keeps live monitoring disconnected until a tile is explicitly started', () => {
    expect(previewSource).toContain('function startSlot(index: number)')
    expect(previewSource).toContain('function toggleSlotPlayback(index: number)')
    expect(previewSource).toContain("state: 'idle'")
    expect(previewSource).toContain('autoFill()')

    const mountedStart = previewSource.indexOf('onMounted(() => {')
    const mountedEnd = previewSource.indexOf('onBeforeUnmount(', mountedStart)
    const mountedBlock = previewSource.slice(mountedStart, mountedEnd)
    expect(mountedBlock).not.toContain('connectSlot(')
  })

  it('stages playback selection without opening a media source on page entry', () => {
    expect(recordingsTypesSource).toContain('select(recording: RecordingItem | null')
    expect(playerSource).toContain('function select(')
    expect(playbackWorkspaceSource).toContain('playerRef.value?.select(recording')
    expect(playbackWorkspaceSource).not.toContain('await openSelection(selected)')
  })

  it('starts a staged playback only after an explicit play or seek action', () => {
    expect(playerSource).toContain('pendingSeekSeconds.value = requested')
    expect(playerSource).toContain('await open(activeRecording.value, { seekSeconds: pendingSeekSeconds.value || 0 })')
    expect(playerSource).toContain('@click="open(activeRecording)"')
  })

  it('selects recording-management deep links without playing them', () => {
    const mountedStart = managementSource.indexOf('onMounted(async () => {')
    const mountedEnd = managementSource.indexOf('onBeforeUnmount(', mountedStart)
    const mountedBlock = managementSource.slice(mountedStart, mountedEnd)
    expect(mountedBlock).toContain('if (target) selectRecording(target)')
    expect(mountedBlock).not.toContain('await play(target)')
  })
})
