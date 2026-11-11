/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OSM_TILE_URL?: string
  readonly VITE_OSM_TILE_ATTRIBUTION?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
