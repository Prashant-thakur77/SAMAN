import '@testing-library/jest-dom/vitest'

// jsdom implements neither, and framer-motion and the virtualiser both ask.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}

if (!window.requestAnimationFrame) {
  window.requestAnimationFrame = (cb: FrameRequestCallback) =>
    window.setTimeout(() => cb(performance.now()), 0)
  window.cancelAnimationFrame = (id: number) => window.clearTimeout(id)
}

// The landing page reveals its sections with framer-motion's `whileInView`,
// which asks for an IntersectionObserver jsdom does not have. Report every
// observed element as visible immediately: a test should assert what the page
// says, never how far down it was scrolled.
if (typeof globalThis.IntersectionObserver === 'undefined') {
  class ImmediateObserver implements IntersectionObserver {
    readonly root = null
    readonly rootMargin = ''
    readonly thresholds: readonly number[] = []
    constructor(private readonly callback: IntersectionObserverCallback) {}
    observe(target: Element) {
      this.callback(
        [{ isIntersecting: true, target } as IntersectionObserverEntry],
        this,
      )
    }
    unobserve() {}
    disconnect() {}
    takeRecords(): IntersectionObserverEntry[] {
      return []
    }
  }
  globalThis.IntersectionObserver =
    ImmediateObserver as unknown as typeof IntersectionObserver
}
