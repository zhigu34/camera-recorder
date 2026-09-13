export type NormalizedPoint = [number, number]

interface RectLike {
  left: number
  top: number
  width: number
  height: number
}

function clamp01(value: number) {
  return Math.max(0, Math.min(1, value))
}

export function canvasPointToNormalized(
  clientX: number,
  clientY: number,
  rect: RectLike,
): NormalizedPoint {
  if (rect.width <= 0 || rect.height <= 0) return [0, 0]
  return [
    clamp01((clientX - rect.left) / rect.width),
    clamp01((clientY - rect.top) / rect.height),
  ]
}

export function polygonToSvgPoints(points: NormalizedPoint[]) {
  return points.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')
}
