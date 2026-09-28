/**
 * A request the host answers while the API is waking is sent again; one the
 * API itself refuses is not.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../lib/api'

const text = (status: number) =>
  new Response('Too Many Requests', { status, headers: { 'content-type': 'text/plain' } })
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

describe('a waking host', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('retries a request the host answered with 429, then succeeds', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(text(429))
      .mockResolvedValueOnce(text(502))
      .mockResolvedValueOnce(json(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    const result = api.post<{ ok: boolean }>('/auth/demo-login', { email: 'a@b' })
    await vi.advanceTimersByTimeAsync(3100)
    await expect(result).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it("never retries SAMAN's own 429, the sign-in throttle", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(429, { detail: 'Too many failed sign-ins.' }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.post('/auth/login', {})).rejects.toMatchObject({ status: 429 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('gives up after about half a minute and says what the host said', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => text(503))
    vi.stubGlobal('fetch', fetchMock)
    const result = api.get('/health').catch((err: unknown) => err)
    await vi.advanceTimersByTimeAsync(31000)
    const err = await result
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(503)
    expect(fetchMock).toHaveBeenCalledTimes(6)
  })

  it('does not retry an unreachable network, so offline mode hears at once', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.get('/health')).rejects.toMatchObject({ status: 0 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
