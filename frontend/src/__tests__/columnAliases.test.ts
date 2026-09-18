/**
 * The onboarding wizard pre-fills its column map from the header row. It
 * matched only SAMAN's own field names, so a genuine SAP extract — MATNR,
 * MAKTX, MEINS, WERKS, MAP, LABST — showed "not present" for every field and
 * the required ones had to be picked by hand. The guess must be the API's guess.
 */

import { describe, expect, it } from 'vitest'

import { guessMapping } from '../lib/columnAliases'

describe('guessing the column map from a header row', () => {
  it('reads an SAP extract the way the API does', () => {
    expect(guessMapping(['MATNR', 'MAKTX', 'MEINS', 'WERKS', 'MAP', 'LABST'])).toEqual({
      legacy_code: 'MATNR',
      description: 'MAKTX',
      uom: 'MEINS',
      plant: 'WERKS',
      price: 'MAP',
      qty_on_hand: 'LABST',
    })
  })

  it('accepts spaces, hyphens and underscores as one spelling', () => {
    expect(guessMapping(['Material-No', 'Short_Text', 'Base UOM'])).toEqual({
      legacy_code: 'Material-No',
      description: 'Short_Text',
      uom: 'Base UOM',
    })
  })

  it('never assigns one header to two fields', () => {
    // "material" is a code alias; it must not also be taken for description.
    const guess = guessMapping(['material', 'desc'])
    expect(guess).toEqual({ legacy_code: 'material', description: 'desc' })
  })

  it('leaves unknown headers unmapped rather than guessing', () => {
    expect(guessMapping(['foo', 'bar'])).toEqual({})
  })
})
