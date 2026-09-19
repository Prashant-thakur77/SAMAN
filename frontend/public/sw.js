/*
 * SAMAN's service worker: the Scan screen on a phone in a store with no signal.
 *
 * What it caches and how, stated so nobody has to read the code to know:
 *   - the app shell and its hashed assets: cached on first use, served from
 *     cache when the network is away (network first for the shell itself, so
 *     an update wins whenever there is a connection);
 *   - the browser OCR engine under /ocr/ (about 15 MB): fetched once into the
 *     cache when the worker installs, so a nameplate can be read offline;
 *   - nothing under /api/: catalogue answers are never served stale from a
 *     cache. Offline lookups fail honestly; the page keeps its own list of
 *     recent scans and queues stock counts for when the signal returns.
 */
const VERSION = 'saman-sw-v1'
const SHELL = ['/', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png']
const OCR = [
  '/ocr/worker.min.js',
  '/ocr/tesseract-core-simd-lstm.wasm.js',
  '/ocr/tesseract-core-simd-lstm.wasm',
  '/ocr/tesseract-core-lstm.wasm.js',
  '/ocr/tesseract-core-lstm.wasm',
  '/ocr/eng.traineddata.gz',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION).then(async (cache) => {
      await cache.addAll(SHELL)
      // Best effort: a phone on a thin link still installs without the engine.
      await Promise.allSettled(OCR.map((url) => cache.add(url)))
    }),
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return // never cached, never faked

  if (request.mode === 'navigate') {
    // The shell: network first, cached copy when the network is away.
    // A host mid-restart answers 502/503: the cached shell and its cached
    // assets are a working application, which a bad gateway page is not.
    event.respondWith(
      fetch(request)
        .then(async (response) => {
          if (!response.ok) return (await caches.match('/')) || response
          const copy = response.clone()
          caches.open(VERSION).then((cache) => cache.put('/', copy))
          return response
        })
        .catch(() => caches.match('/')),
    )
    return
  }

  if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/ocr/') || url.pathname.startsWith('/icons/')) {
    // Hashed or versioned files: cache first, fill on miss.
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone()
              caches.open(VERSION).then((cache) => cache.put(request, copy))
            }
            return response
          }),
      ),
    )
  }
})
