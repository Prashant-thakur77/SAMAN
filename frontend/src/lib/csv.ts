/**
 * CSV export for whatever is on screen: a rendered table, or a list of plain
 * rows. Done in the browser from the data already fetched, so the export
 * shows exactly what the reader saw — the same visibility bands, the same
 * redactions — and nothing the API would not have given them.
 *
 * Excel opens a UTF-8 file with a BOM correctly, and Hindi descriptions
 * survive it; without the BOM they arrive as mojibake.
 */

const BOM = '﻿'

export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = typeof value === 'object' ? JSON.stringify(value) : String(value)
  // Quote when needed, double the quotes inside; a leading =+-@ is neutralised
  // so a description cannot become a formula when the file is opened.
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

export function rowsToCsv(rows: Record<string, unknown>[], columns?: string[]): string {
  if (rows.length === 0) return ''
  const keys = columns ?? Array.from(new Set(rows.flatMap((r) => Object.keys(r))))
  const lines = [keys.map(csvCell).join(',')]
  for (const row of rows) lines.push(keys.map((k) => csvCell(row[k])).join(','))
  return lines.join('\r\n')
}

/** Header cells and body cells as rendered, whitespace collapsed. */
export function tableToCsv(table: HTMLTableElement): string {
  const text = (cell: Element) => (cell.textContent ?? '').replace(/\s+/g, ' ').trim()
  const lines: string[] = []
  const head = table.querySelector('thead tr')
  if (head) lines.push(Array.from(head.children).map((c) => csvCell(text(c))).join(','))
  for (const tr of Array.from(table.querySelectorAll('tbody tr'))) {
    lines.push(Array.from(tr.children).map((c) => csvCell(text(c))).join(','))
  }
  return lines.join('\r\n')
}

export function downloadCsv(name: string, csv: string): void {
  const stamp = new Date().toISOString().slice(0, 10)
  const blob = new Blob([BOM + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name.replace(/[^a-z0-9_-]+/gi, '-').toLowerCase()}-${stamp}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
