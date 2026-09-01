import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Backend origin for the dev proxy. Keeps the browser same-origin so the
// session cookie works without CORS credentials juggling.
const API_TARGET = process.env.VITE_API_BASE ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
