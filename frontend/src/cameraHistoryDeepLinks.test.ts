import { describe, expect, it } from 'vitest'

import eventSource from './EventCenterView.vue?raw'
import healthSource from './HealthCenterView.vue?raw'
import uploadSource from './UploadManagementView.vue?raw'

describe('camera history deep links', () => {
  it('uses camera_id to scope activity and system events', () => {
    expect(eventSource).toContain('positiveRouteId(route.query.camera_id)')
    expect(eventSource).toContain("const activityCamera = ref<ActivityCameraFilter>(initialCameraId || 'all')")
    expect(eventSource).toContain("const cameraFilter = ref<CameraFilter>(initialCameraId || 'all')")
    expect(eventSource).toContain('watch(() => route.query.camera_id')
    expect(eventSource).toContain('replaceCameraDeepLink(nextId)')
  })

  it('opens the health drawer for a camera_id deep link once health data exists', () => {
    expect(healthSource).toContain('positiveRouteId(route.query.camera_id)')
    expect(healthSource).toContain('function syncDeepLinkedCamera()')
    expect(healthSource).toContain('drawerOpen.value = true')
    expect(healthSource).toContain("camera_id: String(cameraId)")
    expect(healthSource).toContain('watch(drawerOpen')
  })

  it('scopes upload rows and summary counts to camera_id', () => {
    expect(uploadSource).toContain('const routeCameraId = computed(() => parsePositiveQueryId(route.query.camera_id))')
    expect(uploadSource).toContain('const cameraScopedTasks = computed')
    expect(uploadSource).toContain('const scopedCounts = computed')
    expect(uploadSource).toContain('cameraScopedTasks.length')
  })
})
