import { describe, expect, it } from 'vitest'

import timelineSource from './PlaybackTimelineV3.vue?raw'

describe('PlaybackTimelineV3 interaction semantics', () => {
  it('uses one explicit interaction state and keeps pan separate from seeking', () => {
    expect(timelineSource).toContain("type TimelineInteraction = 'idle' | 'pan' | 'playhead-drag' | 'range-start-drag' | 'range-end-drag' | 'range-move'")
    expect(timelineSource).toContain("const interaction = ref<TimelineInteraction>('idle')")
    expect(timelineSource).toContain("interaction.value === 'pan'")
    expect(timelineSource).not.toContain('cursorSeconds.value = viewStart.value + span.value / 2')
  })

  it('renders a dedicated draggable playhead target and hover preview without disabling pointer events', () => {
    expect(timelineSource).toContain('timeline-playhead-hit')
    expect(timelineSource).toContain('@pointerdown.stop="startPlayheadDrag"')
    expect(timelineSource).toContain('@pointermove="handlePointerMove"')
    expect(timelineSource).toContain('@pointerleave="clearHover"')
    expect(timelineSource).toContain('timeline-hover-preview')
    expect(timelineSource).not.toMatch(/\.timeline-playhead-hit[^}]*pointer-events\s*:\s*none/)
  })

  it('renders two range handles and a movable selected band in export range mode', () => {
    expect(timelineSource).toContain('rangeSelectEnabled?: boolean')
    expect(timelineSource).toContain('selectedRange?: TimelineSelectionRange | null')
    expect(timelineSource).toContain("'range-change'")
    expect(timelineSource).toContain("'range-commit'")
    expect(timelineSource).toContain('timeline-selection-band')
    expect(timelineSource).toContain('timeline-range-handle start')
    expect(timelineSource).toContain('timeline-range-handle end')
    expect(timelineSource).toContain('@pointerdown.stop="startRangeMove"')
    expect(timelineSource).toContain("startRangeResize(event, 'start')")
    expect(timelineSource).toContain("startRangeResize(event, 'end')")
  })

  it('does not seek from range gestures and keeps gap clicks as visual cursor intent', () => {
    expect(timelineSource).toContain('if (props.rangeSelectEnabled) return')
    expect(timelineSource).toContain('cursorSeconds.value = target')
    expect(timelineSource).toContain("if (state === 'range-start-drag' || state === 'range-end-drag' || state === 'range-move')")
  })
})
