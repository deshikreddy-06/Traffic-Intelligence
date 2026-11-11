import os
path = r'c:\Users\HOME\Downloads\Major Project\frontend\src\App.tsx'
code = '''import { useState, useEffect } from 'react'
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet'
import { Car, Route, BarChart3, Brain, RefreshCw } from 'lucide-react'
import L from 'leaflet'

const HYDERABAD_CENTER: [number, number] = [17.3850, 78.4867]

function MapUpdater({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap()
  map.setView(center, zoom)
  return null
}

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [routes, setRoutes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [areas, setAreas] = useState([])

  useEffect(() => {
    fetch('/api/areas')
      .then(res => res.json())
      .then(data => setAreas(data))
      .catch(() => {})
  }, [])

  const handleCompareRoutes = async () => {
    if (!origin || !destination) return
    setLoading(true)
    try {
      const res = await fetch('/api/routes/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin, destination })
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed')
      setRoutes(data)
      setSelectedRouteId(data.routes.find((r: any) => r.is_fastest)?.route_id || null)
    } catch (e: any) {
      alert(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      <header className="bg-primary-700 text-white px-6 py-4 shadow-lg">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Car className="w-8 h-8" />
            <div>
              <h1 className="text-2xl font-bold">Hyderabad Traffic Intelligence</h1>
              <p className="text-primary-100 text-sm">AI-Based Smart Traffic Prediction & Route Optimization</p>
            </div>
          </div>
        </div>
      </header>

      <nav className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex gap-6">
            {['dashboard', 'routes', 'analytics', 'predictions'].map(tab => (
              <button key={tab} onClick={() => setActiveTab(tab)} className={`flex items-center gap-2 py-4 px-2 border-b-2 font-medium text-sm transition-colors ${activeTab === tab ? 'border-primary-500 text-primary-600' : 'border-transparent text-gray-500'}`}>
                {tab === 'dashboard' && <BarChart3 className="w-4 h-4" />}
                {tab === 'routes' && <Route className="w-4 h-4" />}
                {tab === 'analytics' && <BarChart3 className="w-4 h-4" />}
                {tab === 'predictions' && <Brain className="w-4 h-4" />}
                {tab}
              </button>
            ))}
          </div>
        </div>
      </nav>

      <main className="flex-1 overflow-auto p-6">
        <div className="max-w-7xl mx-auto">
          <div className="h-[500px] bg-white rounded-xl shadow-sm border p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Hyderabad Map</h2>
              <span className="text-sm text-gray-500">Interactive map showing supported areas</span>
            </div>
            <div className="h-[400px]">
              <MapContainer center={HYDERABAD_CENTER} zoom={12} className="h-full">
                <TileLayer attribution='&copy; OpenStreetMap' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                <Marker position={[17.4435, 78.3772]}><Popup>Hitech City</Popup></Marker>
                <Marker position={[17.4489, 78.3918]}><Popup>Madhapur</Popup></Marker>
                <Marker position={[17.4401, 78.3489]}><Popup>Gachibowli</Popup></Marker>
                <Marker position={[17.4633, 78.3738]}><Popup>Kondapur</Popup></Marker>
                <Marker position={[17.4941, 78.4036]}><Popup>Kukatpally</Popup></Marker>
              </MapContainer>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
'''
with open(path, 'w', encoding='utf-8') as f:
    f.write(code)
print('App.tsx written')
