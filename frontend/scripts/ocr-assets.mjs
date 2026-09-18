// Copies the OCR engine the Scan screen runs in the browser into public/ocr,
// where the page serves it from its own origin. Nothing is fetched from the
// internet at runtime: the worker and the WebAssembly core come from the
// installed packages (Apache-2.0), and the English model sits in the
// repository beside them, already compressed.
//
// Run on `npm install` (postinstall) so a clone works in development and in
// the image build alike. The copied files are ignored by git; the model is not.

import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const out = join(root, 'public', 'ocr')
mkdirSync(out, { recursive: true })

const FILES = [
  ['tesseract.js/dist/worker.min.js', 'worker.min.js'],
  // The SIMD build for every current phone and laptop browser, and the plain
  // build the engine falls back to where SIMD is unavailable.
  ['tesseract.js-core/tesseract-core-simd-lstm.wasm.js', 'tesseract-core-simd-lstm.wasm.js'],
  ['tesseract.js-core/tesseract-core-simd-lstm.wasm', 'tesseract-core-simd-lstm.wasm'],
  ['tesseract.js-core/tesseract-core-lstm.wasm.js', 'tesseract-core-lstm.wasm.js'],
  ['tesseract.js-core/tesseract-core-lstm.wasm', 'tesseract-core-lstm.wasm'],
]

let copied = 0
for (const [from, to] of FILES) {
  const source = join(root, 'node_modules', from)
  if (!existsSync(source)) {
    console.warn(`ocr-assets: ${from} is not installed; the browser OCR engine will be absent`)
    continue
  }
  copyFileSync(source, join(out, to))
  copied += 1
}
if (!existsSync(join(out, 'eng.traineddata.gz'))) {
  console.warn('ocr-assets: public/ocr/eng.traineddata.gz is missing; the browser OCR engine will be absent')
}
console.log(`ocr-assets: ${copied} engine files in public/ocr`)
