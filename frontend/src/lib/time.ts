/**
 * The API's timestamps are UTC. Some carry a zone marker ("+00:00" or "Z"),
 * the ones read straight from SQLite do not; both must parse as UTC, never
 * as the browser's local time.
 */
export function parseUtc(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
}
