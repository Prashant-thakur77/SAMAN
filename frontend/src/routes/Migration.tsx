import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function Migration() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Tools"
        title="ERP migration"
        description="Plan, dry-run and apply CNMC cross-references into the ERP master, holding any record with open transactions — and roll a batch back exactly."
      />
      <MilestonePending
        what="Migration runs against a mock SAP-shaped ERP with a full before-image journal."
        milestone="M7.5"
      />
    </div>
  )
}
