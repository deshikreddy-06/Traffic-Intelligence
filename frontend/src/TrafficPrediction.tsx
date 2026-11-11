import { useState } from 'react'
import type { FormEvent } from 'react'
import { Activity, AlertCircle, ArrowDownRight, ArrowUpRight, Clock3, Gauge, Route, Sparkles } from 'lucide-react'
import { LocationAutocomplete, type SelectedLocation } from './LocationAutocomplete'
import { loadGoogleRoutesLibrary } from './GoogleMaps'
import { normalizeRouteResult } from './routeNormalization'

interface Estimate {
  distanceKm: number
  durationMinutes: number
  typicalMinutes: number | null
}

interface PredictionResult {
  live: Estimate
  scheduled: Estimate
  departure: Date
  requestedAt: Date
  liveTitle: string
  liveLabel: string
  forecastLabel: string
  forecastNote: string
}

function localDateTimeValue(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function extractEstimate(routes: google.maps.routes.Route[]): Estimate {
  const route = routes[0]
  if (!route) throw new Error('No drivable route was returned for those locations.')
  if (route.distanceMeters == null || route.durationMillis == null) throw new Error('The traffic service returned an incomplete route estimate.')
  return {
    distanceKm: route.distanceMeters / 1000,
    durationMinutes: route.durationMillis / 60_000,
    typicalMinutes: route.staticDurationMillis == null ? null : route.staticDurationMillis / 60_000,
  }
}

function trafficDescription(estimate: Estimate): string {
  if (estimate.typicalMinutes === null) return 'Traffic comparison unavailable'
  const delay = estimate.durationMinutes - estimate.typicalMinutes
  const ratio = estimate.typicalMinutes > 0 ? delay / estimate.typicalMinutes : 0
  if (ratio < -0.05) return `About ${Math.abs(Math.round(ratio * 100))}% faster than typical`
  if (ratio < 0.05) return 'Near typical traffic (0-5%)'
  const impact = ratio < 0.2 ? 'Moderate traffic impact' : 'Heavy traffic impact'
  return `${impact} (+${Math.round(ratio * 100)}% vs typical)`
}

function formatDuration(minutes: number): string {
  const total = Math.max(0, Math.round(minutes))
  const hours = Math.floor(total / 60)
  const mins = total % 60
  return hours ? `${hours} hr ${mins} min` : `${mins} min`
}

function peakTrafficFactor(departure: Date, distanceKm: number): number {
  const hour = departure.getHours() + departure.getMinutes() / 60
  const weekday = departure.getDay() !== 0 && departure.getDay() !== 6
  let uplift: number
  if (!weekday) {
    // Weekend traffic is usually lighter, with only a modest afternoon/evening bump.
    uplift = hour >= 15 && hour < 22 ? 0.12
      : hour >= 10 && hour < 15 ? 0.06
        : 0.02
  } else {
    // Typical weekday commuter peaks: morning 7-11 AM and evening 3-10 PM.
    uplift = hour >= 15 && hour < 22 ? 0.45
      : hour >= 7 && hour < 11 ? 0.4
        : hour >= 11 && hour < 15 ? 0.1
          : 0.04
  }
  // Scale the urban congestion impact down on long intercity journeys.
  const distanceScale = Math.max(0.5, Math.min(1, 25 / Math.max(distanceKm, 25)))
  return 1 + uplift * distanceScale
}

function EstimateCard({ title, label, estimate, departure, variant }: { title: string; label: string; estimate: Estimate; departure?: Date; variant: 'live' | 'forecast' }) {
  const delay = estimate.typicalMinutes === null ? null : Math.round(estimate.durationMinutes - estimate.typicalMinutes)
  const Icon = variant === 'live' ? Activity : Sparkles
  return <article className={`hti-prediction-card ${variant}`}>
    <div className="hti-prediction-card-heading"><span className="hti-prediction-icon"><Icon size={17} /></span><div><p className="hti-eyebrow">{label}</p><h3>{title}</h3></div></div>
    <div className="hti-prediction-primary"><strong>{formatDuration(estimate.durationMinutes)}</strong><span>estimated drive</span></div>
    <div className="hti-prediction-facts"><span><Route size={15} />{estimate.distanceKm.toFixed(1)} km</span>{departure && <span><Clock3 size={15} />Arrive about {new Date(departure.getTime() + estimate.durationMinutes * 60_000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span>}</div>
    <div className="hti-prediction-traffic"><Gauge size={15} /><span>{trafficDescription(estimate)}</span></div>
    <p className="hti-prediction-baseline">{delay === null ? 'Typical-time comparison unavailable for this route.' : delay > 0 ? `About ${formatDuration(delay)} slower than typical traffic.` : delay < 0 ? `About ${formatDuration(Math.abs(delay))} faster than typical traffic.` : 'Close to the typical traffic estimate.'}</p>
  </article>
}

export function TrafficPrediction() {
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [originPlace, setOriginPlace] = useState<SelectedLocation | null>(null)
  const [destinationPlace, setDestinationPlace] = useState<SelectedLocation | null>(null)
  const [departureText, setDepartureText] = useState(() => localDateTimeValue(new Date(Date.now() + 30 * 60_000)))
  const [result, setResult] = useState<PredictionResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const predict = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setResult(null)
    const departure = new Date(departureText)
    if (!origin.trim() || !destination.trim()) { setError('Enter both a starting point and a destination.'); return }
    if (!departureText || Number.isNaN(departure.getTime())) { setError('Choose a valid departure date and time.'); return }
    if (departure.getTime() < Date.now() - 60_000) { setError('Choose a departure time that is now or in the future.'); return }

    setLoading(true)
    const requestedAt = new Date()
    const routeOrigin: string | google.maps.LatLngLiteral = originPlace ? { lat: originPlace.latitude, lng: originPlace.longitude } : origin.trim()
    const routeDestination: string | google.maps.LatLngLiteral = destinationPlace ? { lat: destinationPlace.latitude, lng: destinationPlace.longitude } : destination.trim()
    try {
      const routeRequest: Record<string, string | number> = {
        origin: originPlace?.formattedAddress || origin.trim(),
        destination: destinationPlace?.formattedAddress || destination.trim(),
      }
      if (originPlace) {
        routeRequest.origin_lat = originPlace.latitude
        routeRequest.origin_lon = originPlace.longitude
      }
      if (destinationPlace) {
        routeRequest.destination_lat = destinationPlace.latitude
        routeRequest.destination_lon = destinationPlace.longitude
      }
      const routeResponse = await fetch('/api/routes/compare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(routeRequest),
      })
      const routePayload = await routeResponse.json()
      if (!routeResponse.ok) throw new Error(typeof routePayload.detail === 'string' ? routePayload.detail : 'The route service could not estimate this trip.')
      const routeData = normalizeRouteResult(routePayload)
      const fastestRoute = routeData.routes.find(route => route.is_fastest) || routeData.routes[0]
      if (fastestRoute.distance === null || fastestRoute.duration === null) throw new Error('The route service returned an incomplete estimate.')
      const usesLiveTraffic = routeData.data_source.toLowerCase().includes('traffic-aware')
      const liveEstimate: Estimate = {
        distanceKm: fastestRoute.distance,
        durationMinutes: fastestRoute.duration,
        typicalMinutes: fastestRoute.static_duration,
      }
      const isNearNow = departure.getTime() <= Date.now() + 3 * 60_000
      let scheduled = liveEstimate
      let forecastLabel = 'CURRENT CONDITIONS'
      let forecastNote = 'Your selected time is near now, so the current route estimate is used.'
      if (!isNearNow) {
        try {
          const { Route: GoogleRoute } = await loadGoogleRoutesLibrary()
          const scheduledResponse = await GoogleRoute.computeRoutes({
            origin: routeOrigin,
            destination: routeDestination,
            travelMode: 'DRIVING',
            routingPreference: 'TRAFFIC_AWARE_OPTIMAL',
            trafficModel: 'bestguess',
            departureTime: departure,
            fields: ['distanceMeters', 'durationMillis', 'staticDurationMillis'],
            region: 'IN',
            language: 'en-IN',
          })
          scheduled = extractEstimate(scheduledResponse.routes || [])
          forecastLabel = 'TRAFFIC-AWARE FORECAST'
          forecastNote = 'Best-guess forecast using traffic information available for the selected departure time.'
        } catch {
          const typical = liveEstimate.typicalMinutes ?? liveEstimate.durationMinutes
          const factor = peakTrafficFactor(departure, liveEstimate.distanceKm)
          scheduled = {
            distanceKm: liveEstimate.distanceKm,
            durationMinutes: typical * factor,
            typicalMinutes: typical,
          }
          forecastLabel = 'TIME-OF-DAY PATTERN ESTIMATE'
          forecastNote = `Scheduled traffic routing is unavailable. The weekday/weekend time profile adds about ${Math.round((factor - 1) * 100)}% to this trip's typical ${formatDuration(typical)} road time.`
        }
      }
      setResult({
        live: liveEstimate,
        scheduled,
        departure,
        requestedAt,
        liveTitle: usesLiveTraffic ? 'Right now' : 'Current road estimate',
        liveLabel: usesLiveTraffic ? 'LIVE TRAFFIC-AWARE ROUTE' : 'ROAD-NETWORK REFERENCE',
        forecastLabel,
        forecastNote,
      })
    } catch {
      setError('Could not estimate this trip. Check both locations and the backend connection, then try again.')
    } finally {
      setLoading(false)
    }
  }

  const difference = result ? Math.round(result.scheduled.durationMinutes - result.live.durationMinutes) : null

  return <div className="hti-prediction-page">
    <section className="hti-panel hti-prediction-intro">
      <div className="hti-prediction-title"><span className="hti-prediction-title-icon"><Sparkles size={20} /></span><div><p className="hti-eyebrow">SMART TRAFFIC INTELLIGENCE</p><h2>Traffic prediction</h2><p className="hti-muted">Compare current road conditions with a traffic-aware estimate for your planned departure.</p></div></div>
      <form className="hti-prediction-form" onSubmit={event => void predict(event)}>
        <LocationAutocomplete label="STARTING POINT" value={origin} onChange={value => { setOrigin(value); setOriginPlace(null) }} onSelect={place => { setOriginPlace(place); if (place) setOrigin(place.formattedAddress) }} placeholder="Search a city, landmark, or address" />
        <LocationAutocomplete label="DESTINATION" value={destination} onChange={value => { setDestination(value); setDestinationPlace(null) }} onSelect={place => { setDestinationPlace(place); if (place) setDestination(place.formattedAddress) }} placeholder="Search a city, landmark, or address" />
        <label className="hti-prediction-time"><span>DEPARTURE DATE & TIME</span><input type="datetime-local" value={departureText} min={localDateTimeValue(new Date()).slice(0, 16)} onChange={event => setDepartureText(event.target.value)} /></label>
        <button className="hti-primary-button hti-prediction-submit" type="submit" disabled={loading}><Sparkles size={16} />{loading ? 'Calculating…' : 'Predict traffic'}</button>
      </form>
      <p className="hti-prediction-hint">When available, the forecast uses traffic-aware routing. If that service is unavailable, the page shows a clearly labeled time-of-day estimate instead.</p>
      {error && <p className="hti-prediction-error" role="alert"><AlertCircle size={16} />{error}</p>}
    </section>

    {loading && <section className="hti-panel hti-prediction-loading" role="status"><span className="hti-loading-pulse" /><div><strong>Analyzing the trip</strong><p>Comparing live traffic with your departure-time forecast…</p></div></section>}
    {result && <>
      <div className="hti-prediction-result-heading"><div><p className="hti-eyebrow">ROUTE OUTLOOK</p><h2>{originPlace?.name || origin} <span>to</span> {destinationPlace?.name || destination}</h2></div><span className="hti-prediction-distance">Trip estimate comparison</span></div>
      <section className="hti-prediction-results" aria-label="Live and predicted route estimates">
        <EstimateCard title={result.liveTitle} label={result.liveLabel} estimate={result.live} variant="live" />
        <EstimateCard title={result.departure.toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })} label={result.forecastLabel} estimate={result.scheduled} departure={result.departure} variant="forecast" />
      </section>
      <section className="hti-panel hti-prediction-comparison">
        <div className="hti-prediction-compare-icon">{difference !== null && difference >= 0 ? <ArrowUpRight size={18} /> : <ArrowDownRight size={18} />}</div>
        <div><p className="hti-eyebrow">{result.liveLabel.includes('LIVE') ? 'PREDICTED CHANGE FROM LIVE TRAFFIC' : 'SCHEDULED CHANGE FROM ROUTE REFERENCE'}</p><strong>{difference === null || difference === 0 ? 'About the same travel time' : `${formatDuration(Math.abs(difference))} ${difference > 0 ? 'longer' : 'shorter'}`}</strong><span>{result.liveLabel.includes('LIVE') ? 'Scheduled estimate compared with current live traffic' : 'Time-of-day estimate compared with the current road-network reference'}</span></div>
        <small>Calculated {result.requestedAt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</small>
      </section>
      <p className="hti-prediction-disclaimer"><AlertCircle size={15} />{result.forecastNote} Estimates are not guarantees and can change with road incidents and weather.</p>
    </>}
    {!result && !loading && <section className="hti-panel hti-prediction-empty"><span><Activity size={22} /></span><strong>Plan ahead with a traffic forecast</strong><p>Enter two locations and a departure time to compare current traffic with expected conditions at that time.</p></section>}
  </div>
}
