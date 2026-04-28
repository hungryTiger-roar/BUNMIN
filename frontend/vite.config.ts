import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import wasm from 'vite-plugin-wasm'
import topLevelAwait from 'vite-plugin-top-level-await'
import path from 'path'
import fs from 'fs'

const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000'
const backendWsUrl = backendUrl.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [
    react(),
    wasm(),
    topLevelAwait(),
    {
      name: 'serve-public-mjs',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url?.startsWith('/ort-wasm-simd-threaded')) {
            const fileName = req.url.split('?')[0].slice(1)
            const filePath = path.resolve(__dirname, 'public', fileName)
            if (fs.existsSync(filePath)) {
              const contentType = fileName.endsWith('.wasm') ? 'application/wasm' : 'text/javascript'
              res.setHeader('Content-Type', contentType)
              fs.createReadStream(filePath).pipe(res as any)
              return
            }
          }
          next()
        })
      },
    },
  ],
  base: './',
  envDir: path.resolve(__dirname, '..'),
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  optimizeDeps: {
    exclude: ['@ricky0123/vad-web', 'onnxruntime-web', 'kokoro-js'],
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
    headers: {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    },
    proxy: {
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
      '/slides': {
        target: backendUrl,
        changeOrigin: true,
      },
      '/health': {
        target: backendUrl,
        changeOrigin: true,
      },
      '/network': {
        target: backendUrl,
        changeOrigin: true,
      },
      '/transcripts': {
        target: backendUrl,
        changeOrigin: true,
      },
      '/ws': {
        target: backendWsUrl,
        ws: true,
      },
    },
  },
})
