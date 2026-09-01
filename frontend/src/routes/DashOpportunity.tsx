import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function DashOpportunity() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Analytics"
        title="Opportunity"
        description="Joint-tender candidates from 12-month purchase history, price variance per base unit, and cross-CPSE inventory sharing with dead-stock value."
      />
      <MilestonePending
        what="Savings are derived from seeded purchase history and stock, with the discount assumption stated inline."
        milestone="M5"
      />
    </div>
  )
}
