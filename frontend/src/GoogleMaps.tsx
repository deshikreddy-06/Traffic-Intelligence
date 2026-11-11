import { useEffect, useRef, useState } from 'react'

const API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY?.trim()
const AUTH_FAILURE_EVENT = 'hti-google-maps-auth-failure'
const API_SCRIPT_ID = 'hti-google-maps-javascript-api'

let mapsApiPromise: Promise<void> | null = null

type MapsWindow = Window & {
  google?: typeof google
  gm_authFailure?: () => void
}

type RoutesLibrary = { Route: typeof google.maps.routes.Route }
function loadGoogleMapsApi(): Promise<void> {
  const browserWindow = window as MapsWindow
  if (browserWindow.google?.maps?.Map && typeof (browserWindow.google.maps as unknown as { importLibrary?: unknown }).importLibrary === 'function') return Promise.resolve()
  if (!API_KEY) return Promise.reject(new Error('Google Maps is not configured. Add VITE_GOOGLE_MAPS_API_KEY to frontend/.env.local, then restart the frontend.'))
  if (mapsApiPromise) return mapsApiPromise
  if (browserWindow.google?.maps?.Map) return Promise.reject(new Error('Google Maps was loaded in legacy mode. Refresh the page to load the Routes library.'))

  const googleNamespace = (browserWindow.google ??= {} as typeof google)
  const mapsNamespace = (googleNamespace.maps ??= {} as typeof google.maps)
  const loaderMaps = mapsNamespace as typeof google.maps & { __ib__?: () => void }
  const requestedLibraries = new Set<string>()
  let scriptPromise: Promise<void> | null = null
  const loadScript = () => scriptPromise ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.id = API_SCRIPT_ID
    script.async = true
    script.defer = true
    const parameters = new URLSearchParams({ key: API_KEY, v: 'weekly', callback: 'google.maps.__ib__', libraries: [...requestedLibraries].join(',') })
    script.src = `https://maps.googleapis.com/maps/api/js?${parameters}`
    loaderMaps.__ib__ = resolve
    script.onerror = () => reject(new Error('Google Maps could not load. Check your connection, API key, and Maps JavaScript API access.'))
    browserWindow.gm_authFailure = () => window.dispatchEvent(new Event(AUTH_FAILURE_EVENT))
    document.head.appendChild(script)
  })

  if (typeof (mapsNamespace as unknown as { importLibrary?: unknown }).importLibrary !== 'function') {
    mapsNamespace.importLibrary = ((libraryName: string) => {
      requestedLibraries.add(libraryName)
      return loadScript().then(() => mapsNamespace.importLibrary(libraryName as never))
    }) as typeof google.maps.importLibrary
  }

  mapsApiPromise = mapsNamespace.importLibrary('maps').then(() => undefined).catch((failure: unknown) => {
    mapsApiPromise = null
    throw failure
  })
  return mapsApiPromise
}

export async function loadGoogleRoutesLibrary(): Promise<RoutesLibrary> {
  await loadGoogleMapsApi()
  return await (window as MapsWindow).google!.maps.importLibrary('routes') as RoutesLibrary
}

export const GOOGLE_MAPS_AUTH_FAILURE_EVENT = AUTH_FAILURE_EVENT
export const INDIA_MAP_CENTER: google.maps.LatLngLiteral = { lat: 20.5937, lng: 78.9629 }

const DARK_MAP_STYLES: google.maps.MapTypeStyle[] = [
  { elementType: 'geometry', stylers: [{ color: '#18222e' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#b8c7d8' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#111a24' }] },
  { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: '#455466' }] },
  { featureType: 'landscape', elementType: 'geometry', stylers: [{ color: '#18222e' }] },
  { featureType: 'poi', elementType: 'labels.text.fill', stylers: [{ color: '#a9b9c9' }] },
  { featureType: 'poi.park', elementType: 'geometry', stylers: [{ color: '#1b302d' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#334354' }] },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: [{ color: '#1a2632' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#536b80' }] },
  { featureType: 'road.highway', elementType: 'geometry.stroke', stylers: [{ color: '#293948' }] },
  { featureType: 'road.local', elementType: 'geometry', stylers: [{ color: '#273543' }] },
  { featureType: 'transit.line', elementType: 'geometry', stylers: [{ color: '#405466' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#102b3a' }] },
]

interface GoogleMapsCanvasProps {
  className?: string
  zoom?: number
  onMapReady: (map: google.maps.Map | null) => void
  onMapError?: (message: string) => void
}

export function GoogleMapsCanvas({ className = 'relative h-full w-full', zoom = 5, onMapReady, onMapError }: GoogleMapsCanvasProps) {
  const mapElement = useRef<HTMLDivElement>(null)
  const mapRef = useRef<google.maps.Map | null>(null)
  const onMapReadyRef = useRef(onMapReady)
  const onMapErrorRef = useRef(onMapError)
  const [message, setMessage] = useState(API_KEY ? 'Loading Google Maps…' : 'Google Maps needs an API key.')

  onMapReadyRef.current = onMapReady
  onMapErrorRef.current = onMapError

  useEffect(() => {
    let disposed = false
    let map: google.maps.Map | null = null
    const failAuth = () => {
      const errorMessage = 'Google rejected this API key. Check its website restrictions, billing status, and Maps JavaScript API access.'
      setMessage(errorMessage)
      onMapErrorRef.current?.(errorMessage)
    }
    window.addEventListener(AUTH_FAILURE_EVENT, failAuth)

    if (!API_KEY) {
      const errorMessage = 'Google Maps API key missing. Add VITE_GOOGLE_MAPS_API_KEY to frontend/.env.local, enable Maps JavaScript API, and restart the frontend.'
      setMessage(errorMessage)
      onMapErrorRef.current?.(errorMessage)
    } else {
      void loadGoogleMapsApi().then(() => {
        if (disposed || !mapElement.current || !window.google?.maps) return
        map = new google.maps.Map(mapElement.current, {
          center: INDIA_MAP_CENTER,
          zoom,
          minZoom: 4,
          maxZoom: 21,
          mapTypeId: 'roadmap',
          renderingType: 'RASTER',
          styles: DARK_MAP_STYLES,
          backgroundColor: '#111a24',
          disableDefaultUI: true,
          zoomControl: false,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          scrollwheel: true,
          gestureHandling: 'greedy',
          disableDoubleClickZoom: true,
          clickableIcons: true,
        })
        setMessage('')
        mapRef.current = map
        onMapReadyRef.current(map)
      }).catch((failure: unknown) => {
        if (disposed) return
        const errorMessage = failure instanceof Error ? failure.message : 'Google Maps could not be initialized.'
        setMessage(errorMessage)
        onMapErrorRef.current?.(errorMessage)
      })
    }

    return () => {
      disposed = true
      window.removeEventListener(AUTH_FAILURE_EVENT, failAuth)
      mapRef.current = null
      onMapReadyRef.current(null)
    }
  }, [zoom])

  useEffect(() => {
    const element = mapElement.current
    if (!element) return
    const observer = new ResizeObserver(() => {
      if (!mapRef.current) return
      const center = mapRef.current.getCenter()
      google.maps.event.trigger(mapRef.current, 'resize')
      if (center) mapRef.current.setCenter(center)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return <div className={`${className} overflow-hidden`}>
    <div ref={mapElement} className="hti-google-map h-full w-full" aria-label="Google map of India" />
    {message && <div className="hti-google-map-message" role="status">{message}</div>}
  </div>
}
