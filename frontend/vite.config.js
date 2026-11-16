import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: proxy /api to FastAPI. Build: output into backend/static so one application
// host serves both the SPA and the API (Allocation View, Architecture Design 6.3).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
  build: { outDir: '../backend/static', emptyOutDir: true },
})
