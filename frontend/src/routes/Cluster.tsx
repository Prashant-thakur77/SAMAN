import { useParams } from 'react-router-dom'

import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function Cluster() {
  const { id } = useParams<{ id: string }>()
  return (
    <div className="space-y-8">
      <PageHeader
        section="Review"
        title={`Cluster ${id ?? ''}`}
        description="Every member of the cluster, the proposed golden description with per-field provenance, and split / merge actions."
      />
      <MilestonePending
        what="Clusters are produced by the matching and standardization engines."
        milestone="M4"
      />
    </div>
  )
}
