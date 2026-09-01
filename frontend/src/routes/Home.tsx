import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function Home() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Overview"
        title="Home"
        description="Role-aware landing: registrars see executive KPIs, stewards see their pending review queue."
      />
      <MilestonePending
        what="KPIs are computed from the database, so they appear once the pipeline has run."
        milestone="M5"
      />
    </div>
  )
}
