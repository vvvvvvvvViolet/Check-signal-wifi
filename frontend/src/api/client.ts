// Thin fetch wrapper. Errors carry the backend's `detail` message so screens
// can show something better than "request failed".

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join('; ')
    } catch {
      // A non-JSON error body is not worth failing over; keep the status line.
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function withQuery(path: string, params?: Record<string, unknown>): string {
  if (!params) return path
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `${path}?${qs}` : path
}

export const api = {
  get: <T>(path: string, params?: Record<string, unknown>) => request<T>(withQuery(path, params)),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
  /** Build a download URL; the browser fetches it directly so the file streams. */
  downloadUrl: (path: string, params?: Record<string, unknown>) => withQuery(path, params),
}

/** WebSocket URL for the live monitor, matching the page's scheme and host. */
export function monitorSocketUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/monitor/ws`
}
