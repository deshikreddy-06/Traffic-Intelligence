import type { RoutePoint } from './routeNormalization'

export interface RouteProgress {
  distanceFromRouteMeters: number
  travelledMeters: number
  fraction: number
}

export interface NavigationStep {
  distance_km: number | null
  instruction: string
}

const EARTH_RADIUS_METERS = 6_371_000

export function haversineMeters(a: RoutePoint, b: RoutePoint): number {
  const radians = (degrees: number) => degrees * Math.PI / 180
  const lat1 = radians(a[0])
  const lat2 = radians(b[0])
  const deltaLat = lat2 - lat1
  const deltaLon = radians(b[1] - a[1])
  const term = Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2
  return EARTH_RADIUS_METERS * 2 * Math.atan2(Math.sqrt(term), Math.sqrt(Math.max(0, 1 - term)))
}

export function routeSegmentLengthMeters(start: RoutePoint, end: RoutePoint): number {
  return haversineMeters(start, end)
}

/** Find the closest point on the route and distance already travelled along its geometry. */
export function progressOnRoute(point: RoutePoint, geometry: RoutePoint[]): RouteProgress | null {
  if (geometry.length < 2) return null
  let travelledBeforeSegment = 0
  let bestDistance = Number.POSITIVE_INFINITY
  let bestTravelled = 0

  for (let index = 0; index < geometry.length - 1; index += 1) {
    const start = geometry[index]
    const end = geometry[index + 1]
    const segmentLength = haversineMeters(start, end)
    const latitudeScale = Math.cos(point[0] * Math.PI / 180) * Math.PI / 180 * EARTH_RADIUS_METERS
    const longitudeScale = latitudeScale
    const startX = (start[1] - point[1]) * longitudeScale
    const startY = (start[0] - point[0]) * EARTH_RADIUS_METERS * Math.PI / 180
    const endX = (end[1] - point[1]) * longitudeScale
    const endY = (end[0] - point[0]) * EARTH_RADIUS_METERS * Math.PI / 180
    const segmentX = endX - startX
    const segmentY = endY - startY
    const denominator = segmentX * segmentX + segmentY * segmentY
    const fraction = denominator === 0 ? 0 : Math.max(0, Math.min(1, -(startX * segmentX + startY * segmentY) / denominator))
    const distance = Math.hypot(startX + fraction * segmentX, startY + fraction * segmentY)
    if (distance < bestDistance) {
      bestDistance = distance
      bestTravelled = travelledBeforeSegment + segmentLength * fraction
    }
    travelledBeforeSegment += segmentLength
  }

  return {
    distanceFromRouteMeters: bestDistance,
    travelledMeters: bestTravelled,
    fraction: travelledBeforeSegment > 0 ? Math.min(1, bestTravelled / travelledBeforeSegment) : 0,
  }
}

export function currentStepIndex(progressMeters: number, steps: NavigationStep[]): number {
  if (steps.length <= 1) return 0
  let cumulativeMeters = 0
  for (let index = 0; index < steps.length - 1; index += 1) {
    cumulativeMeters += (steps[index].distance_km ?? 0) * 1000
    if (progressMeters < cumulativeMeters) return index
  }
  return steps.length - 1
}

export function isOffRoute(distanceMeters: number, thresholdMeters = 70): boolean {
  return Number.isFinite(distanceMeters) && distanceMeters > thresholdMeters
}

export function createOffRouteTracker(thresholdMeters = 70, requiredFixes = 2) {
  let consecutiveFixes = 0
  return {
    observe(distanceMeters: number): boolean {
      consecutiveFixes = isOffRoute(distanceMeters, thresholdMeters) ? consecutiveFixes + 1 : 0
      return consecutiveFixes >= requiredFixes
    },
    reset(): void { consecutiveFixes = 0 },
  }
}

export function formatDistance(meters: number): string {
  if (!Number.isFinite(meters) || meters < 0) return 'Unavailable'
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters / 10) * 10} m`
}

export interface GeolocationLike {
  watchPosition: (success: PositionCallback, error?: PositionErrorCallback | null, options?: PositionOptions) => number
  clearWatch: (watchId: number) => void
}

/** Owns one browser watch and guarantees idempotent cleanup. */
export function startLocationWatch(
  geolocation: GeolocationLike,
  onPosition: PositionCallback,
  onError: PositionErrorCallback,
): () => void {
  const watchId = geolocation.watchPosition(onPosition, onError, { enableHighAccuracy: true, maximumAge: 1000, timeout: 15000 })
  let stopped = false
  return () => {
    if (stopped) return
    stopped = true
    geolocation.clearWatch(watchId)
  }
}
