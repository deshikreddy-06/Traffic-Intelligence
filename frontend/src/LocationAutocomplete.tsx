import { useEffect, useRef, useState } from 'react'
import type { ReactNode, KeyboardEvent } from 'react'
import { Building2, Bus, GraduationCap, HeartPulse, Landmark, Loader2, MapPin, Plane, ShoppingBag, Train, Utensils, X } from 'lucide-react'

export interface SelectedLocation {
  placeId: string
  name: string
  formattedAddress: string
  latitude: number
  longitude: number
  placeType?: string
  city?: string | null
  district?: string | null
  state?: string | null
}

interface LocationSuggestion extends SelectedLocation {
  categories: string[]
}

interface AutocompleteResponse {
  results?: Array<{
    place_id: string
    name: string
    formatted_address: string
    latitude: number
    longitude: number
    place_type?: string
    categories?: string[]
    city?: string | null
    district?: string | null
    state?: string | null
  }>
  message?: string | null
}

interface LocationAutocompleteProps {
  label: string
  value: string
  placeholder: string
  onChange: (value: string) => void
  onSelect: (place: SelectedLocation | null) => void
  action?: ReactNode
}

function suggestionIcon(suggestion: LocationSuggestion) {
  const types = [suggestion.placeType || '', ...suggestion.categories].map(type => type.toLowerCase())
  if (types.some(type => /hospital|doctor|medical|pharmacy|healthcare/.test(type))) return HeartPulse
  if (types.some(type => /school|university|college|education/.test(type))) return GraduationCap
  if (types.some(type => /bus_station|bus\.station|train_station|railway|transit/.test(type))) return types.some(type => /bus/.test(type)) ? Bus : Train
  if (types.some(type => /airport|aerodrome/.test(type))) return Plane
  if (types.some(type => /shopping|commercial\.mall/.test(type))) return ShoppingBag
  if (types.some(type => /tourism|tourist|temple|attraction|heritage|museum|place_of_worship/.test(type))) return Landmark
  if (types.some(type => /restaurant|cafe|food/.test(type))) return Utensils
  if (types.some(type => /locality|district|state|administrative|city|village|town/.test(type))) return Building2
  return MapPin
}

