import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './app'
import { LangProvider } from './lib/i18n'
import { SessionProvider } from './lib/session'
import { ThemeProvider } from './lib/theme'
import './styles/index.css'

// The service worker makes the Scan screen installable and keeps the shell
// and the OCR engine available in a store with no signal. Production only:
// in development it would cache Vite's modules and hide every edit.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* an old browser or a blocked origin still gets the ordinary page */
    })
  })
}

const root = document.getElementById('root')
if (!root) throw new Error('#root not found in index.html')

createRoot(root).render(
  <StrictMode>
    {/* Opt in early to the v7 behaviours so the upgrade is not a surprise, and
        so the console stays clean enough that a real warning is noticed. */}
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ThemeProvider>
        <LangProvider>
          <SessionProvider>
            <App />
          </SessionProvider>
        </LangProvider>
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>,
)
