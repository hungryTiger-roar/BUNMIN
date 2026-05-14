import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import wasm from 'vite-plugin-wasm'
import topLevelAwait from 'vite-plugin-top-level-await'
import path from 'path'
import fs from 'fs'

// Vite proxy target 은 Node.js 가 fetch — Node 17+ 가 'localhost' 를 IPv6 우선 해석해 uvicorn(IPv4)에 ECONNREFUSED.
const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:48000'
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
          const url = req.url?.split('?')[0].slice(1) ?? ''
          const isWasmFile =
            url.startsWith('ort-wasm-simd-threaded') ||
            url.startsWith('onnx/') ||
            url.startsWith('piper/') ||
            url.startsWith('worker/')
          if (isWasmFile) {
            const filePath = path.resolve(__dirname, 'public', url)
            if (fs.existsSync(filePath)) {
              const contentType = url.endsWith('.wasm') ? 'application/wasm' : 'text/javascript'
              res.setHeader('Content-Type', contentType)
              // 같은 출처에서 Worker 가 이 자원을 import 할 때 cross-origin isolation
              // 위반으로 막히지 않도록 CORP 명시. (COEP 는 document-level 이라 여기 X)
              res.setHeader('Cross-Origin-Resource-Policy', 'same-origin')
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
    exclude: ['@ricky0123/vad-web', 'onnxruntime-web', 'piper-tts-web'],
  },
  server: {
    port: 43000,
    host: '0.0.0.0',
    headers: {
      // SharedArrayBuffer 활성화 — threaded onnxruntime-web 동작 필수.
      // `credentialless`: cross-origin 자원(HuggingFace voice 등)을 CORP 없이 받을 수 있음.
      //                   대신 Chromium 계열만 지원. (HF voice 프리페치 정상 동작 확인됨)
      // 미들웨어에서 정적 자원에는 CORP: same-origin 명시 → 워커 내부 fetch 도 통과.
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'credentialless',
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
