import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API and the WebSocket are proxied so `npm run dev` talks to the local
// FastAPI service without CORS or a hard-coded origin in the client.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
