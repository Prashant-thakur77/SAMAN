import { MilestonePending } from '../components/MilestonePending'
import { PageHeader } from '../components/PageHeader'

export default function Search() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Overview"
        title="Search"
        description="Search every CPSE catalogue by description, attribute or CNMC. Press ⌘K to open the same search anywhere."
      />
      <MilestonePending
        what="Item search runs against normalized text and extracted attributes."
        milestone="M3"
      />
    </div>
  )
}
