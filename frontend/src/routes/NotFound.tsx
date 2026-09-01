import { Link } from 'react-router-dom'

import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/primitives/Button'
import { EmptyState } from '../components/primitives/EmptyState'

export default function NotFound() {
  return (
    <div className="space-y-8">
      <PageHeader
        section="Error"
        title="Page not found"
        description="That route does not exist in SAMAN."
      />
      <EmptyState
        title="No such page"
        description="Check the address, or press ⌘K to jump to any screen."
        action={
          <Link to="/">
            <Button variant="primary">Back to home</Button>
          </Link>
        }
      />
    </div>
  )
}
