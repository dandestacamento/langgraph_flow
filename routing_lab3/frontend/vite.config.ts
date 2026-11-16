import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Proxies browser calls to /api/* to the FastAPI backend (app/api/main.py),
      // avoiding CORS configuration during local development.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
    // Playwright's own tests live in e2e/ and run via `npm run test:e2e`,
    // not vitest - exclude them so `npm run test` only runs unit/component tests.
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
