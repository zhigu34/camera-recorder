import { describe, expect, it } from 'vitest'

import cameraSource from './CamerasView.vue?raw'
import detailsSource from './CameraOnvifDetails.vue?raw'

describe('ONVIF device capability details', () => {
  it('renders ONVIF details only for the ONVIF adapter', () => {
    expect(cameraSource).toContain("import CameraOnvifDetails from './CameraOnvifDetails.vue'")
    expect(cameraSource).toContain("selectedCamera.connection?.adapter === 'onvif'")
    expect(cameraSource).toContain('<CameraOnvifDetails')
  })

  it('shows persisted device identity and profile roles without credentials', () => {
    expect(detailsSource).toContain('固件')
    expect(detailsSource).toContain('序列号')
    expect(detailsSource).toContain('Hardware ID')
    expect(detailsSource).toContain('Device UUID')
    expect(detailsSource).toContain('recording_profile_token')
    expect(detailsSource).toContain('preview_profile_token')
    expect(detailsSource).toContain('detection_profile_token')
    expect(detailsSource).not.toContain('password')
  })

  it('summarizes ONVIF Media, Events and PTZ service availability', () => {
    expect(detailsSource).toContain('Media')
    expect(detailsSource).toContain('Events')
    expect(detailsSource).toContain('PTZ')
    expect(detailsSource).toContain('media_xaddr')
    expect(detailsSource).toContain('events_xaddr')
    expect(detailsSource).toContain('ptz_xaddr')
  })

  it('renders discovered media profiles with codec, resolution and fps', () => {
    expect(detailsSource).toContain('config.profiles')
    expect(detailsSource).toContain('profile.encoding')
    expect(detailsSource).toContain('profile.width')
    expect(detailsSource).toContain('profile.height')
    expect(detailsSource).toContain('profile.fps')
  })
})
