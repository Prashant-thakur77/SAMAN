import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function Audit() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Governance"
        title="Audit trail"
        description="Every mutation as a hash-chained event. Verifying the chain re-walks it and reports the sequence number of the first break."
      />
      <MilestonePending
        what="Audit events are written by the decision and migration workflows."
        milestone="M4"
      />
    </div>
  )
}
