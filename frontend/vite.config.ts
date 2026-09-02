import react from '@vitejs/plugin-react'
import path from 'node:path'
/// <reference types="vitest" />
import { defineConfig, type Plugin } from 'vite'

/**
 * Restart the dev server when tailwind.config.js changes.
 *
 * Vite reloads CSS on edit but caches the Tailwind config, so a new colour or
 * shadow token added to the config leaves a long-running `make dev` serving a
 * 500 for index.css ("The `ring-accent` class does not exist") and a blank
 * page, with nothing in the terminal to say why. Twice in one day was enough.
 */
function restartOnTailwindConfig(): Plugin {
  const target = path.resolve(__dirname, 'tailwind.config.js')
  return {
    name: 'saman:restart-on-tailwind-config',
    configureServer(server) {
      server.watcher.add(target)
      server.watcher.on('change', (file) => {
        if (path.resolve(file) === target) {
          server.config.logger.info('tailwind.config.js changed, restarting dev server')
          void server.restart()
        }
      })
    },
  }
}

// Backend origin for the dev proxy. Keeps the browser same-origin so the
// session cookie works without CORS credentials juggling.
const API_TARGET = process.env.VITE_API_BASE ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), restartOnTailwindConfig()],
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
