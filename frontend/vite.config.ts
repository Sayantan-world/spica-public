import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  envDir: "..",
  server: {
    host: "0.0.0.0",
    port: 5001,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      "/health": "http://127.0.0.1:5002",
      "/account": "http://127.0.0.1:5002",
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 5001,
    strictPort: true,
    allowedHosts: true,
  },
})
