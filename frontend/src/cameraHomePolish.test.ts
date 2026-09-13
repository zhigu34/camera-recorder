import { describe, expect, it } from 'vitest'
import mainSource from './main.ts?raw'
import cameraSource from './CamerasView.vue?raw'

describe('Camera home polish', () => {
  it('loads the dedicated camera home visual refinement layer', () => {
    expect(mainSource).toContain("import './styles/camera-home-polish.css'")
  })

  it('keeps camera preview manual while the home page is visually refined', () => {
    expect(cameraSource).toContain('const previewPlaying = ref(false)')
    expect(cameraSource).toContain('function startPreview()')
    expect(cameraSource).toContain('if (openingDifferentCamera) preparePreview(camera)')
    expect(cameraSource).toContain('previewPlaying.value = false')
  })
})
