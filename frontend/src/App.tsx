import { useEffect, useRef, useState } from 'react'
import { Route, Navigation, Clock, MapPin, LocateFixed, AlertCircle, Play, Square, Volume2, VolumeX, RefreshCw, Crosshair, Database, ArrowLeftRight, MapPinned, Activity, Search, X, Maximize2, Minimize2, Plus, Minus, Settings, Menu, TrendingUp } from 'lucide-react'
import { formatRouteNumber, normalizeRouteResult, routeDifference, type NormalizedRouteResult, type RoutePoint } from './routeNormalization'
import { createOffRouteTracker, currentStepIndex, formatDistance, progressOnRoute, routeSegmentLengthMeters, startLocationWatch } from './navigation'
import { GoogleMapsCanvas, loadGoogleRoutesLibrary } from './GoogleMaps'
import { LocationAutocomplete, type SelectedLocation } from './LocationAutocomplete'
import { TrafficPrediction } from './TrafficPrediction'

type Point = RoutePoint
type RouteResult = NormalizedRouteResult

interface TrafficSource {
  source_name: string
  observation_count: number
  source_url: string | null
  collection_period: string | null
  license: string | null
  data_type: string | null
  city_coverage: string | null
  imported_at: string | null
  notes: string | null
}

interface TrafficStats {
  observation_count: number
  covered_area_count: number
  date_range: { start: string | null; end: string | null }
  average_recorded_speed_kmh: number | null
  average_recorded_vehicle_count: number | null
  data_status: string
  message: string | null
  sources: TrafficSource[]
}

interface GpsStats {
  sample_count: number
  date_range: { start: string | null; end: string | null }
  average_individual_gps_speed_kmh: number | null
  message: string
}

interface TrafficObservation {
  observation_id: string
  timestamp: string | null
  road_name: string | null
  average_speed_kmh: number | null
  vehicle_count: number | null
  congestion_level: string | null
  data_source: string
  data_status: string | null
  road_segment: { segment_id: string; name: string; start: Point; end: Point } | null
}

interface AnalyticsAreaSummary { area: string; avg_travel_time: number | null; avg_speed: number | null; sample_count: number; data_status: string; message: string | null }
interface HourlyAnalytics { area: string; sample_count: number; data_status: string; hourly_data: Record<string, { avg_travel_time: number | null; avg_speed: number | null; sample_count: number } | null> }

const ROUTE_COLORS = ['#64748b', '#7c3aed', '#d97706', '#0891b2']
const GPS_CONSENT_VERSION = 'gps-foreground-consent-v1'
const PRIMARY_NAV_ITEMS = [
  { id: 'routes', label: 'Route planner', icon: Route },
  { id: 'predictions', label: 'Traffic prediction', icon: TrendingUp },
  { id: 'settings', label: 'Settings', icon: Settings },
] as const

function formatDurationMinutes(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'Unavailable'
  const totalMinutes = Math.max(0, Math.round(value))
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return hours ? `${hours} hr ${minutes} min` : `${minutes} min`
}

