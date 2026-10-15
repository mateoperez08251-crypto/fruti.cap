import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En desarrollo, /api se envía al backend FastAPI. En producción FastAPI sirve dist/.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
})
