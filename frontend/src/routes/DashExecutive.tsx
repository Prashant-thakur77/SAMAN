import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function DashExecutive() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Analytics"
        title="Executive dashboard"
        description="Harmonization progress across CPSEs: items, clusters, confirmed duplicates, CNMCs issued, automation rate and identified savings."
      />
      <MilestonePending
        what="Every figure here reconciles with /api/metrics and is computed from the database."
        milestone="M5"
      />
    </div>
  )
}
