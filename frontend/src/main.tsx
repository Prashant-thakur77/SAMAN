import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './app'
import { SessionProvider } from './lib/session'
import { ThemeProvider } from './lib/theme'
import './styles/index.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root not found in index.html')

createRoot(root).render(
  <StrictMode>
    {/* Opt in early to the v7 behaviours so the upgrade is not a surprise, and
        so the console stays clean enough that a real warning is noticed. */}
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ThemeProvider>
        <SessionProvider>
          <App />
        </SessionProvider>
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>,
)
