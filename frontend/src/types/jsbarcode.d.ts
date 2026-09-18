/**
 * jsbarcode ships no types. Only what the label uses is declared: the default
 * export renders a barcode into an element the caller already holds.
 */
declare module 'jsbarcode' {
  type JsBarcodeOptions = {
    format?: string
    width?: number
    height?: number
    displayValue?: boolean
    margin?: number
    background?: string
    lineColor?: string
    flat?: boolean
  }
  function JsBarcode(
    element: SVGElement | HTMLCanvasElement | HTMLImageElement | string,
    text: string,
    options?: JsBarcodeOptions,
  ): void
  export default JsBarcode
}
