import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function Onboard() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Tools"
        title="Onboard a CPSE"
        description="Upload a catalogue, map its columns, review a dry-run of rows accepted and rejected, then ingest and run the pipeline."
      />
      <MilestonePending
        what="The wizard writes real rows through the ingest endpoint."
        milestone="M7"
      />
    </div>
  )
}
