import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
      host:true,
      allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8082',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:8082',
        changeOrigin: true,
      },
      '/users': {
        target: 'http://localhost:8082',
        changeOrigin: true,
      },
    },
  },
  build: {
    // Output to backend's static directory for production serving
    outDir: '../backend/src/orpheus_ui/static',
    emptyOutDir: true,
  },
})
