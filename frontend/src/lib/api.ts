/**
 * Thin fetch wrapper for the SAMAN API.
 *
 * Same-origin in dev via the Vite proxy (see vite.config.ts), so the session
 * cookie rides along with `credentials: 'include'`. No third-party client.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      ...init,
    })
  } catch (cause) {
    // Backend down or unreachable — surface it as a normal API failure so the
    // UI can render an empty state instead of a blank screen.
    throw new ApiError(0, 'Cannot reach the SAMAN backend.', cause)
  }

  const body = res.headers.get('content-type')?.includes('application/json')
    ? await res.json().catch(() => null)
    : null

  if (!res.ok) {
    const message =
      (body && typeof body === 'object' && 'detail' in body && String(body.detail)) ||
      `${res.status} ${res.statusText}`
    throw new ApiError(res.status, message, body)
  }
  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) }),
}

// ---- typed shapes for endpoints that exist today (M1) ----

export type TierHealth = { mode: string; engine: string; degraded: boolean }

export type Health = {
  status: string
  app: string
  long_name: string
  version: string
  offline: boolean
  capabilities: {
    linkage: TierHealth
    embedding: TierHealth
    llm: TierHealth
    sovereign_mode: boolean
    degraded: string[]
  }
}

export const getHealth = () => api.get<Health>('/health')