export function LocationAutocomplete({ label, value, placeholder, onChange, onSelect, action }: LocationAutocompleteProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const newestRequestRef = useRef(0)
  const lastRequestedQueryRef = useRef('')
  const [suggestions, setSuggestions] = useState<LocationSuggestion[]>([])
  const [focused, setFocused] = useState(false)
  const [loading, setLoading] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [error, setError] = useState('')

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setFocused(false)
        setActiveIndex(-1)
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [])

  useEffect(() => {
    const query = value.trim()
    const requestId = ++newestRequestRef.current
    if (!focused) {
      setLoading(false)
      setActiveIndex(-1)
      return
    }
    if (query.length < 3) {
      setSuggestions([])
      setLoading(false)
      setError('')
      setActiveIndex(-1)
      if (query.length < 3) lastRequestedQueryRef.current = ''
      return
    }

    const normalizedQuery = query.toLocaleLowerCase('en-IN')
    if (lastRequestedQueryRef.current === normalizedQuery) return
    const controller = new AbortController()
    let requestFinished = false
    setLoading(true)
    const timer = window.setTimeout(async () => {
      lastRequestedQueryRef.current = normalizedQuery
      setError('')
      try {
        const response = await fetch(`/api/locations/autocomplete?text=${encodeURIComponent(query)}`, { signal: controller.signal })
        const body = await response.json() as AutocompleteResponse & { detail?: string }
        if (!response.ok) {
          const statusMessage = response.status === 429 || response.status === 503
            ? 'Location search is busy. Please try again in a moment.'
            : response.status >= 500
              ? 'Location search is temporarily unavailable. Please try again.'
              : body.detail || 'Location search could not be completed.'
          throw new Error(statusMessage)
        }
        if (requestId !== newestRequestRef.current) return
        const rows = Array.isArray(body.results) ? body.results : []
        setSuggestions(rows.filter(item => item && Number.isFinite(item.latitude) && Number.isFinite(item.longitude) && typeof item.name === 'string' && typeof item.formatted_address === 'string').map(item => ({
          placeId: item.place_id,
          name: item.name,
          formattedAddress: item.formatted_address,
          latitude: item.latitude,
          longitude: item.longitude,
          placeType: item.place_type,
          categories: Array.isArray(item.categories) ? item.categories : [],
          city: item.city,
          district: item.district,
          state: item.state,
        })))
        setActiveIndex(-1)
      } catch (failure) {
        if (controller.signal.aborted || requestId !== newestRequestRef.current) return
        lastRequestedQueryRef.current = ''
        setSuggestions([])
        setError(failure instanceof Error ? failure.message : 'Location search is temporarily unavailable.')
      } finally {
        requestFinished = true
        if (!controller.signal.aborted && requestId === newestRequestRef.current) setLoading(false)
      }
    }, 450)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
      if (!requestFinished && lastRequestedQueryRef.current === normalizedQuery) lastRequestedQueryRef.current = ''
    }
  }, [value, focused])

  const selectSuggestion = (suggestion: LocationSuggestion) => {
    const { categories: _categories, ...selectedPlace } = suggestion
    onChange(suggestion.formattedAddress)
    onSelect(selectedPlace)
    setSuggestions([])
    setFocused(false)
    setActiveIndex(-1)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' && suggestions.length) {
      event.preventDefault()
      setActiveIndex(index => (index + 1) % suggestions.length)
    } else if (event.key === 'ArrowUp' && suggestions.length) {
      event.preventDefault()
      setActiveIndex(index => (index <= 0 ? suggestions.length - 1 : index - 1))
    } else if (event.key === 'Escape') {
      setFocused(false)
      setActiveIndex(-1)
    } else if (event.key === 'Enter' && activeIndex >= 0 && suggestions[activeIndex]) {
      event.preventDefault()
      selectSuggestion(suggestions[activeIndex])
    }
  }

  const showDropdown = focused && value.trim().length >= 3
  const listboxId = `${label.toLowerCase().replace(/\s+/g, '-')}-suggestions`

  return <div ref={rootRef} className="hti-place-autocomplete">
    <div className="hti-place-label-row">
      <label className="block text-xs font-semibold text-slate-500 mb-1">{label}</label>
      {action}
    </div>
    <div className="hti-input-with-clear">
      <input
        value={value}
        onChange={event => { onChange(event.target.value); onSelect(null); setError('') }}
        onFocus={() => setFocused(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        className="w-full border rounded-lg px-3 py-3 outline-cyan-600"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={showDropdown}
        aria-controls={listboxId}
      />
      <button type="button" onClick={() => { onChange(''); onSelect(null); setSuggestions([]); setError('') }} aria-label={`Clear ${label.toLowerCase()}`}>
        {loading ? <Loader2 size={15} className="animate-spin" /> : <X size={15} />}
      </button>
    </div>
    {showDropdown && <div className="hti-place-suggestions" id={listboxId} role="listbox" aria-label={`${label} suggestions`}>
      {loading && <div className="hti-place-message"><Loader2 size={15} className="animate-spin" />Searching places across India…</div>}
      {!loading && error && <div className="hti-place-message error" role="status">{error}</div>}
      {!loading && !error && suggestions.length === 0 && <div className="hti-place-message">No matching places in India. Try a different spelling or nearby landmark.</div>}
      {!loading && !error && suggestions.map((suggestion, index) => {
        const Icon = suggestionIcon(suggestion)
        const locality = [suggestion.city, suggestion.district, suggestion.state].filter(Boolean).join(', ')
        return <button
          type="button"
          role="option"
          aria-selected={index === activeIndex}
          className={`hti-place-option ${index === activeIndex ? 'active' : ''}`}
          key={`${suggestion.placeId}-${index}`}
          onPointerDown={event => event.preventDefault()}
          onClick={() => selectSuggestion(suggestion)}
        >
          <span className="hti-place-icon"><Icon size={17} /></span>
          <span className="hti-place-copy"><strong>{suggestion.name}</strong><small>{suggestion.formattedAddress}</small>{locality && locality !== suggestion.formattedAddress && <small>{locality}</small>}</span>
        </button>
      })}
      <div className="hti-place-attribution">Powered by Geoapify</div>
    </div>}
  </div>
}
