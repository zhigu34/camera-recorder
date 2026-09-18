export interface CameraDeletionImpact {
  camera_id: number
  recordings: number
  motion_events: number
  health_samples: number
  blocking_events: number
  pending_uploads: number
  can_delete: boolean
}

export function hasDeletionBlockers(impact: CameraDeletionImpact | null): boolean {
  return Boolean(impact && !impact.can_delete)
}
