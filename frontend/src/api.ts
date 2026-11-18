const configuredApiUrl = import.meta.env.VITE_API_URL?.trim()
export const API_BASE_URL = (configuredApiUrl || '/api').replace(/\/+$/, '')

/** Send API calls through the same-origin proxy in development/Docker, or directly to a deployed API. */
export function apiFetch(path: string | URL, init?: RequestInit): Promise<Response> {
  const pathname = String(path).replace(/^\/api(?=\/|$)/, '')
  return fetch(`${API_BASE_URL}${pathname}`, init)
}
