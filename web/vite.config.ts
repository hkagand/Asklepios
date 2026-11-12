import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/fhir': process.env.FHIR_SERVER ?? 'http://localhost:8080',
      '/api': process.env.AGENT_SERVER ?? 'http://localhost:8000',
      // The simulated national record service; the web app reads only its simulated phone (/demo/phone).
      '/national': {
        target: process.env.NATIONAL_SERVER ?? 'http://localhost:8090',
        rewrite: (path) => path.replace(/^\/national/, ''),
      },
    },
  },
})
