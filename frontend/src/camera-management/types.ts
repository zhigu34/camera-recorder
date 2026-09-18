export interface CameraDeletionImpact {
  camera_id: number
  recordings: number
  motion_events: number
  detection_events: number
  health_samples: number
  blocking_events: number
  pending_uploads: number
  can_delete: boolean
}
