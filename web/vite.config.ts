import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/fhir': process.env.FHIR_SERVER ?? 'http://localhost:8080',
      '/api': process.env.AGENT_SERVER ?? 'http://localhost:8000',
    },
  },
})
