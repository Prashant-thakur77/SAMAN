import { EmptyState } from './primitives/EmptyState'

/**
 * Honest placeholder for a screen whose engine has not been built yet
 * (spec §10: "If something isn't built yet, show an honest empty state" —
 * never invented numbers, never a fake chart).
 *
 * Every use of this component is deleted by the milestone named in `milestone`.
 */
export function MilestonePending({
  what,
  milestone,
}: {
  what: string
  milestone: string
}) {
  return (
    <EmptyState
      title="Nothing to show yet"
      description={`${what} This screen is built in ${milestone}; until then it shows no data rather than placeholder figures.`}
    />
  )
}
