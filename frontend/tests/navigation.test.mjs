import test from 'node:test'
import assert from 'node:assert/strict'
import { createOffRouteTracker, currentStepIndex, formatDistance, progressOnRoute, startLocationWatch } from '../src/navigation.ts'

const route = [[17.4, 78.4], [17.405, 78.4], [17.41, 78.4]]

test('GPS updates are matched to route geometry and progress', () => {
  const progress = progressOnRoute([17.405, 78.4001], route)
  assert.ok(progress)
  assert.ok(progress.distanceFromRouteMeters < 15)
  assert.ok(progress.fraction > 0.45 && progress.fraction < 0.55)
})

test('turn instructions progress after cumulative OSRM step distance', () => {
  const steps = [{ distance_km: 0.4, instruction: 'Continue' }, { distance_km: 0.6, instruction: 'Turn left' }, { distance_km: 0.2, instruction: 'Arrive' }]
  assert.equal(currentStepIndex(100, steps), 0)
  assert.equal(currentStepIndex(450, steps), 1)
  assert.equal(currentStepIndex(1100, steps), 2)
})

test('off-route warning/reroute requires repeated inaccurate-safe fixes and resets on route return', () => {
  const tracker = createOffRouteTracker(70, 2)
  assert.equal(tracker.observe(90), false)
  assert.equal(tracker.observe(120), true)
  tracker.reset()
  assert.equal(tracker.observe(25), false)
  assert.equal(tracker.observe(25), false)
})

test('watcher cleanup clears the GPS watch once; denial callback remains available', () => {
  let success
  let failure
  const cleared = []
  const fakeGeolocation = {
    watchPosition(onSuccess, onError) { success = onSuccess; failure = onError; return 42 },
    clearWatch(id) { cleared.push(id) },
  }
  let receivedError
  const stop = startLocationWatch(fakeGeolocation, () => {}, error => { receivedError = error })
  failure({ code: 1, message: 'denied' })
  assert.equal(receivedError.code, 1)
  stop()
  stop()
  assert.deepEqual(cleared, [42])
  assert.equal(typeof success, 'function')
})

test('distance display uses metres for short remaining distances and km for long routes', () => {
  assert.equal(formatDistance(240), '240 m')
  assert.equal(formatDistance(1250), '1.3 km')
  assert.equal(formatDistance(Number.NaN), 'Unavailable')
})
