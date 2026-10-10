import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/v1/extractions': { target: 'http://127.0.0.1:8765' } },
    fs: {
      // Keep private model receipts/source data out of the local static server.
      deny: [
        '.env', '.env.*', '*.{crt,pem,key,p12,pfx,cer,der}', '.npmrc', '.yarnrc.yml', '**/.git/**',
        '**/artifacts/**', '**/data/**', '**/tests/fixtures/**',
      ],
    },
  },
})
