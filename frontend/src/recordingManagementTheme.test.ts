import { describe, expect, it } from 'vitest'
import mainSource from './main.ts?raw'
import managementSource from './RecordingManagementView.vue?raw'

describe('Recording management player theme', () => {
  it('loads the recording management player theme refinement layer', () => {
    expect(mainSource).toContain("import './styles/recording-management-theme.css'")
  })

  it('keeps the real recording video canvas black and fitted while the surrounding frame follows theme', () => {
    expect(managementSource).toContain('aspect-ratio:16/9')
    expect(managementSource).toContain('object-fit:contain;background:#000')
    expect(managementSource).not.toContain('object-fit:cover')
    expect(managementSource).not.toContain('filter:blur')
  })
})
