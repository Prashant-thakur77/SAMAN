import { Link } from 'react-router-dom'

import type { ItemCard } from '../../lib/api'
import { CodeChip, StatusChip } from '../primitives/Chip'

/** One side of a workbench comparison, or one member of a cluster. */
export function ItemPanel({ item, side }: { item: ItemCard; side?: string }) {
  return (
    <div className="min-w-0 space-y-3 border border-hairline p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {side && <p className="micro-label">{side}</p>}
          <p className="micro-label mt-1">{item.cpse}</p>
        </div>
        <CodeChip code={item.legacy_code} />
      </div>

      <p className="break-words text-sm text-ink">{item.description}</p>
      <p className="break-words font-mono text-xs text-muted">{item.normalized}</p>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {item.mpn_norm && (
          <>
            <dt className="text-muted">MPN</dt>
            <dd className="font-mono">{item.mpn_norm}</dd>
          </>
        )}
        {item.gtin && (
          <>
            <dt className="text-muted">GTIN</dt>
            <dd className="font-mono">{item.gtin}</dd>
          </>
        )}
        {item.plant && (
          <>
            <dt className="text-muted">Plant</dt>
            <dd>{item.plant}</dd>
          </>
        )}
        {item.pack_qty > 1 && (
          <>
            <dt className="text-muted">Pack</dt>
            <dd>
              {item.pack_qty} × {item.uom_base ?? 'EA'}
            </dd>
          </>
        )}
      </dl>

      <div className="flex flex-wrap items-center gap-3 pt-1">
        {item.class_uncertain ? (
          <StatusChip tone="danger">Class uncertain: anchor keys only</StatusChip>
        ) : (
          <StatusChip tone="neutral">{item.class_code}</StatusChip>
        )}
        {item.cluster_id && (
          <Link
            to={`/clusters/${item.cluster_id}`}
            className="text-xs text-muted underline underline-offset-2 hover:text-ink"
          >
            cluster {item.cluster_id}
          </Link>
        )}
      </div>
    </div>
  )
}
