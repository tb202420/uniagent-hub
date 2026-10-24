import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式：npm run dev 后代理到本机 Dashboard（18080）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:18080',
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 900,
  },
})