function formatEstimatedArrival(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return 'Arrival time unavailable'
  const arrival = new Date(Date.now() + value * 60_000)
  return `Estimated arrival ${arrival.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
}

function turnIconRotation(instruction: string): number {
  const text = instruction.toLowerCase()
  if (text.includes('u-turn') || text.includes('uturn') || text.includes('roundabout')) return 180
  if (text.includes('left')) return -45
  if (text.includes('right')) return 45
  return 0
}

function googlePinIcon(letter: string, color: string): google.maps.Icon {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="44" height="54" viewBox="0 0 44 54"><path d="M22 2C10.4 2 2 10.6 2 21.6c0 14.2 20 30.4 20 30.4s20-16.2 20-30.4C42 10.6 33.6 2 22 2z" fill="${color}" stroke="#fff" stroke-width="3"/><circle cx="22" cy="21" r="12" fill="#fff"/><text x="22" y="26" text-anchor="middle" font-family="Arial,sans-serif" font-size="14" font-weight="700" fill="${color}">${letter}</text></svg>`
  return { url: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`, scaledSize: new google.maps.Size(40, 49), anchor: new google.maps.Point(20, 47) }
}

function GpsContribution() {
  const [consent, setConsent] = useState(false)
  const [active, setActive] = useState(false)
  const [sessionForDeletion, setSessionForDeletion] = useState<string | null>(() => localStorage.getItem('hti-gps-session-to-delete'))
  const [message, setMessage] = useState(sessionForDeletion ? 'A saved GPS session exists. Stop or delete it before starting another collection.' : 'GPS collection is off.')
  const [lastSpeed, setLastSpeed] = useState<number | null>(null)
  const [gpsStats, setGpsStats] = useState<GpsStats | null>(null)
  const [error, setError] = useState('')
  const [summaryError, setSummaryError] = useState('')
  const watchId = useRef<number | null>(null)
  const sessionId = useRef<string | null>(null)
  const sessionToken = useRef<string | null>(null)
  const activeRef = useRef(false)
  const lastSentAt = useRef(0)
  const inflight = useRef(Promise.resolve())

  const refreshStats = () => fetch('/api/traffic/gps-observations/stats', { method: 'GET' })
    .then(async response => {
      if (!response.ok) throw new Error(`GPS sample summary API returned HTTP ${response.status}. Restart the project backend and confirm /api/traffic/gps-observations/stats is available.`)
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('GPS sample summary endpoint returned a non-JSON response. Check the frontend /api proxy and backend version.')
      const data = await response.json() as GpsStats
      if (!Number.isInteger(data.sample_count) || data.sample_count < 0 || !('average_individual_gps_speed_kmh' in data)) throw new Error('GPS sample summary endpoint returned an unexpected response schema.')
      setGpsStats(data)
      setSummaryError('')
    })
    .catch(failure => setSummaryError(failure instanceof TypeError
      ? 'Could not reach the GPS sample summary API. Check that the backend is running and the frontend /api proxy points to it.'
      : failure instanceof Error ? failure.message : 'GPS sample summary API is unavailable.'))

  const stop = async (reason = 'Collection stopped.') => {
    activeRef.current = false
    setActive(false)
    if (watchId.current !== null && navigator.geolocation) navigator.geolocation.clearWatch(watchId.current)
    watchId.current = null
    const id = sessionId.current
    const token = sessionToken.current
    sessionId.current = null
    sessionToken.current = null
    if (id) {
      try { await fetch(`/api/traffic/gps-sessions/${id}/stop`, { method: 'POST', headers: token ? { Authorization: `Bearer ${token}` } : {}, keepalive: true }) } catch { /* Local collection is already stopped. */ }
    }
    setMessage(reason)
    void refreshStats()
  }

  useEffect(() => {
    void refreshStats()
    const onVisibility = () => { if (document.visibilityState !== 'visible' && activeRef.current) void stop('Collection stopped because this page is no longer visible.') }
    const onPageHide = () => { if (activeRef.current) void stop('Collection stopped because this page is being closed or navigated away from.') }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', onPageHide)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', onPageHide)
      if (activeRef.current) void stop('Collection stopped when leaving this screen.')
    }
  }, [])

  const start = async () => {
    setError('')
    if (!consent) { setError('Review and accept the consent before starting GPS collection.'); return }
    if (!navigator.geolocation) { setError('This browser does not support GPS location.'); return }
    if (!window.isSecureContext && location.hostname !== 'localhost') { setError('Browser GPS requires HTTPS (or localhost).'); return }
    const id = crypto.randomUUID()
    try {
      const response = await fetch(`/api/traffic/gps-sessions/${id}/start`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ consent_confirmed: true, consent_version: GPS_CONSENT_VERSION }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || 'Could not start GPS collection.')
      if (typeof body.session_token !== 'string') throw new Error('GPS session did not return its access token.')
      sessionId.current = id
      sessionToken.current = body.session_token
      setSessionForDeletion(id)
      localStorage.setItem('hti-gps-session-to-delete', id)
      localStorage.setItem('hti-gps-session-token', body.session_token)
      activeRef.current = true
      setActive(true)
      setMessage('Collecting foreground GPS fixes. Move along a road to produce segment speed samples.')
      watchId.current = navigator.geolocation.watchPosition(position => {
        if (!activeRef.current || document.visibilityState !== 'visible') return
        const now = Date.now()
        if (now - lastSentAt.current < 5000) return
        lastSentAt.current = now
        const timestamp = new Date(position.timestamp).toISOString()
        const reading = {
          observation_id: crypto.randomUUID(), timestamp,
          latitude: position.coords.latitude, longitude: position.coords.longitude,
          accuracy_meters: position.coords.accuracy,
        }
        inflight.current = inflight.current.then(async () => {
          if (!activeRef.current || sessionId.current !== id) return
          const result = await fetch(`/api/traffic/gps-sessions/${id}/readings`, {
            method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionToken.current}` }, body: JSON.stringify(reading),
          })
          const data = await result.json()
          if (!result.ok) throw new Error(data.detail || 'GPS reading was rejected.')
          if (data.average_speed_kmh != null) setLastSpeed(data.average_speed_kmh)
          setMessage(data.message)
          if (data.stored) void refreshStats()
        }).catch(failure => { if (activeRef.current) setError(failure instanceof Error ? failure.message : 'GPS reading could not be submitted.') })
      }, failure => {
        setError(failure.code === 1 ? 'Location permission was denied. Collection has stopped.' : 'GPS position is unavailable or timed out. Collection has stopped.')
        void stop('Collection stopped after a GPS error.')
      }, { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not start GPS collection.')
    }
  }

  const deleteSession = async () => {
    const id = sessionForDeletion
    const token = localStorage.getItem('hti-gps-session-token')
    if (!id || !token) { setError('This browser no longer has the session access token, so its samples cannot be deleted here.'); return }
    await stop('Collection stopped.')
    try {
      const response = await fetch(`/api/traffic/gps-sessions/${id}/observations`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not delete this session.')
      localStorage.removeItem('hti-gps-session-to-delete')
      localStorage.removeItem('hti-gps-session-token')
      setSessionForDeletion(null)
      setMessage(`${data.deleted_samples} stored samples deleted.`)
      void refreshStats()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not delete this session.') }
  }

  const stopSavedSession = async () => {
    const id = sessionForDeletion
    const token = localStorage.getItem('hti-gps-session-token')
    if (!id || !token) { setError('This browser no longer has the session access token.'); return }
    setError('')
    try {
      const response = await fetch(`/api/traffic/gps-sessions/${id}/stop`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not stop the saved GPS session.')
      setMessage('Saved GPS session stopped. You can now delete its samples.')
      void refreshStats()
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not stop the saved GPS session.') }
  }

  return <section className="hti-panel hti-gps-contribution">
    <h2 className="font-bold text-xl">Opt-in GPS speed contribution</h2>
    <p className="text-sm text-slate-600 mt-2">This optional foreground-only collector derives approximate speed from consecutive accurate GPS fixes. A sample represents one device's segment movement; it is not a road-wide speed, vehicle count, or total traffic measurement.</p>
    <div className="rounded-lg bg-amber-50 text-amber-900 p-4 text-sm mt-4">
      <p className="font-semibold">What is collected</p>
      <p className="mt-1">Participation is optional. With your consent, accepted timestamps, coordinates, approximate segment speeds, accuracy, interval, and quality/source labels are stored for research and traffic analysis. Each sample is an individual journey observation, not a verified road-wide traffic measurement or vehicle count. Press Stop now at any time, then choose Delete session and samples. If a page closes before the stop request completes, Stop saved session is available when you return. A random access token is kept in this browser's local storage so you can stop or delete the session later; it is sent only in an authorization header, never in the URL or shown in error messages.</p>
    </div>
    <label className="flex items-start gap-3 mt-4 text-sm"><input type="checkbox" checked={consent} disabled={active} onChange={event => setConsent(event.target.checked)} className="mt-1" /><span>I explicitly consent to this foreground GPS collection and storage for this session.</span></label>
    <div className="flex flex-wrap gap-2 mt-4">
      {!active ? <button onClick={() => void start()} disabled={!consent || !!sessionForDeletion} className="rounded-lg bg-cyan-700 px-4 py-2 text-white font-semibold disabled:opacity-40">Start collection</button> : <button onClick={() => void stop()} className="rounded-lg bg-rose-700 px-4 py-2 text-white font-semibold">Stop now</button>}
      {sessionForDeletion && !active && <>
        <button onClick={() => void stopSavedSession()} className="rounded-lg border border-amber-700 px-4 py-2 text-amber-900">Stop saved session</button>
        <button onClick={() => void deleteSession()} className="rounded-lg border border-rose-700 px-4 py-2 text-rose-800">Delete session and samples</button>
      </>}
    </div>
    <p className="text-sm text-slate-700 mt-3" role="status">{message}</p>
    {lastSpeed != null && <p className="text-sm mt-2">Last accepted individual GPS segment speed: <strong>{formatRouteNumber(lastSpeed, 1)} km/h</strong></p>}
    {error && <p className="text-sm text-rose-800 mt-3" role="alert">{error}</p>}
    {summaryError && <p className="text-sm text-amber-800 mt-3" role="alert">{summaryError}</p>}
    <div className="grid sm:grid-cols-2 gap-3 mt-5">
      <div className="rounded-lg bg-slate-50 p-4"><p className="text-xs text-slate-500">INDIVIDUAL GPS SPEED SAMPLES</p><p className="text-2xl font-bold mt-1">{gpsStats?.sample_count.toLocaleString() ?? '—'}</p></div>
      <div className="rounded-lg bg-slate-50 p-4"><p className="text-xs text-slate-500">AVERAGE OF CONTRIBUTED GPS SEGMENTS</p><p className="text-2xl font-bold mt-1">{gpsStats?.sample_count === 0 ? 'No samples yet' : gpsStats?.average_individual_gps_speed_kmh == null ? 'Unavailable' : `${formatRouteNumber(gpsStats.average_individual_gps_speed_kmh, 1)} km/h`}</p></div>
    </div>
    {gpsStats && <p className="text-xs text-slate-500 mt-3">{gpsStats.message} {gpsStats.date_range.start && `Date range: ${new Date(gpsStats.date_range.start).toLocaleString()} – ${new Date(gpsStats.date_range.end || gpsStats.date_range.start).toLocaleString()}`}</p>}
  </section>
}

function congestionColor(level: string | null): string {
  switch ((level || '').trim().toLowerCase()) {
    case 'low': case 'free': return '#16a34a'
    case 'moderate': case 'medium': return '#f59e0b'
    case 'heavy': case 'high': return '#dc2626'
    case 'severe': return '#7f1d1d'
    default: return '#64748b'
  }
}

function visibleTrafficColor(level: string | null): string | null {
  const normalized = (level || '').trim().toLowerCase()
  if (['moderate', 'medium'].includes(normalized)) return '#f59e0b'
  if (['heavy', 'high'].includes(normalized)) return '#dc2626'
  if (normalized === 'severe') return '#7f1d1d'
  return null
}

function MapZoomControls({ map }: { map: google.maps.Map | null }) {
  return <div className="hti-google-zoom-controls" aria-label="Map zoom controls">
    <button type="button" onClick={() => map?.setZoom((map?.getZoom() || 12) + 1)} disabled={!map} aria-label="Zoom in"><Plus size={19} /></button>
    <button type="button" onClick={() => map?.setZoom((map?.getZoom() || 12) - 1)} disabled={!map} aria-label="Zoom out"><Minus size={19} /></button>
  </div>
}

function TrafficMap({ observations, className = 'h-[480px]', enabled = true }: { observations: TrafficObservation[]; className?: string; enabled?: boolean }) {
  const [map, setMap] = useState<google.maps.Map | null>(null)
  const segments = new Map<string, TrafficObservation>()
    observations.filter(row => ['actual', 'historical'].includes((row.data_status || '').toLowerCase()) && row.road_segment && visibleTrafficColor(row.congestion_level))
    .forEach(row => {
      const id = row.road_segment!.segment_id
      const prior = segments.get(id)
      if (!prior || (row.timestamp || '') > (prior.timestamp || '')) segments.set(id, row)
    })

  useEffect(() => {
    if (!map) return
    const lines: google.maps.Polyline[] = []
    const infoWindows: google.maps.InfoWindow[] = []
    if (enabled) [...segments.values()].forEach(row => {
      const segment = row.road_segment!
      const line = new google.maps.Polyline({
        map,
        path: [
          { lat: segment.start[0], lng: segment.start[1] },
          { lat: segment.end[0], lng: segment.end[1] },
        ],
        strokeColor: visibleTrafficColor(row.congestion_level)!,
        strokeOpacity: 0.92,
        strokeWeight: 7,
        zIndex: 10,
      })
      const content = document.createElement('div')
      content.textContent = `${segment.name} ? Recorded ${row.congestion_level || 'unclassified'} ? ${row.data_source} ? ${row.timestamp ? new Date(row.timestamp).toLocaleString() : 'time unavailable'}`
      const infoWindow = new google.maps.InfoWindow({ content })
      line.addListener('click', (event: google.maps.PolyMouseEvent) => {
        if (!event.latLng) return
        infoWindow.setPosition(event.latLng)
        infoWindow.open({ map })
      })
      lines.push(line)
      infoWindows.push(infoWindow)
    })
    return () => {
      lines.forEach(line => line.setMap(null))
      infoWindows.forEach(infoWindow => infoWindow.close())
    }
  }, [map, enabled, observations])

  return <div className={`${className} relative rounded-xl overflow-hidden border border-slate-700`}>
    <GoogleMapsCanvas onMapReady={setMap} className="absolute inset-0" />
    <MapZoomControls map={map} />
  </div>
}

function HourlySpeedChart({ data }: { data: Array<{ hour: string; speed?: number; samples: number }> }) {
  const width = 760
  const height = 240
  const left = 44
  const right = 12
  const top = 14
  const bottom = 32
  const values = data.map(row => row.speed).filter((value): value is number => value !== undefined && Number.isFinite(value))
  const maximum = Math.max(1, ...values)
  const usableWidth = width - left - right
  const usableHeight = height - top - bottom
  let path = ''
  let segmentOpen = false
  data.forEach((row, index) => {
    if (row.speed === undefined || !Number.isFinite(row.speed)) { segmentOpen = false; return }
    const x = left + index / Math.max(data.length - 1, 1) * usableWidth
    const y = top + (1 - row.speed / maximum) * usableHeight
    path += `${segmentOpen ? 'L' : 'M'} ${x.toFixed(1)} ${y.toFixed(1)} `
    segmentOpen = true
  })
  return <svg viewBox={`0 0 ${width} ${height}`} className="hti-hourly-chart" role="img" aria-label="Thirty day average recorded speed by hour">
    {[0, .5, 1].map(ratio => { const y = top + ratio * usableHeight; return <g key={ratio}><line x1={left} x2={width - right} y1={y} y2={y} stroke="#2b3b50" strokeDasharray="4 5" /><text x={left - 8} y={y + 4} textAnchor="end" fill="#8292a9" fontSize="10">{Math.round(maximum * (1 - ratio))}</text></g> })}
    <path d={path} fill="none" stroke="#22c5e5" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    {data.filter((_, index) => index % 4 === 0).map(row => { const index = data.indexOf(row); const x = left + index / Math.max(data.length - 1, 1) * usableWidth; return <text key={row.hour} x={x} y={height - 8} textAnchor="middle" fill="#8292a9" fontSize="10">{row.hour}</text> })}
    {data.map((row, index) => row.speed === undefined ? null : <circle key={row.hour} cx={left + index / Math.max(data.length - 1, 1) * usableWidth} cy={top + (1 - row.speed / maximum) * usableHeight} r="3.5" fill="#22c5e5"><title>{row.hour}: {row.speed} km/h, {row.samples} samples</title></circle>)}
  </svg>
}

export default function App() {
  const [tab, setTab] = useState('routes')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [origin, setOrigin] = useState('Hitech City, Hyderabad')
  const [destination, setDestination] = useState('Kempegowda International Airport, Bengaluru')
  const [originPlace, setOriginPlace] = useState<SelectedLocation | null>(null)
  const [destinationPlace, setDestinationPlace] = useState<SelectedLocation | null>(null)
  const [gpsLoading, setGpsLoading] = useState(false)
  const [result, setResult] = useState<RouteResult | null>(null)
  const [selected, setSelected] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [trafficStats, setTrafficStats] = useState<TrafficStats | null>(null)
  const [statsError, setStatsError] = useState('')
  const [navigationActive, setNavigationActive] = useState(false)
  const [navigationStarting, setNavigationStarting] = useState(false)
  const [navigationPosition, setNavigationPosition] = useState<Point | null>(null)
  const [navigationError, setNavigationError] = useState('')
  const [offRoute, setOffRoute] = useState(false)
  const [autoReroute, setAutoReroute] = useState(false)
  const [rerouting, setRerouting] = useState(false)
  const [voiceEnabled, setVoiceEnabled] = useState(false)
  const [trafficEnabled, setTrafficEnabled] = useState(true)
  const [trafficObservations, setTrafficObservations] = useState<TrafficObservation[]>([])
  const [trafficObservationTotal, setTrafficObservationTotal] = useState(0)
  const [trafficLoading, setTrafficLoading] = useState(false)
  const [trafficError, setTrafficError] = useState('')
  const [recenterSignal, setRecenterSignal] = useState(0)
  const [routeGpsPoint, setRouteGpsPoint] = useState<Point | null>(null)
  const [mapFullscreen, setMapFullscreen] = useState(false)
  const [routeMap, setRouteMap] = useState<google.maps.Map | null>(null)
  const [routeMapError, setRouteMapError] = useState('')
  const [routeTrafficStatus, setRouteTrafficStatus] = useState('')
  const [healthState, setHealthState] = useState<'checking' | 'online' | 'offline'>('checking')
  const [supportedAreaCount, setSupportedAreaCount] = useState<number | null>(null)
  const [trafficAreaFilter, setTrafficAreaFilter] = useState('')
  const [trafficAreaSearch, setTrafficAreaSearch] = useState('')
  const [analyticsAreas, setAnalyticsAreas] = useState<AnalyticsAreaSummary[]>([])
  const [analyticsArea, setAnalyticsArea] = useState('Hitech City')
  const [hourlyAnalytics, setHourlyAnalytics] = useState<HourlyAnalytics | null>(null)
  const [analyticsError, setAnalyticsError] = useState('')
  const autoRerouteRef = useRef(autoReroute)
  autoRerouteRef.current = autoReroute
  const originEditVersion = useRef(0)
  const navigationCleanup = useRef<(() => void) | null>(null)
  const navigationStopRef = useRef<() => void>(() => {})
  const offRouteTracker = useRef(createOffRouteTracker())
  const lastAnnouncedStep = useRef('')
  const autoReroutePending = useRef(false)
  const navigationDestination = useRef('')
  const navigationBoundaryValidated = useRef(false)
  const navigationBoundaryCheckPending = useRef(false)
  const reroutingRef = useRef(false)

  const stopNavigation = () => {
    navigationCleanup.current?.()
    navigationCleanup.current = null
    setNavigationActive(false)
    setNavigationStarting(false)
    setNavigationPosition(null)
    setOffRoute(false)
    offRouteTracker.current.reset()
    autoReroutePending.current = false
    navigationBoundaryValidated.current = false
    navigationBoundaryCheckPending.current = false
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
  }
  navigationStopRef.current = stopNavigation

  useEffect(() => {
    let cancelled = false
    fetch('/api/health').then(response => { if (!response.ok) throw new Error(); return response.json() })
      .then(() => { if (!cancelled) setHealthState('online') })
      .catch(() => { if (!cancelled) setHealthState('offline') })
    fetch('/api/areas').then(response => { if (!response.ok) throw new Error(); return response.json() })
      .then(areas => { if (!cancelled && Array.isArray(areas)) setSupportedAreaCount(areas.length) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const stopWhenHidden = () => {
      if (document.visibilityState !== 'visible') navigationStopRef.current()
    }
    const stopOnPageHide = () => navigationStopRef.current()
    document.addEventListener('visibilitychange', stopWhenHidden)
    window.addEventListener('pagehide', stopOnPageHide)
    return () => {
      document.removeEventListener('visibilitychange', stopWhenHidden)
      window.removeEventListener('pagehide', stopOnPageHide)
      navigationStopRef.current()
    }
  }, [])

  useEffect(() => {
    if (!trafficEnabled && tab !== 'monitoring' && tab !== 'dashboard') return
    let cancelled = false
    setTrafficLoading(true)
    setTrafficError('')
    const params = new URLSearchParams({ limit: '1000' })
    if (trafficAreaFilter.trim()) params.set('area', trafficAreaFilter.trim())
    fetch(`/api/traffic/observations?${params.toString()}`)
      .then(async response => {
        if (!response.ok) throw new Error(`Traffic observations are unavailable (HTTP ${response.status}).`)
        const body = await response.json()
        if (!Array.isArray(body.observations)) throw new Error('Traffic observations response had an unexpected format.')
        return { rows: body.observations as TrafficObservation[], total: Number.isInteger(body.total) ? body.total : body.observations.length }
      })
      .then(({ rows, total }) => { if (!cancelled) { setTrafficObservations(rows); setTrafficObservationTotal(total) } })
      .catch(failure => { if (!cancelled) setTrafficError(failure instanceof Error ? failure.message : 'Traffic observations are unavailable.') })
      .finally(() => { if (!cancelled) setTrafficLoading(false) })
    return () => { cancelled = true }
  }, [trafficEnabled, tab, trafficAreaFilter, result?.routes[0]?.geometry])

  useEffect(() => {
    if (!['dashboard', 'analytics', 'monitoring', 'sources', 'predictions'].includes(tab)) return
    if (trafficStats) return
    let cancelled = false
    fetch('/api/traffic/stats')
      .then(async response => {
        if (!response.ok) throw new Error('Traffic observation summary is temporarily unavailable.')
        return response.json() as Promise<TrafficStats>
      })
      .then(data => { if (!cancelled) setTrafficStats(data) })
      .catch(failure => { if (!cancelled) setStatsError(failure instanceof Error ? failure.message : 'Traffic observation summary is temporarily unavailable.') })
    return () => { cancelled = true }
  }, [tab, trafficStats])

  useEffect(() => {
    if (tab !== 'analytics') return
    let cancelled = false
    fetch('/api/analytics/areas')
      .then(async response => { if (!response.ok) throw new Error(`Area analytics unavailable (HTTP ${response.status}).`); return response.json() })
      .then(data => { if (!cancelled && Array.isArray(data.areas)) { setAnalyticsAreas(data.areas); if (data.areas.length && !data.areas.some((item: AnalyticsAreaSummary) => item.area === analyticsArea)) setAnalyticsArea(data.areas[0].area) } })
      .catch(failure => { if (!cancelled) setAnalyticsError(failure instanceof Error ? failure.message : 'Area analytics unavailable.') })
    return () => { cancelled = true }
  }, [tab])

  useEffect(() => {
    if (tab !== 'analytics' || !analyticsArea) return
    let cancelled = false
    const params = new URLSearchParams({ area: analyticsArea, days: '30' })
    fetch(`/api/analytics/hourly?${params.toString()}`)
      .then(async response => { if (!response.ok) throw new Error(`Hourly analytics unavailable (HTTP ${response.status}).`); return response.json() })
      .then(data => { if (!cancelled) setHourlyAnalytics(data as HourlyAnalytics) })
      .catch(failure => { if (!cancelled) setAnalyticsError(failure instanceof Error ? failure.message : 'Hourly analytics unavailable.') })
    return () => { cancelled = true }
  }, [tab, analyticsArea])

  const useMyLocation = () => {
    setError('')
    setGpsLoading(true)
    const editVersionAtRequest = originEditVersion.current
    if (!navigator.geolocation) {
      setError('This browser does not support location access. Enter your starting point manually.')
      setGpsLoading(false)
      return
    }
    navigator.geolocation.getCurrentPosition(
      async position => {
        const latitude = position.coords.latitude
        const longitude = position.coords.longitude
        try {
          if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) throw new Error('The browser returned invalid GPS coordinates. Enter a starting point manually.')
          const validation = await fetch('/api/routes/validate-point', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ latitude, longitude }),
          })
          if (!validation.headers.get('content-type')?.includes('application/json')) throw new Error('GPS validation returned a non-JSON response. Restart the project backend or enter a location manually.')
          const result = await validation.json()
          if (!validation.ok) {
            if (validation.status === 404) throw new Error('GPS validation is missing from the running backend. Restart the project backend or enter a location manually.')
            throw new Error(result.detail || `Location validation failed (HTTP ${validation.status}).`)
          }
          if (result.valid !== true) throw new Error('The backend did not confirm this GPS point is inside India. Enter a location manually.')
          if (originEditVersion.current !== editVersionAtRequest) {
            setError('The starting point was edited while GPS was being checked. Your manual entry was kept.')
            return
          }
          setOrigin(`${latitude.toFixed(6)}, ${longitude.toFixed(6)}`)
          setOriginPlace(null)
          setRouteGpsPoint([latitude, longitude])
          setError('')
        } catch (failure) {
          setError(failure instanceof Error ? failure.message : 'Could not validate the GPS position. Enter an Indian location manually.')
        } finally {
          setGpsLoading(false)
        }
      },
      failure => {
        setError(failure.code === 1 ? 'Location permission denied. You can still enter your starting point manually.' : 'Could not get your location. Check device location settings or enter it manually.')
        setGpsLoading(false)
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 },
    )
  }

  const recenterOnCurrentLocation = () => {
    const knownLocation = navigationPosition || routeGpsPoint
    if (knownLocation) {
      setRecenterSignal(value => value + 1)
      return
    }
    if (!navigator.geolocation) {
      setError('This browser does not support location access. Use the map controls to position the map manually.')
      return
    }
    setError('')
    navigator.geolocation.getCurrentPosition(
      position => {
        const point: Point = [position.coords.latitude, position.coords.longitude]
        setRouteGpsPoint(point)
        setRecenterSignal(value => value + 1)
      },
      failure => setError(failure.code === 1 ? 'Location permission denied. You can still position the map manually.' : 'Could not get your location. Check device location settings and try again.'),
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 },
    )
  }

  const findRoute = async () => {
    stopNavigation()
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const body: Record<string, string | number> = {
        origin: originPlace?.formattedAddress || origin,
        destination: destinationPlace?.formattedAddress || destination,
      }
      if (originPlace) {
        body.origin_lat = originPlace.latitude
        body.origin_lon = originPlace.longitude
      }
      if (destinationPlace) {
        body.destination_lat = destinationPlace.latitude
        body.destination_lon = destinationPlace.longitude
      }
      const response = await fetch('/api/routes/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not calculate routes')
      const routeData = normalizeRouteResult(data)
      setResult(routeData)
      const fastest = routeData.routes.find(route => route.is_fastest) || routeData.routes[0]
      setSelected(fastest?.route_id || '')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Unable to connect to routing service. Make sure backend is running.')
    } finally {
      setLoading(false)
    }
  }

  const activeRoute = result?.routes.find(route => route.route_id === selected)
  const activeRouteRef = useRef(activeRoute)
  activeRouteRef.current = activeRoute
  const shortestRoute = result?.routes.find(route => route.is_shortest)
  const fastestRoute = result?.routes.find(route => route.is_fastest)
  const orderedRoutes = result ? [...result.routes].sort((a, b) => Number(b.is_fastest) - Number(a.is_fastest) || (a.duration ?? Infinity) - (b.duration ?? Infinity)) : []
  const hasTrafficAwareEstimates = result?.data_source.toLowerCase().includes('traffic-aware') ?? false
  const navigationProgress = navigationPosition && activeRoute ? progressOnRoute(navigationPosition, activeRoute.geometry) : null
  const routeMeters = (activeRoute?.distance ?? 0) * 1000
  const travelledForSteps = navigationProgress ? navigationProgress.fraction * routeMeters : 0
  const navigationStepIndex = activeRoute ? currentStepIndex(travelledForSteps, activeRoute.steps) : 0
  const navigationStep = activeRoute?.steps[navigationStepIndex] ?? null
  let metresToInstruction = 0
  if (activeRoute && navigationProgress) {
    for (let index = 0; index < navigationStepIndex; index += 1) metresToInstruction += (activeRoute.steps[index].distance_km ?? 0) * 1000
    metresToInstruction += (navigationStep?.distance_km ?? 0) * 1000
    metresToInstruction = Math.max(0, metresToInstruction - travelledForSteps)
  }
  const remainingDistanceKm = navigationProgress && activeRoute?.distance !== null && activeRoute?.distance !== undefined
    ? Math.max(0, activeRoute.distance * (1 - navigationProgress.fraction))
    : activeRoute?.distance ?? null
  const remainingMinutes = navigationProgress && activeRoute?.duration !== null && activeRoute?.duration !== undefined
    ? Math.max(0, activeRoute.duration * (1 - navigationProgress.fraction))
    : activeRoute?.duration ?? null
  const eta = remainingMinutes === null ? null : new Date(Date.now() + remainingMinutes * 60_000)

  const rerouteFrom = async (point: Point) => {
    if (reroutingRef.current) return
    reroutingRef.current = true
    setRerouting(true)
    setNavigationError('')
    try {
      const response = await fetch('/api/routes/compare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin: `${point[0]}, ${point[1]}`, destination: navigationDestination.current }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'OSRM could not calculate a new route.')
      const routeData = normalizeRouteResult(data)
      setResult(routeData)
      const nextRoute = routeData.routes.find(route => route.is_fastest) || routeData.routes[0]
      setSelected(nextRoute?.route_id || '')
      lastAnnouncedStep.current = ''
      setNavigationPosition(point)
      setOffRoute(false)
      offRouteTracker.current.reset()
      autoReroutePending.current = false
      setNavigationError('Route updated using the real OSRM road network.')
    } catch (failure) {
      autoReroutePending.current = false
      setNavigationError(failure instanceof Error ? failure.message : 'Could not reroute. Your existing route is still available.')
    } finally {
      reroutingRef.current = false
      setRerouting(false)
    }
  }

  const acceptNavigationPoint = (point: Point) => {
    setNavigationPosition(point)
    setNavigationStarting(false)
    setNavigationActive(true)
    const currentRoute = activeRouteRef.current
    const progress = currentRoute ? progressOnRoute(point, currentRoute.geometry) : null
    if (progress && offRouteTracker.current.observe(progress.distanceFromRouteMeters)) {
      setOffRoute(true)
      if (autoRerouteRef.current && !autoReroutePending.current) {
        autoReroutePending.current = true
        void rerouteFrom(point)
      }
    } else {
      offRouteTracker.current.reset()
      setOffRoute(false)
    }
  }

  const centerMapOnNavigationPoint = (point: Point) => {
    if (!routeMap) return
    routeMap.panTo({ lat: point[0], lng: point[1] })
    routeMap.setZoom(17)
  }

  const startNavigation = () => {
    if (!activeRoute) { setNavigationError('Find and select a route before starting navigation.'); return }
    if (!navigator.geolocation) { setNavigationError('This browser does not support GPS. You can still plan a route manually.'); return }
    if (!window.isSecureContext && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
      setNavigationError('Browser GPS requires HTTPS or localhost. Your manually planned route is still available.')
      return
    }
    setNavigationError('Waiting for a GPS fix…')
    setNavigationStarting(true)
    if (routeGpsPoint) centerMapOnNavigationPoint(routeGpsPoint)
    navigationBoundaryValidated.current = false
    navigationBoundaryCheckPending.current = false
    navigationDestination.current = destination
    try {
      navigationCleanup.current?.()
      navigationCleanup.current = startLocationWatch(navigator.geolocation,
        position => {
          if (position.coords.accuracy > 80) {
            setNavigationError(`GPS accuracy is poor (${Math.round(position.coords.accuracy)} m). Waiting for a better fix.`)
            return
          }
          const point: Point = [position.coords.latitude, position.coords.longitude]
          centerMapOnNavigationPoint(point)
          if (navigationBoundaryValidated.current) { acceptNavigationPoint(point); return }
          if (navigationBoundaryCheckPending.current) return
          navigationBoundaryCheckPending.current = true
          fetch('/api/routes/validate-point', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ latitude: point[0], longitude: point[1] }),
          }).then(async response => {
            const data = await response.json()
            if (!response.ok || data.valid !== true) throw new Error(typeof data.detail === 'string' ? data.detail : 'Current GPS location is outside India.')
            navigationBoundaryValidated.current = true
            navigationBoundaryCheckPending.current = false
            setNavigationError('GPS location validated inside India. Navigation is active.')
            acceptNavigationPoint(point)
          }).catch(failure => {
            navigationBoundaryCheckPending.current = false
            navigationCleanup.current?.()
            navigationCleanup.current = null
            setNavigationStarting(false)
            setNavigationActive(false)
            setNavigationPosition(null)
            setNavigationError(failure instanceof Error ? `${failure.message} Manual route planning remains available.` : 'Could not validate GPS location. Manual route planning remains available.')
          })
          return
        },
        failure => {
          navigationCleanup.current?.()
          navigationCleanup.current = null
          setNavigationActive(false)
          setNavigationStarting(false)
          setNavigationPosition(null)
          setNavigationError(failure.code === 1
            ? 'GPS permission was denied. Navigation stopped; manual route planning remains available.'
            : 'GPS position is unavailable. Check location settings or continue with manual route planning.')
        })
    } catch {
      setNavigationStarting(false)
      setNavigationError('Could not start GPS navigation. Check browser location permission or continue manually.')
    }
  }

  useEffect(() => {
    if (!navigationActive || !voiceEnabled || !navigationStep || !('speechSynthesis' in window)) return
    const key = `${activeRoute?.route_id}:${navigationStepIndex}`
    if (lastAnnouncedStep.current === key) return
    lastAnnouncedStep.current = key
    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(navigationStep.instruction))
  }, [navigationActive, voiceEnabled, navigationStep, navigationStepIndex, activeRoute?.route_id])

  const latestBySegment = new Map<string, TrafficObservation>()
  trafficObservations
    .filter(row => ['actual', 'historical'].includes((row.data_status || '').toLowerCase()) && row.road_segment)
    .forEach(row => {
      const id = row.road_segment!.segment_id
      const prior = latestBySegment.get(id)
      if (!prior || (row.timestamp || '') > (prior.timestamp || '')) latestBySegment.set(id, row)
    })
  const verifiedTrafficSegments = [...latestBySegment.values()]
  const verifiedTrafficObservations = trafficObservations.filter(row => ['actual', 'historical'].includes((row.data_status || '').toLowerCase()))
  const routeTrafficSegments = activeRoute ? verifiedTrafficSegments.filter(row => {
    const segment = row.road_segment!
    const startGap = progressOnRoute(segment.start, activeRoute.geometry)?.distanceFromRouteMeters ?? Infinity
    const endGap = progressOnRoute(segment.end, activeRoute.geometry)?.distanceFromRouteMeters ?? Infinity
    return startGap <= 150 && endGap <= 150
  }) : []
  const classifiedRouteSegments = routeTrafficSegments.filter(row => congestionColor(row.congestion_level) !== '#64748b')
  const trafficDistanceByLevel = { low: 0, moderate: 0, heavy: 0 }
  let classifiedMeters = 0
  for (const row of classifiedRouteSegments) {
    const segment = row.road_segment!
    const meters = routeSegmentLengthMeters(segment.start, segment.end)
    const level = (row.congestion_level || '').toLowerCase()
    const key = ['low', 'free'].includes(level) ? 'low' : ['moderate', 'medium'].includes(level) ? 'moderate' : 'heavy'
    trafficDistanceByLevel[key] += meters / 1000
    classifiedMeters += meters
  }
  const trafficCoveragePercent = activeRoute?.distance ? Math.min(100, classifiedMeters / (activeRoute.distance * 1000) * 100) : 0
  const routeObservationDates = routeTrafficSegments.map(row => row.timestamp).filter((value): value is string => !!value).sort()
  const lastRouteObservation = routeObservationDates[routeObservationDates.length - 1] || null

  useEffect(() => {
    if (!routeMap || !result) return
    const overlays: Array<google.maps.Marker | google.maps.Polyline> = []
    overlays.push(new google.maps.Marker({
      map: routeMap,
      position: { lat: result.origin_point[0], lng: result.origin_point[1] },
      title: `Start: ${result.origin}`,
      icon: googlePinIcon('S', '#16a34a'),
      zIndex: 30,
    }))
    overlays.push(new google.maps.Marker({
      map: routeMap,
      position: { lat: result.destination_point[0], lng: result.destination_point[1] },
      title: `Destination: ${result.destination}`,
      icon: googlePinIcon('D', '#dc2626'),
      zIndex: 30,
    }))
    result.routes.filter(route => route.route_id !== selected).forEach((route, index) => {
      const color = route.is_shortest ? '#2563eb' : route.is_fastest ? '#f59e0b' : ROUTE_COLORS[index % ROUTE_COLORS.length]
      overlays.push(new google.maps.Polyline({
        map: routeMap,
        path: route.geometry.map(([lat, lng]) => ({ lat, lng })),
        strokeColor: color,
        strokeOpacity: 0.78,
        strokeWeight: 4,
        zIndex: 5,
      }))
    })
    if (activeRoute) {
      const path = activeRoute.geometry.map(([lat, lng]) => ({ lat, lng }))
      overlays.push(new google.maps.Polyline({ map: routeMap, path, strokeColor: '#f8fafc', strokeOpacity: 1, strokeWeight: 12, zIndex: 30 }))
      overlays.push(new google.maps.Polyline({ map: routeMap, path, strokeColor: '#31c9e2', strokeOpacity: 1, strokeWeight: 8, zIndex: 31 }))
    }
    return () => overlays.forEach(overlay => overlay.setMap(null))
  }, [routeMap, result, selected, activeRoute])

  useEffect(() => {
    if (!routeMap || !activeRoute || !result || !trafficEnabled) {
      setRouteTrafficStatus('')
      return
    }
    let cancelled = false
    const trafficLines: google.maps.Polyline[] = []
    setRouteTrafficStatus('Loading traffic conditions for the selected route…')

    void loadGoogleRoutesLibrary().then(async ({ Route: GoogleRoute }) => {
      const geometry = activeRoute.geometry
      const maxIntermediates = 23
      const stride = Math.max(1, Math.ceil((geometry.length - 2) / maxIntermediates))
      const intermediates: google.maps.routes.Waypoint[] = []
      for (let index = stride; index < geometry.length - 1 && intermediates.length < maxIntermediates; index += stride) {
        const [lat, lng] = geometry[index]
        intermediates.push({ location: { lat, lng }, via: true })
      }
      const response = await GoogleRoute.computeRoutes({
        origin: { lat: result.origin_point[0], lng: result.origin_point[1] },
        destination: { lat: result.destination_point[0], lng: result.destination_point[1] },
        intermediates,
        travelMode: 'DRIVING',
        routingPreference: 'TRAFFIC_AWARE',
        extraComputations: ['TRAFFIC_ON_POLYLINE'],
        fields: ['path', 'speedPaths'],
      })
      if (cancelled) return
      const route = response.routes?.[0]
      const speedPaths = route?.speedPaths ?? []
      let displayedSegments = 0
      const trafficCounts = { slow: 0, jam: 0 }
      for (const speedPath of speedPaths) {
        const speed = String(speedPath.speed || '').toUpperCase()
        const color = speed === 'SLOW' ? '#f59e0b' : speed === 'TRAFFIC_JAM' ? '#dc2626' : null
        if (!color || speedPath.path.length < 2) continue
        const level = speed === 'SLOW' ? 'slow' : 'jam'
        trafficCounts[level] += 1
        trafficLines.push(new google.maps.Polyline({
          map: routeMap,
          path: speedPath.path.map(point => ({ lat: point.lat, lng: point.lng })),
          strokeColor: color,
          strokeOpacity: 1,
          strokeWeight: 6,
          zIndex: 32,
        }))
        displayedSegments += 1
      }
      setRouteTrafficStatus(displayedSegments
        ? `Selected route: ${trafficCounts.slow} moderate and ${trafficCounts.jam} heavy traffic sections. Flowing roads are hidden.`
        : 'No moderate or heavy traffic sections reported on this route. Flowing roads are hidden.')
    }).catch((failure: unknown) => {
      if (cancelled) return
      const message = failure instanceof Error ? failure.message : 'Traffic data could not be loaded.'
      const quotaExceeded = /resource_exhausted|quota exceeded|per day.*quota/i.test(message)
      setRouteTrafficStatus(quotaExceeded
        ? 'Live traffic is unavailable because the Google Routes API quota is exhausted. The route card still shows the OSRM road-network ETA.'
        : 'Live traffic is temporarily unavailable. The route card still shows the OSRM road-network ETA.')
    })

    return () => {
      cancelled = true
      trafficLines.forEach(line => line.setMap(null))
    }
  }, [routeMap, activeRoute, result, trafficEnabled])

  useEffect(() => {
    if (!routeMap || !navigationPosition) return
    const marker = new google.maps.Marker({
      map: routeMap,
      position: { lat: navigationPosition[0], lng: navigationPosition[1] },
      title: 'Current GPS location',
      icon: { path: google.maps.SymbolPath.CIRCLE, scale: 9, fillColor: '#2563eb', fillOpacity: 1, strokeColor: '#ffffff', strokeWeight: 3 },
      zIndex: 50,
    })
    return () => marker.setMap(null)
  }, [routeMap, navigationPosition])

  useEffect(() => {
    if (!routeMap || !trafficEnabled) return
    const lines = routeTrafficSegments.flatMap(row => {
      const segment = row.road_segment
      const color = visibleTrafficColor(row.congestion_level)
      if (!segment || !color) return []
      return [new google.maps.Polyline({
        map: routeMap,
        path: [{ lat: segment.start[0], lng: segment.start[1] }, { lat: segment.end[0], lng: segment.end[1] }],
        strokeColor: color,
        strokeOpacity: 0.96,
        strokeWeight: 8,
        zIndex: 20,
      })]
    })
    return () => lines.forEach(line => line.setMap(null))
  }, [routeMap, trafficEnabled, routeTrafficSegments])

  useEffect(() => {
    if (!routeMap) return
    if (navigationActive && navigationPosition) {
      centerMapOnNavigationPoint(navigationPosition)
      return
    }
    if (recenterSignal > 0) {
      const point = navigationPosition || routeGpsPoint
      if (point) {
        centerMapOnNavigationPoint(point)
        return
      }
    }
  }, [routeMap, navigationActive, navigationPosition, routeGpsPoint, recenterSignal])

  useEffect(() => {
    if (!routeMap || !result?.routes.length) return
    const bounds = new google.maps.LatLngBounds()
    result.routes.forEach(route => route.geometry.forEach(([lat, lng]) => bounds.extend({ lat, lng })))
    if (!bounds.isEmpty()) routeMap.fitBounds(bounds, 64)
  }, [routeMap, result, mapFullscreen])

  return (
    <div className="hti-shell">
      {sidebarOpen && <button type="button" className="hti-sidebar-backdrop" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />}
      <aside className={`hti-sidebar ${sidebarOpen ? 'hti-sidebar-open' : ''}`} aria-label="Main navigation">
        <div className="hti-brand">
          <span className="hti-brand-mark"><Activity size={20} strokeWidth={2.2} /></span>
          <div><strong>INDIA TRAFFIC</strong><span>INTELLIGENCE</span></div>
        </div>
        <nav className="hti-side-navigation" aria-label="Main pages">
          {PRIMARY_NAV_ITEMS.filter(item => item.id !== 'settings').map(item => {
            const Icon = item.icon
            return <button key={item.id} type="button" onClick={() => { setTab(item.id); setSidebarOpen(false) }} className={`hti-side-link ${tab === item.id ? 'hti-side-link-active' : ''}`} aria-current={tab === item.id ? 'page' : undefined}>
              <Icon size={18} strokeWidth={1.8} /><span>{item.label}</span>
            </button>
          })}
        </nav>
        <div className="hti-sidebar-spacer" />
        <nav className="hti-side-navigation hti-sidebar-settings" aria-label="Settings">
          {PRIMARY_NAV_ITEMS.filter(item => item.id === 'settings').map(item => {
            const Icon = item.icon
            return <button key={item.id} type="button" onClick={() => { setTab(item.id); setSidebarOpen(false) }} className={`hti-side-link ${tab === item.id ? 'hti-side-link-active' : ''}`} aria-current={tab === item.id ? 'page' : undefined}>
              <Icon size={18} strokeWidth={1.8} /><span>{item.label}</span>
            </button>
          })}
        </nav>
        <div className="hti-sidebar-footer">
          <span className={`hti-api-indicator ${healthState}`}><i />{healthState === 'online' ? 'System connected' : healthState === 'offline' ? 'Connection unavailable' : 'Connecting'}</span>
          <small>India coverage · v1.0</small>
        </div>
      </aside>
      <div className="hti-content-shell">
        <header className="hti-topbar">
          <div className="hti-topbar-title">
            <button type="button" className="hti-mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Menu size={19} /></button>
            <span className="hti-topbar-mark"><Navigation size={18} /></span>
            <div><p className="hti-eyebrow">INDIA TRAFFIC INTELLIGENCE</p><h1>{PRIMARY_NAV_ITEMS.find(item => item.id === tab)?.label ?? 'Route Planner'}</h1></div>
          </div>
          <div className="hti-topbar-status">
            <span className={`hti-api-indicator ${healthState}`}><i />{healthState === 'online' ? 'API connected' : healthState === 'offline' ? 'API unavailable' : 'Connecting'}</span>
            <span className="hti-location-status"><LocateFixed size={15} />{navigationPosition ? 'GPS tracking' : routeGpsPoint ? 'GPS location ready' : 'India'}</span>
          </div>
        </header>

      <main className="hti-main-content">
        {tab === 'dashboard' && <>
          <section className="hti-welcome-panel">
            <div><p className="hti-eyebrow">INDIA</p><h2>Good {new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 17 ? 'afternoon' : 'evening'}</h2><p>Traffic intelligence and road navigation for India.</p></div>
            <button onClick={() => setTab('routes')} className="hti-primary-button"><Route size={17} />Plan a route</button>
          </section>
          <section className="hti-metric-grid" aria-label="Traffic data overview">
            <article className="hti-metric-card"><span className="hti-metric-icon"><Activity size={18} /></span><p>Genuine observations</p><strong>{trafficStats ? trafficStats.observation_count.toLocaleString() : 'Unavailable'}</strong><small>{trafficStats?.observation_count === 0 ? 'No traffic observations available' : 'Actual and historical records'}</small></article>
            <article className="hti-metric-card"><span className="hti-metric-icon violet"><MapPinned size={18} /></span><p>Traffic data coverage</p><strong>{trafficStats && supportedAreaCount ? `${((trafficStats.covered_area_count / supportedAreaCount) * 100).toFixed(1)}%` : 'Unavailable'}</strong><small>{trafficStats ? `${trafficStats.covered_area_count} of ${supportedAreaCount ?? '—'} areas have observations` : 'India project coverage'}</small></article>
            <article className="hti-metric-card"><span className="hti-metric-icon green"><Database size={18} /></span><p>Registered data sources</p><strong>{trafficStats ? trafficStats.sources.length : 'Unavailable'}</strong><small>Source metadata registry</small></article>
            <article className="hti-metric-card"><span className="hti-metric-icon amber"><Navigation size={18} /></span><p>Navigation session</p><strong>{navigationActive ? 'Active' : 'Inactive'}</strong><small>{navigationActive ? 'GPS in this browser' : 'Start from a selected route'}</small></article>
          </section>
          <section className="hti-content-grid">
            <article className="hti-panel"><div className="hti-panel-heading"><div><p className="hti-eyebrow">STREET MAP</p><h3>India traffic map</h3></div><button onClick={() => { setTab('monitoring'); setTrafficEnabled(true) }} className="hti-quiet-button">Open monitoring</button></div><TrafficMap observations={trafficObservations} className="h-[390px]" />{verifiedTrafficSegments.length === 0 && <p className="hti-empty-inline">Traffic data unavailable. No road-segment-linked traffic measurements are recorded.</p>}</article>
            <article className="hti-panel"><div className="hti-panel-heading"><div><p className="hti-eyebrow">RECENT ACTIVITY</p><h3>Latest observations</h3></div><span className="hti-count-pill">{verifiedTrafficObservations.length} loaded</span></div>
              {verifiedTrafficObservations.length === 0 ? <div className="hti-empty-state"><Database size={24} /><strong>No recent traffic activity</strong><span>Import verified India traffic measurements to populate this list.</span></div> : <div className="hti-observation-list">{verifiedTrafficObservations.slice(0, 6).map(row => <div key={row.observation_id}><span className="hti-observation-dot" /><div><strong>{row.road_name || row.road_segment?.name || 'Road name unavailable'}</strong><span>{row.timestamp ? new Date(row.timestamp).toLocaleString() : 'Timestamp unavailable'} · {row.data_status}</span></div><b>{row.average_speed_kmh == null ? '—' : `${row.average_speed_kmh} km/h`}</b></div>)}</div>}
            </article>
          </section>
          {trafficStats && trafficStats.observation_count === 0 && <p className="hti-data-notice"><AlertCircle size={17} />No traffic observations available. Dashboard metrics and map conditions are not estimated or simulated.</p>}
        </>}

        {tab === 'navigation' && <section className="hti-panel hti-page-empty"><span className="hti-empty-icon"><Navigation size={25} /></span><p className="hti-eyebrow">LIVE NAVIGATION</p><h2>Choose a route before starting</h2><p>Navigation uses your browser GPS only after you explicitly start it. Your location is not saved to GPS contribution storage.</p><button onClick={() => setTab('routes')} className="hti-primary-button"><Route size={17} />Open route planner</button></section>}

        {tab === 'monitoring' && <section className="hti-panel">
          <div className="hti-panel-heading"><div><p className="hti-eyebrow">OBSERVED CONDITIONS</p><h2>Traffic monitoring</h2><p className="hti-muted">Only source-recorded actual or historical observations linked to a road segment are drawn.</p></div><button onClick={() => setTrafficEnabled(value => !value)} className="hti-quiet-button">{trafficEnabled ? 'Layer enabled' : 'Enable traffic layer'}</button></div>
          <form className="hti-search-row" onSubmit={event => { event.preventDefault(); setTrafficAreaFilter(trafficAreaSearch.trim()) }}><div><Search size={17} /><input value={trafficAreaSearch} onChange={event => setTrafficAreaSearch(event.target.value)} placeholder="Filter by Indian area name" aria-label="Search traffic observations by area" /></div><button className="hti-primary-button" type="submit">Search area</button>{trafficAreaFilter && <button type="button" className="hti-quiet-button" onClick={() => { setTrafficAreaSearch(''); setTrafficAreaFilter('') }}><X size={15} />Clear</button>}</form>
          <div className="hti-traffic-legend"><b>Traffic legend</b><span><i className="green" />Low</span><span><i className="yellow" />Moderate</span><span><i className="red" />Heavy</span><span><i className="grey" />Unavailable / unclassified</span></div>
          <TrafficMap observations={trafficObservations} enabled={trafficEnabled} className="h-[min(62vh,620px)] min-h-[360px]" />
          <div className="hti-monitoring-stats"><span><b>{verifiedTrafficObservations.length}</b> valid records loaded of {trafficObservationTotal} total</span><span><b>{verifiedTrafficSegments.length}</b> mapped road segments</span><span><b>{verifiedTrafficSegments.length ? 'Recorded' : 'Unavailable'}</b> road coverage</span><span><b>{verifiedTrafficObservations.map(row => row.timestamp).filter((date): date is string => !!date).sort().slice(-1)[0] ? new Date(verifiedTrafficObservations.map(row => row.timestamp).filter((date): date is string => !!date).sort().slice(-1)[0]!).toLocaleString() : 'Unavailable'}</b> last observation</span></div>
          {trafficError && <p className="hti-data-notice"><AlertCircle size={17} />{trafficError}</p>}{!trafficLoading && !trafficError && verifiedTrafficObservations.length === 0 && <p className="hti-data-notice"><AlertCircle size={17} />Traffic data unavailable. Individual GPS samples are not included as road-wide traffic.</p>}
        </section>}

        {tab === 'sources' && <section className="hti-panel"><div className="hti-panel-heading"><div><p className="hti-eyebrow">PROVENANCE</p><h2>Data sources</h2><p className="hti-muted">Source details come from the backend registry.</p></div><span className="hti-count-pill">{trafficStats?.sources.length ?? '—'} registered</span></div>
          {!trafficStats && !statsError && <p className="hti-muted">Loading data source registry…</p>}{statsError && <p className="hti-data-notice"><AlertCircle size={17} />{statsError}</p>}
          {trafficStats?.sources.length === 0 && <div className="hti-empty-state"><Database size={24} /><strong>No registered data sources</strong><span>Source metadata will appear after datasets are imported.</span></div>}
          <div className="hti-source-grid">{trafficStats?.sources.map(source => <article key={source.source_name} className="hti-source-card"><div className="hti-source-heading"><Database size={17} /><span className="hti-count-pill">{source.data_type || 'Unclassified'}</span></div><h3>{source.source_name}</h3><p>{source.city_coverage || 'Coverage unspecified'}</p><dl><div><dt>Genuine observations</dt><dd>{source.observation_count.toLocaleString()}</dd></div><div><dt>Collection period</dt><dd>{source.collection_period || 'Unavailable'}</dd></div><div><dt>Licence</dt><dd>{source.license || 'Unspecified'}</dd></div><div><dt>Last updated</dt><dd>{source.imported_at ? new Date(source.imported_at).toLocaleString() : 'Unavailable'}</dd></div><div><dt>Reliability</dt><dd>{source.observation_count ? 'Source-reported traffic observations' : 'Registered metadata; no matching traffic observations'}</dd></div></dl>{source.source_url && <a href={source.source_url} target="_blank" rel="noreferrer" className="hti-source-link">Open source <span>↗</span></a>}{source.notes && <p className="hti-source-notes">{source.notes}</p>}</article>)}</div>
        </section>}

        {tab === 'settings' && <section className="hti-panel"><div className="hti-panel-heading"><div><p className="hti-eyebrow">PREFERENCES & STATUS</p><h2>Settings</h2></div></div><div className="hti-settings-list">
          <div><div><strong>Automatic rerouting</strong><span>Recalculate after two consecutive GPS fixes are more than 70 m from the selected road geometry.</span></div><input type="checkbox" checked={autoReroute} onChange={event => setAutoReroute(event.target.checked)} aria-label="Automatic rerouting" /></div>
          <div><div><strong>Voice guidance</strong><span>Use the browser Web Speech API for turn instructions.</span></div><input type="checkbox" checked={voiceEnabled} disabled={!('speechSynthesis' in window)} onChange={event => setVoiceEnabled(event.target.checked)} aria-label="Voice guidance" /></div>
          <div><div><strong>Traffic overlay</strong><span>Show validated road-segment observations on map views.</span></div><input type="checkbox" checked={trafficEnabled} onChange={event => setTrafficEnabled(event.target.checked)} aria-label="Traffic overlay" /></div>
          <div><div><strong>Backend API</strong><span>Health endpoint and local proxy connectivity.</span></div><b className={`hti-api-indicator ${healthState}`}><i />{healthState}</b></div>
        </div><p className="hti-data-notice"><MapPinned size={17} />Your Maps key powers the map, place search, traffic-aware route estimates, and live traffic display. Enable Maps JavaScript API, Places API, and route computation; restrict the key to your website referrers. Traffic-aware route requests may incur Maps Platform charges.</p></section>}

        {tab === 'routes' && <>
          <section className="hti-route-search-panel bg-white rounded-2xl shadow-sm border p-5 mb-5">
            <div className="flex items-center gap-2 mb-4"><Navigation className="text-cyan-700" /><h2 className="font-bold text-lg">Plan your journey</h2></div>
            <div className="hti-route-search-grid">
              <LocationAutocomplete
                label="STARTING POINT"
                value={origin}
                onChange={value => { originEditVersion.current += 1; setOrigin(value) }}
                onSelect={setOriginPlace}
                placeholder="Search any place in India"
                action={<button type="button" onClick={useMyLocation} disabled={gpsLoading} className="hti-current-location-button">
                  <LocateFixed size={15} />{gpsLoading ? 'Getting current location…' : 'Use current location'}
                </button>}
              />
              <button onClick={() => {
                const previousText = origin
                const previousPlace = originPlace
                setOrigin(destination)
                setOriginPlace(destinationPlace)
                setDestination(previousText)
                setDestinationPlace(previousPlace)
                originEditVersion.current += 1
              }} className="hti-swap-button" aria-label="Swap origin and destination"><ArrowLeftRight size={18} /></button>
              <LocationAutocomplete
                label="DESTINATION"
                value={destination}
                onChange={setDestination}
                onSelect={setDestinationPlace}
                placeholder="Search a city, landmark, or address"
              />
              <div className="flex gap-2">
                <button onClick={findRoute} disabled={loading} className="bg-cyan-700 hover:bg-cyan-800 disabled:opacity-50 text-white rounded-lg px-5 py-3 font-semibold whitespace-nowrap">{loading ? 'Finding…' : 'Find routes'}</button>
              </div>
            </div>
            <p className="text-xs text-slate-500 mt-3">Search landmarks, addresses, transport hubs, and towns across India, or use your current location as the starting point.</p>
            {error && <div className="mt-3 rounded-lg bg-amber-50 text-amber-800 p-3 text-sm flex gap-2"><AlertCircle size={17} className="shrink-0" />{error}</div>}
          </section>

          <div className="hti-route-layout grid lg:grid-cols-[390px_1fr] gap-5">
            <section className="hti-route-options bg-white rounded-2xl shadow-sm border p-4 min-w-0">
              <div className="hti-route-options-heading"><div><p className="hti-eyebrow">COMPARE JOURNEYS</p><h3 className="font-bold">Route options</h3></div>{result && <span className="hti-count-pill">{result.routes.length} options</span>}</div>
              {!result && <div className="text-sm text-slate-500 bg-slate-50 rounded-xl p-5">Enter a starting point and destination, then select Find routes. Available road-network routes will appear here.</div>}
              {result && <>
                <p className="text-xs text-slate-600 bg-slate-50 rounded-lg p-3 mb-3">{result.alternatives_note}{result.shortest_fastest_same && <> The shortest and fastest estimated routes are the same.</>} {result.traffic_note} Select a route to highlight it; all alternatives stay visible on the map.</p>
                <div className="hti-route-list max-h-[350px] overflow-y-auto pr-1">
                  {orderedRoutes.map(route => {
                    const distanceDifference = routeDifference(route.distance, shortestRoute?.distance ?? null)
                    const timeDifference = routeDifference(route.duration, fastestRoute?.duration ?? null)
                    return (
                      <button key={route.route_id} onClick={() => setSelected(route.route_id)} aria-pressed={selected === route.route_id} className={`hti-route-option w-full text-left border rounded-xl p-4 mb-3 transition-colors ${selected === route.route_id ? 'hti-route-option-selected border-cyan-600 bg-cyan-50 ring-1 ring-cyan-600' : 'border-slate-200 hover:border-slate-400'}`}>
                        <div className="flex justify-between gap-2 items-start">
                          <span className="font-semibold">Route {route.route_number}</span>
                          <span className="flex gap-1 flex-wrap justify-end">
                            {route.is_fastest && <span className="text-[10px] bg-emerald-100 text-emerald-800 px-2 py-1 rounded-full">FASTEST ESTIMATE</span>}
                            {route.is_shortest && <span className="text-[10px] bg-blue-100 text-blue-800 px-2 py-1 rounded-full">SHORTEST</span>}
                          </span>
                        </div>
                        <div className="flex gap-4 mt-3 text-sm"><span className="flex items-center gap-1"><MapPin size={15} />{formatRouteNumber(route.distance, 2)}{route.distance === null ? '' : ' km'}</span><span className="flex items-center gap-1"><Clock size={15} />{formatDurationMinutes(route.duration)} estimated</span></div>
                        <p className={`text-[10px] font-semibold mt-2 ${hasTrafficAwareEstimates ? 'text-emerald-700' : 'text-amber-700'}`}>{hasTrafficAwareEstimates ? 'Traffic-aware time estimate' : 'Road-network ETA (estimated)'}</p>
                        {!hasTrafficAwareEstimates && route.duration !== null && <p className="text-[11px] text-slate-500 mt-1">{formatEstimatedArrival(route.duration)} based on estimated drive time.</p>}
                        {hasTrafficAwareEstimates && route.static_duration !== null && <p className="text-[11px] text-slate-500 mt-1">Typical time without current traffic: {formatDurationMinutes(route.static_duration)}{route.duration !== null && route.duration > route.static_duration ? ` · current traffic adds ${formatDurationMinutes(route.duration - route.static_duration)}` : ''}</p>}
                        <div className="grid grid-cols-2 gap-2 mt-3 text-xs text-slate-600">
                          <span>Distance vs shortest: {distanceDifference === null ? 'Unavailable' : `+${formatRouteNumber(distanceDifference, 2)} km`}</span>
                          <span>Time vs fastest: {timeDifference === null ? 'Unavailable' : `+${formatDurationMinutes(timeDifference)}`}</span>
                        </div>
                        <p className="text-[11px] text-slate-500 mt-2 capitalize">Route type: {route.route_type} · {result.data_source}</p>
                      </button>
                    )
                  })}
                </div>
              </>}
              {activeRoute && <div className="hti-directions-panel border-t pt-3 mt-2">
                <div className="hti-directions-heading"><div><p className="hti-eyebrow">TURN-BY-TURN</p><h4 className="font-semibold text-sm">Directions</h4></div><span className="hti-directions-total">{formatRouteNumber(activeRoute.distance, 2)} km · {formatDurationMinutes(activeRoute.duration)}</span></div>
                <div className="hti-directions-list max-h-64 overflow-auto space-y-2 mt-3">
                  {activeRoute.steps.map((step, index) => <div key={`${activeRoute.route_id}-${index}`} className="hti-direction-step flex gap-3 text-xs border-b pb-2">
                    <span className="hti-direction-step-icon"><Navigation size={15} style={{ transform: `rotate(${turnIconRotation(step.instruction)}deg)` }} /></span>
                    <div><p>{step.instruction}</p>{step.road_name && <p className="text-slate-500">Road: {step.road_name}</p>}<p className="text-slate-500 mt-1">{formatRouteNumber(step.distance_km, 2)}{step.distance_km === null ? '' : ' km'} · {formatDurationMinutes(step.duration_minutes)}</p></div>
                  </div>)}
                </div>
              </div>}
              {activeRoute && <section className="border-t mt-4 pt-4" aria-label="Navigation controls">
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => setVoiceEnabled(value => !value)} disabled={!('speechSynthesis' in window)} className="rounded-lg border px-3 py-2 text-sm flex items-center gap-2 disabled:opacity-50" title={!('speechSynthesis' in window) ? 'Voice guidance is not supported by this browser' : undefined}>
                    {voiceEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}{voiceEnabled ? 'Voice on' : 'Voice off'}
                  </button>
                  <button onClick={recenterOnCurrentLocation} className="rounded-lg border px-3 py-2 text-sm flex items-center gap-2" title="Center the map on your current or last known GPS location"><Crosshair size={16} />Recenter</button>
                </div>
                <label className="flex gap-2 items-center text-xs text-slate-600 mt-3"><input type="checkbox" checked={autoReroute} onChange={event => setAutoReroute(event.target.checked)} />Automatically reroute after repeated off-route GPS fixes</label>
                {(navigationActive || navigationStarting) && <div className="hti-live-nav-card rounded-xl bg-slate-950 text-white p-4 mt-3">
                  <p className="text-xs uppercase tracking-wide text-cyan-300">{navigationStarting ? 'Waiting for GPS' : 'Navigation active'}</p>
                  <h4 className="font-semibold mt-1">{navigationStep?.instruction || 'Following selected route'}</h4>
                  {navigationStep?.road_name && <p className="text-sm text-slate-300 mt-1">Current road: {navigationStep.road_name}</p>}
                  <div className="grid grid-cols-2 gap-2 mt-3 text-sm">
                    <p>Distance to next instruction: {navigationProgress ? formatDistance(metresToInstruction) : 'Waiting for GPS'}</p>
                    <p>Remaining distance: {remainingDistanceKm === null ? 'Unavailable' : `${remainingDistanceKm.toFixed(1)} km`}</p>
                    <p>Remaining time: {remainingMinutes === null ? 'Unavailable' : formatDurationMinutes(Math.ceil(remainingMinutes))}</p>
                    <p>Estimated arrival: {eta ? eta.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Unavailable'}</p>
                  </div>
                  {navigationStepIndex + 1 < (activeRoute?.steps.length ?? 0) && <p className="text-xs text-slate-300 mt-2">Then: {activeRoute?.steps[navigationStepIndex + 1].instruction}</p>}
                  {offRoute && <div className="rounded-lg bg-amber-100 text-amber-950 p-3 mt-3 text-sm" role="alert">
                    <p className="font-semibold">You appear to be off route. GPS readings may be inaccurate.</p>
                    <button onClick={() => navigationPosition && void rerouteFrom(navigationPosition)} disabled={!navigationPosition || rerouting} className="mt-2 rounded-md bg-amber-800 text-white px-3 py-1.5 inline-flex gap-2 items-center disabled:opacity-50"><RefreshCw size={14} />{rerouting ? 'Rerouting…' : 'Reroute now'}</button>
                  </div>}
                </div>}
                {navigationError && <p className="text-xs text-slate-600 mt-2" role="status">{navigationError}</p>}
                <p className="text-[11px] text-slate-500 mt-2">Navigation fixes are not saved as GPS contributions. If you request rerouting, the current coordinate is sent to the routing backend and OSRM only to calculate a route.</p>
              </section>}
            </section>

            <section className={`hti-map-shell bg-white rounded-2xl shadow-sm border p-2 h-[min(760px,82vh)] min-h-[480px] flex flex-col ${mapFullscreen ? 'hti-map-fullscreen' : ''}`}>
              <div className="flex flex-wrap items-center gap-3 p-2 text-xs">
                {activeRoute && (navigationActive || navigationStarting
                  ? <button onClick={stopNavigation} className="hti-stop-navigation-button"><Square size={16} />End navigation</button>
                  : <button onClick={startNavigation} className="hti-start-navigation-button"><Play size={17} fill="currentColor" />Start</button>)}
                <button onClick={() => setTrafficEnabled(value => !value)} className="rounded-lg border px-3 py-2 font-medium">{trafficEnabled ? 'Disable traffic overlay' : 'Enable traffic overlay'}</button>
                <button onClick={recenterOnCurrentLocation} className="hti-quiet-button" title="Center the map on your current or last known GPS location"><Crosshair size={15} />Recenter</button>
                <button onClick={() => setMapFullscreen(value => !value)} className="hti-quiet-button" aria-label={mapFullscreen ? 'Exit full-screen map' : 'View full-screen map'}>{mapFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}{mapFullscreen ? 'Exit full screen' : 'Full screen'}</button>
                {trafficLoading && <span className="text-slate-500">Loading recorded observations…</span>}
                {trafficError && <span className="text-amber-800">{trafficError}</span>}
                {trafficEnabled && !routeMapError && <span className="text-slate-600">{activeRoute ? `Route traffic · ${routeTrafficStatus || 'Loading route traffic details…'}` : 'Plan a route to see traffic conditions along it.'}</span>}
                {routeMapError && <span className="text-amber-800">{routeMapError}</span>}
              </div>
              {trafficEnabled && <div className="flex flex-wrap gap-x-3 gap-y-1 px-2 pb-2 text-[11px] text-slate-600" aria-label="Traffic legend">
                <span className="font-semibold">Route traffic:</span>
                <span className="flex items-center gap-1"><i className="w-3 h-3 rounded-full bg-amber-500" />Moderate</span>
                <span className="flex items-center gap-1"><i className="w-3 h-3 rounded-full bg-red-600" />Heavy</span>
                <span className="flex items-center gap-1"><i className="w-3 h-3 rounded-full bg-red-950" />Severe</span>
                <span className="flex items-center gap-1"><i className="w-3 h-3 rounded-full bg-slate-500" />No data</span>
              </div>}
              {activeRoute && <div className="flex flex-wrap gap-x-3 gap-y-1 px-2 pb-2 text-[11px] text-slate-600" aria-label="Route legend">
                <span className="font-semibold">Routes:</span>
                <span className="flex items-center gap-1"><i className="w-4 h-[3px] bg-slate-900" />Selected</span>
                <span className="flex items-center gap-1"><i className="w-4 h-[3px] bg-blue-600" />Shortest</span>
                <span className="flex items-center gap-1"><i className="w-4 h-[3px] bg-amber-500" />Fastest</span>
                <span className="flex items-center gap-1"><i className="w-4 h-[3px] bg-violet-600" />Alternative</span>
              </div>}
              <div className="hti-route-map-canvas flex-1 min-h-0 rounded-lg overflow-hidden">
                {(navigationActive || navigationStarting) && activeRoute && <div className="hti-nav-map-banner" aria-live="polite">
                  <span className="hti-nav-map-icon"><Navigation size={19} /></span>
                  <div><p className="hti-eyebrow">{navigationStarting ? 'WAITING FOR GPS' : 'NEXT INSTRUCTION'}</p><strong>{navigationStep?.instruction || 'Following selected route'}</strong><small>{navigationPosition ? `In ${formatDistance(metresToInstruction)}` : 'Waiting for a GPS fix'}</small></div>
                </div>}
                <GoogleMapsCanvas className="absolute inset-0" onMapReady={setRouteMap} onMapError={setRouteMapError} />
                <MapZoomControls map={routeMap} />
              </div>
            </section>
          </div>
          {activeRoute && <section className="bg-white rounded-xl p-4 border mt-4">
            <h3 className="font-semibold">Traffic conditions along selected route</h3>
            {!trafficEnabled && <p className="text-sm text-slate-600 mt-2">Enable the traffic layer to check recorded, road-segment-linked observations.</p>}
            {trafficEnabled && (trafficLoading ? <p className="text-sm text-slate-600 mt-2">Loading observations…</p> : trafficError ? <p className="text-sm text-amber-800 mt-2">{trafficError}</p> : classifiedRouteSegments.length === 0 ? <p className="text-sm text-slate-600 mt-2">Not enough traffic observations yet</p> : <>
              <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-3 text-sm">
                <p>Low traffic: {trafficDistanceByLevel.low.toFixed(2)} km</p><p>Moderate traffic: {trafficDistanceByLevel.moderate.toFixed(2)} km</p><p>Heavy traffic: {trafficDistanceByLevel.heavy.toFixed(2)} km</p><p>Data coverage: {trafficCoveragePercent.toFixed(1)}%</p>
              </div>
              <p className="text-xs text-slate-500 mt-2">Last observation: {lastRouteObservation ? new Date(lastRouteObservation).toLocaleString() : 'Unavailable'}. Categories use source-recorded congestion labels only.</p>
            </>)}
          </section>}
          {result && <div className="text-xs text-slate-500 mt-3 bg-white border rounded-lg p-3">Route source: OSRM road network. Map: Google Maps. {result.traffic_note}</div>}
        </>}
        {(tab === 'dashboard' || tab === 'analytics') && <section className="bg-white rounded-xl p-6 border">
          <h2 className="font-bold text-xl">{tab === 'dashboard' ? 'India traffic data' : 'Traffic analytics'}</h2>
          <p className="text-sm text-slate-600 mt-2">Statistics use imported source-reported observations only. Route durations and emissions grids are not traffic observations or live traffic measurements.</p>
          {statsError && <p className="text-sm text-amber-800 mt-3">{statsError}</p>}
          {!trafficStats && !statsError && <p className="text-sm text-slate-500 mt-3">Loading recorded observations…</p>}
          {trafficStats && <>
            {trafficStats.observation_count === 0 && <p className="mt-4 rounded-lg bg-slate-50 p-4 text-sm font-medium text-slate-700">No traffic observations available</p>}
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
              <div className="rounded-lg bg-slate-50 p-4"><p className="text-xs text-slate-500">TRAFFIC OBSERVATIONS</p><p className="text-2xl font-bold mt-1">{trafficStats.observation_count.toLocaleString()}</p></div>
              <div className="rounded-lg bg-slate-50 p-4"><p className="text-xs text-slate-500">COVERED AREAS</p><p className="text-2xl font-bold mt-1">{trafficStats.covered_area_count.toLocaleString()}</p></div>
              <div className="rounded-lg bg-slate-50 p-4"><p className="text-xs text-slate-500">AVERAGE RECORDED SPEED</p><p className="text-2xl font-bold mt-1">{formatRouteNumber(trafficStats.average_recorded_speed_kmh, 1)}{trafficStats.average_recorded_speed_kmh == null ? '' : ' km/h'}</p></div>
              <div className="rounded-lg bg-slate-50 p-4"><p className="text-xs text-slate-500">AVERAGE VEHICLE COUNT</p><p className="text-2xl font-bold mt-1">{formatRouteNumber(trafficStats.average_recorded_vehicle_count, 1)}</p></div>
            </div>
            <p className="text-xs text-slate-500 mt-3">Observation period: {trafficStats.date_range.start ? new Date(trafficStats.date_range.start).toLocaleString() : 'Unavailable'} – {trafficStats.date_range.end ? new Date(trafficStats.date_range.end).toLocaleString() : 'Unavailable'}</p>
            <div className="mt-5"><h3 className="font-semibold text-sm">Registered data sources</h3>{trafficStats.sources.length === 0 ? <p className="text-sm text-slate-500 mt-2">No dataset sources registered.</p> : <ul className="mt-2 divide-y">{trafficStats.sources.map(source => <li key={source.source_name} className="py-3 text-sm"><div className="flex flex-wrap gap-2 items-center"><span className="font-medium">{source.source_name}</span><span className="rounded-full bg-slate-100 px-2 py-1 text-[10px]">{source.data_type || 'unclassified'}</span></div><p className="text-xs text-slate-500 mt-1">{source.city_coverage || 'Coverage unspecified'} · {source.collection_period || 'Collection period unspecified'} · {source.license || 'License unspecified'}</p>{source.source_url && <a className="text-xs text-cyan-700 underline" href={source.source_url} target="_blank" rel="noreferrer">Source</a>}{source.notes && <p className="text-xs text-slate-600 mt-1">{source.notes}</p>}</li>)}</ul>}</div>
          </>}
        </section>}
        {tab === 'analytics' && <section className="hti-panel">
          <div className="hti-panel-heading"><div><p className="hti-eyebrow">DATABASE AGGREGATES</p><h2>Area and hourly analytics</h2><p className="hti-muted">Only observations marked actual or historical are included. GPS journey samples are excluded.</p></div>
            <select value={analyticsArea} onChange={event => setAnalyticsArea(event.target.value)} aria-label="Select analytics area" className="border rounded-lg px-3 py-2">{analyticsAreas.map(item => <option key={item.area} value={item.area}>{item.area}</option>)}</select>
          </div>
          {analyticsError && <p className="hti-data-notice"><AlertCircle size={17} />{analyticsError}</p>}
          {hourlyAnalytics && hourlyAnalytics.sample_count >= 10 && Object.values(hourlyAnalytics.hourly_data).filter(value => value?.avg_speed !== null && value?.avg_speed !== undefined).length >= 3
            ? <div className="hti-chart"><HourlySpeedChart data={Object.entries(hourlyAnalytics.hourly_data).map(([hour, values]) => ({ hour, speed: values?.avg_speed ?? undefined, samples: values?.sample_count ?? 0 }))} /><p className="hti-muted">30-day hourly averages · {hourlyAnalytics.sample_count} qualifying observations · recorded measurements, not predictions</p></div>
            : <div className="hti-empty-state"><Activity size={24} /><strong>Insufficient traffic data for a trend</strong><span>At least 10 qualifying observations across 3 or more hours are required to draw this trend.</span></div>}
          <h3 className="hti-subheading">Area summaries</h3>
          {analyticsAreas.length === 0 && !analyticsError && <p className="hti-muted">Loading area summaries…</p>}
          <div className="hti-area-table"><div className="hti-area-table-head"><span>Area</span><span>Observations</span><span>Average speed</span><span>Average journey time</span><span>Status</span></div>
            {analyticsAreas.map(item => <div key={item.area} className="hti-area-table-row"><strong>{item.area}</strong><span>{item.sample_count.toLocaleString()}</span><span>{item.avg_speed === null ? 'Unavailable' : `${item.avg_speed} km/h`}</span><span>{item.avg_travel_time === null ? 'Unavailable' : `${item.avg_travel_time} min`}</span><span>{item.sample_count ? item.data_status : 'Insufficient data'}</span></div>)}
          </div>
        </section>}
        {tab === 'predictions' && <TrafficPrediction />}
        {tab === 'gps' && <GpsContribution />}
      </main>
      </div>

    </div>
  )
}
