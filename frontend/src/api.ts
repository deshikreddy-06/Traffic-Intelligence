const configuredApiUrl = import.meta.env.VITE_API_URL?.trim()
const apiBase = (configuredApiUrl || '/api').replace(/\/+$/, '')
export const API_BASE_URL = apiBase === '/api' || apiBase.endsWith('/api')
  ? apiBase
  : `${apiBase}/api`

/** Send API calls through the same-origin proxy in development/Docker, or directly to a deployed API. */
export function apiFetch(path: string | URL, init?: RequestInit): Promise<Response> {
  const pathname = String(path).replace(/^\/api(?=\/|$)/, '')
  return fetch(`${API_BASE_URL}${pathname}`, init)
}
