/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly BACKEND_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  electron?: {
    notifyReady: () => void
    onBackendReady: (callback: (ready: boolean) => void) => void
    onBackendLog: (callback: (log: string) => void) => void
  }
}
