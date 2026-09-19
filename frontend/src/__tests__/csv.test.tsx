/**
 * CSV export: what the screen showed, safely quoted, with formulas defused.
 */
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { csvCell, rowsToCsv, tableToCsv } from '../lib/csv'

describe('csv cells', () => {
  it('quotes commas, quotes and newlines', () => {
    expect(csvCell('a,b')).toBe('"a,b"')
    expect(csvCell('say "hi"')).toBe('"say ""hi"""')
    expect(csvCell('two\nlines')).toBe('"two\nlines"')
  })

  it('neutralises a leading formula character', () => {
    expect(csvCell('=SUM(A1)')).toBe("'=SUM(A1)")
    expect(csvCell('+91 98')).toBe("'+91 98")
    expect(csvCell('-5')).toBe("'-5")
  })

  it('leaves plain values and numbers alone', () => {
    expect(csvCell('BRG 6205 2Z')).toBe('BRG 6205 2Z')
    expect(csvCell(42)).toBe('42')
    expect(csvCell(null)).toBe('')
  })
})

describe('rows to csv', () => {
  it('writes a header from the union of keys and one line per row', () => {
    const csv = rowsToCsv([
      { code: 'CPCL001', qty: 3 },
      { code: 'IOCL002', qty: 1, note: 'idle' },
    ])
    expect(csv.split('\r\n')).toEqual(['code,qty,note', 'CPCL001,3,', 'IOCL002,1,idle'])
  })
})

describe('table to csv', () => {
  it('reads the rendered header and body cells', () => {
    const { container } = render(
      <table>
        <thead>
          <tr>
            <th>Code</th>
            <th>Description</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>CPCL001</td>
            <td>
              BEARING, <span>6205</span> 2Z
            </td>
          </tr>
        </tbody>
      </table>,
    )
    const table = container.querySelector('table') as HTMLTableElement
    expect(tableToCsv(table)).toBe('Code,Description\r\nCPCL001,"BEARING, 6205 2Z"')
  })
})
