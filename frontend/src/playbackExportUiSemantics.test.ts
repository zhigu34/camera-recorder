import { describe, expect, it } from 'vitest'

import workspaceSource from './PlaybackWorkspace.vue?raw'

describe('playback export workflow semantics', () => {
  it('enters range selection without starting media', () => {
    expect(workspaceSource).toContain('function startExportRangeSelection()')
    expect(workspaceSource).toContain('initialExportRange(activeWallSeconds.value, recordings.value)')
    const start = workspaceSource.indexOf('function startExportRangeSelection()')
    const end = workspaceSource.indexOf('\n}', start)
    const body = workspaceSource.slice(start, end)
    expect(body).not.toContain('playerRef.value?.open')
    expect(body).not.toContain('playerRef.value?.play')
  })

  it('wires the committed wall-clock range to the timeline without using it as seek intent', () => {
    expect(workspaceSource).toContain(':range-select-enabled="rangeSelectEnabled"')
    expect(workspaceSource).toContain(':selected-range="exportRange"')
    expect(workspaceSource).toContain('@range-change="handleExportRangeChange"')
    expect(workspaceSource).toContain('@range-commit="handleExportRangeCommit"')
  })

  it('polls only pending or processing export jobs and stops on terminal state', () => {
    expect(workspaceSource).toContain("job.status !== 'pending' && job.status !== 'processing'")
    expect(workspaceSource).toContain('stopExportPolling()')
    expect(workspaceSource).toContain("if (job.status === 'ready')")
    expect(workspaceSource).toContain('fetchExportArtifacts(job.id)')
  })

  it('resets stale export selection on camera/date changes and stops timers on unmount', () => {
    expect(workspaceSource).toContain('resetExportContext()')
    expect(workspaceSource).toContain('onBeforeUnmount(() => stopExportPolling())')
  })

  it('uses server-owned artifact download URLs', () => {
    expect(workspaceSource).toContain('/api/exports/${activeExportJob.value.id}/artifacts/${artifact.id}/download')
    expect(workspaceSource).not.toContain('artifact.path')
  })
})
