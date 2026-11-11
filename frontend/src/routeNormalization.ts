export type RoutePoint = [number, number]

export interface NormalizedRouteStep {
  instruction: string
  road_name: string | null
  turn_direction: string | null
  location: RoutePoint | null
  distance_km: number | null
  duration_minutes: number | null
}

export interface NormalizedRouteOption {
  route_id: string
  route_number: number
  route_type: string
  distance: number | null
  duration: number | null
  static_duration: number | null
  is_shortest: boolean
  is_fastest: boolean
  geometry: RoutePoint[]
  steps: NormalizedRouteStep[]
}

export interface NormalizedRouteResult {
  origin: string
  destination: string
  origin_point: RoutePoint
  destination_point: RoutePoint
  routes: NormalizedRouteOption[]
  route_count: number
  alternatives_available: boolean
  alternatives_note: string
  shortest_fastest_same: boolean
  data_source: string
  traffic_note: string
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

export function routeNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

export function formatRouteNumber(value: unknown, digits: number): string {
  const number = routeNumber(value)
  return number === null ? 'Unavailable' : number.toFixed(digits)
}

function normalizePoint(value: unknown): RoutePoint | null {
  if (!Array.isArray(value) || value.length < 2) return null
  const latitude = routeNumber(value[0])
  const longitude = routeNumber(value[1])
  if (latitude === null || longitude === null || latitude > 90 || longitude > 180) return null
  return [latitude, longitude]
}

function normalizeGeometry(value: unknown): RoutePoint[] | null {
  if (!Array.isArray(value) || value.length < 2) return null
  const points = value.map(normalizePoint)
  return points.every((point): point is RoutePoint => point !== null) ? points : null
}

function normalizeStep(value: unknown): NormalizedRouteStep {
  const step = record(value) ?? {}
  return {
    instruction: typeof step.instruction === 'string' && step.instruction.trim() ? step.instruction : 'Instruction unavailable',
    road_name: typeof step.road_name === 'string' && step.road_name.trim() ? step.road_name : null,
    turn_direction: typeof step.turn_direction === 'string' ? step.turn_direction : null,
    location: normalizePoint(step.location),
    // The current OSRM API supplies both canonical _km/_minutes values and
    // legacy distance/duration values, in kilometres and minutes respectively.
    distance_km: routeNumber(step.distance_km ?? step.distance),
    duration_minutes: routeNumber(step.duration_minutes ?? step.duration),
  }
}

export function normalizeRouteResult(value: unknown): NormalizedRouteResult {
  const response = record(value)
  if (!response || !Array.isArray(response.routes)) {
    throw new Error('Routing service returned an invalid response. Please retry.')
  }
  const dataSource = typeof response.data_source === 'string' ? response.data_source : ''
  if (/mock|simulat|fabricat/i.test(dataSource)) {
    throw new Error('The running routing backend returned simulated route data. Restart the routing backend before planning routes.')
  }

  let discarded = 0
  const routes = response.routes.flatMap((item, index) => {
    const route = record(item)
    const geometry = normalizeGeometry(route?.geometry)
    if (!route || !geometry) {
      discarded += 1
      return []
    }
    const distance = routeNumber(route.distance_km ?? route.distance)
    const duration = routeNumber(route.duration_minutes ?? route.duration)
    const rawSteps = Array.isArray(route.steps) ? route.steps : []
    return [{
      route_id: typeof route.route_id === 'string' && route.route_id ? route.route_id : `route-${index + 1}`,
      route_number: routeNumber(route.route_number) ?? index + 1,
      route_type: typeof route.route_type === 'string' ? route.route_type : 'alternative',
      distance,
      duration,
      static_duration: routeNumber(route.static_duration),
      is_shortest: false as boolean,
      is_fastest: false as boolean,
      geometry,
      steps: rawSteps.map(normalizeStep),
    } satisfies NormalizedRouteOption]
  })
  if (routes.length === 0) {
    throw new Error('Routing service returned no routes with valid road geometry. No route was displayed.')
  }

  const shortestCandidates = routes.map((route, index) => ({ route, index })).filter(item => item.route.distance !== null)
  const fastestCandidates = routes.map((route, index) => ({ route, index })).filter(item => item.route.duration !== null)
  const shortest = shortestCandidates.sort((a, b) => a.route.distance! - b.route.distance!)[0]
  const fastest = fastestCandidates.sort((a, b) => a.route.duration! - b.route.duration!)[0]
  if (shortest) routes[shortest.index].is_shortest = true
  if (fastest) routes[fastest.index].is_fastest = true
  routes.forEach(route => {
    if (route.is_shortest && route.is_fastest) route.route_type = 'shortest and fastest'
    else if (route.is_shortest) route.route_type = 'shortest'
    else if (route.is_fastest) route.route_type = 'fastest estimated'
  })

  const originPoint = normalizePoint(response.origin_point) ?? routes[0].geometry[0]
  const destinationPoint = normalizePoint(response.destination_point) ?? routes[0].geometry[routes[0].geometry.length - 1]
  const baseNote = typeof response.alternatives_note === 'string'
    ? response.alternatives_note
    : routes.length > 1 ? `${routes.length} distinct road routes returned by OSRM.` : 'Only one distinct road route was returned; alternatives are unavailable for this trip.'
  return {
    origin: typeof response.origin === 'string' ? response.origin : 'Starting point',
    destination: typeof response.destination === 'string' ? response.destination : 'Destination',
    origin_point: originPoint,
    destination_point: destinationPoint,
    routes,
    route_count: routes.length,
    alternatives_available: routes.length > 1,
    alternatives_note: discarded ? `${baseNote} ${discarded} malformed route${discarded === 1 ? ' was' : 's were'} omitted.` : baseNote,
    shortest_fastest_same: Boolean(shortest && fastest && shortest.index === fastest.index),
    data_source: dataSource || 'OpenStreetMap + OSRM',
    traffic_note: typeof response.traffic_note === 'string' ? response.traffic_note : 'Route durations are estimates and do not represent live traffic.',
  }
}

export function routeDifference(value: number | null, baseline: number | null): number | null {
  return value === null || baseline === null ? null : Math.max(0, value - baseline)
}
