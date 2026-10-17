import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiBase = env.VITE_API_URL || env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      // Dev-mode proxy: forwards /api/* and /health to the local FastAPI backend
      proxy: {
        '/api': { target: apiBase, changeOrigin: true },
        '/health': { target: apiBase, changeOrigin: true },
        '/demo-target': { target: apiBase, changeOrigin: true },
        '/docs': { target: apiBase, changeOrigin: true },
      },
    },
    build: {
      // Ensures Vite output ends up in frontend/dist (default, but explicit)
      outDir: 'dist',
    },
  }
})
