import react from '@vitejs/plugin-react'
/// <reference types="vitest" />
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
  // `vite preview` serves the production build; it needs the same proxy so a
  // built bundle can be exercised against a real API (screenshots, smoke runs).
  preview: {
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
    include: ['src/**/*.test.tsx', 'src/**/*.test.ts'],
  },
})
