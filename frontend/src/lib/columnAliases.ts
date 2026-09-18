/**
 * Header spellings seen in real CPSE extracts, mapped onto SAMAN's fields.
 *
 * This is the same table as `COLUMN_ALIASES` in backend/app/routers/ingest.py,
 * and `guessMapping` is the same rule as `guess_mapping` there: the onboarding
 * wizard shows its guess *before* the file is sent, so the two have to agree or
 * the mapping screen contradicts the dry run that follows it. Keep them in step.
 */
export const COLUMN_ALIASES: Record<string, readonly string[]> = {
  legacy_code: [
    'legacy_code', 'material_code', 'material', 'matnr', 'code', 'item_code',
    'material number', 'material no', 'sap code', 'part code',
  ],
  description: [
    'description', 'material_description', 'desc', 'maktx', 'item_description',
    'long text', 'short text', 'material text',
  ],
  uom: ['uom', 'unit', 'unit_of_measure', 'meins', 'base uom', 'uom_code'],
  plant: ['plant', 'werks', 'location', 'site', 'store'],
  price: ['price', 'unit_price', 'rate', 'value', 'moving average price', 'map'],
  qty_on_hand: ['qty_on_hand', 'qty', 'quantity', 'stock', 'on_hand', 'labst'],
}

const norm = (s: string) => s.trim().toLowerCase().replace(/-/g, ' ').replace(/_/g, ' ')

/** Field → header, for every field one of the headers is a known spelling of. */
export function guessMapping(headers: string[]): Record<string, string> {
  const mapping: Record<string, string> = {}
  const taken = new Set<string>()
  for (const [field, aliases] of Object.entries(COLUMN_ALIASES)) {
    const wanted = new Set(aliases.map(norm))
    const hit = headers.find((h) => !taken.has(h) && wanted.has(norm(h)))
    if (hit) {
      mapping[field] = hit
      taken.add(hit)
    }
  }
  return mapping
}
