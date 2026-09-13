export function cameraIdFromRouteQuery(value: unknown): number | null {
  const raw = Array.isArray(value) ? value[0] : value
  const parsed = Number(raw ?? 0)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}
