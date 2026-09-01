import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './app'
import { ThemeProvider } from './lib/theme'
import './styles/index.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root not found in index.html')

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>,
)
