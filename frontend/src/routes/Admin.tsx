import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function Admin() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Governance"
        title="Administration"
        description="Users and roles, sovereign-mode toggle, and the health panel showing which matching engine is active in each tier."
      />
      <MilestonePending
        what="User management and the sovereign toggle need the auth layer; the health panel renders live capability data."
        milestone="M7"
      />
    </div>
  )
}
