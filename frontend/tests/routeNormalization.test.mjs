import test from 'node:test'
import assert from 'node:assert/strict'
import { formatRouteNumber, normalizeRouteResult, routeDifference, routeNumber } from '../src/routeNormalization.ts'

const geometry = [[17.4435, 78.3772], [17.4401, 78.3489]]

function responseWithRoute(route, extra = {}) {
  return {
    origin: 'Hitech City',
    destination: 'Gachibowli',
    origin_point: geometry[0],
    destination_point: geometry[1],
    routes: [route],
    data_source: 'OpenStreetMap + OSRM',
    ...extra,
  }
}

test('valid route and step numbers normalize, classify, and format', () => {
  const result = normalizeRouteResult(responseWithRoute({
    route_id: 'route-a',
    distance: 4.25,
    duration: 11.2,
    geometry,
    steps: [{ instruction: 'Turn left', turn_direction: 'left', location: geometry[1], distance: 1.1, duration: 2.5 }],
  }))
  assert.equal(result.routes[0].distance, 4.25)
  assert.equal(result.routes[0].duration, 11.2)
  assert.equal(result.routes[0].is_shortest, true)
  assert.equal(result.routes[0].is_fastest, true)
  assert.equal(result.routes[0].steps[0].distance_km, 1.1)
  assert.equal(result.routes[0].steps[0].duration_minutes, 2.5)
  assert.equal(result.routes[0].steps[0].turn_direction, 'left')
  assert.deepEqual(result.routes[0].steps[0].location, geometry[1])
  assert.equal(formatRouteNumber(result.routes[0].distance, 2), '4.25')
})

test('missing and null route or step numbers become Unavailable without crashing', () => {
  const result = normalizeRouteResult(responseWithRoute({
    geometry,
    steps: [{ instruction: 'Continue', distance_km: null, duration_minutes: undefined }],
  }))
  assert.equal(result.routes[0].distance, null)
  assert.equal(result.routes[0].duration, null)
  assert.equal(result.routes[0].is_shortest, false)
  assert.equal(result.routes[0].is_fastest, false)
  assert.equal(result.routes[0].steps[0].distance_km, null)
  assert.equal(formatRouteNumber(result.routes[0].distance, 2), 'Unavailable')
  assert.equal(formatRouteNumber(result.routes[0].steps[0].duration_minutes, 1), 'Unavailable')
})

test('invalid non-finite, negative, and non-numeric values are unavailable', () => {
  for (const value of [undefined, null, NaN, Infinity, -1, '12.5', {}]) {
    assert.equal(routeNumber(value), null)
    assert.equal(formatRouteNumber(value, 1), 'Unavailable')
  }
  assert.equal(routeDifference(null, 4), null)
  assert.equal(routeDifference(5, null), null)
})

test('one malformed route is omitted without discarding a valid road route', () => {
  const result = normalizeRouteResult({
    ...responseWithRoute({ route_id: 'valid', distance: 5, duration: 10, geometry, steps: [] }),
    routes: [
      { route_id: 'bad', distance: 2, duration: 3, geometry: null, steps: [] },
      { route_id: 'valid', distance: 5, duration: 10, geometry, steps: [] },
    ],
  })
  assert.equal(result.routes.length, 1)
  assert.match(result.alternatives_note, /1 malformed route was omitted/)
})

test('simulated route payloads and responses without real geometry are rejected', () => {
  assert.throws(
    () => normalizeRouteResult(responseWithRoute({ distance: 2, duration: 4, geometry, steps: [] }, { data_source: 'mock_simulation' })),
    /simulated route data/,
  )
  assert.throws(
    () => normalizeRouteResult(responseWithRoute({ distance: 2, duration: 4, steps: [] })),
    /no routes with valid road geometry/,
  )
})
