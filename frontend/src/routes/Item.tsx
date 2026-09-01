import { useParams } from 'react-router-dom'

import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function Item() {
  const { id } = useParams<{ id: string }>()
  return (
    <div className="space-y-8">
      <PageHeader
        section="Catalogue"
        title={`Item ${id ?? ''}`}
        description="Golden record, CNMC, every CPSE's legacy code, attribute grid, match evidence, consolidated stock and purchase history."
      />
      <MilestonePending
        what="Item detail is assembled from the golden record and its cluster members."
        milestone="M3.4"
      />
    </div>
  )
}
