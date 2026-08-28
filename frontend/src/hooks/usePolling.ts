import { useCallback, useEffect, useRef, useState } from 'react'

interface Options {
  /** Milliseconds between refreshes. Omit or pass 0 to fetch once. */
  intervalMs?: number
  enabled?: boolean
}

interface State<T> {
  data: T | null
  error: string | null
  loading: boolean
  refresh: () => Promise<void>
}

/**
 * Fetch on mount and optionally on an interval.
 *
 * Two things this gets right that a naive useEffect does not: an in-flight
 * request is never allowed to overwrite state after the component unmounts,
 * and a slow request cannot be overtaken by a newer one - stale responses are
 * discarded rather than flickering older data back onto the screen.
 */
export function usePolling<T>(fetcher: () => Promise<T>, options: Options = {}): State<T> {
  const { intervalMs = 0, enabled = true } = options
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const mounted = useRef(true)
  const requestId = useRef(0)

  const refresh = useCallback(async () => {
    const id = ++requestId.current
    try {
      const result = await fetcherRef.current()
      if (!mounted.current || id !== requestId.current) return
      setData(result)
      setError(null)
    } catch (err) {
      if (!mounted.current || id !== requestId.current) return
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (mounted.current && id === requestId.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    if (!enabled) {
      setLoading(false)
      return () => {
        mounted.current = false
      }
    }
    void refresh()
    if (intervalMs > 0) {
      const timer = window.setInterval(() => void refresh(), intervalMs)
      return () => {
        mounted.current = false
        window.clearInterval(timer)
      }
    }
    return () => {
      mounted.current = false
    }
  }, [refresh, intervalMs, enabled])

  return { data, error, loading, refresh }
}
