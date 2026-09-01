/** Tiny class-name joiner. Keeps the bundle lean — no clsx dependency (spec §9). */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}
