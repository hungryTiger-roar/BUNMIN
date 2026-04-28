/// <reference types="vite/client" />

interface ModelEntry {
  status: 'pending' | 'loading' | 'done' | 'error' | 'skipped'
  progress: number
  label: string
  desc: string
}

interface ModelMap {
  asr: ModelEntry
  nmt_asr: ModelEntry
  tts: ModelEntry
  ocr: ModelEntry
  vlm: ModelEntry
}

interface BackendState {
  progress: number
  models: ModelMap | null
  ready: boolean | null
}

interface Window {
  electron?: {
    onBackendReady: (callback: (ready: boolean) => void) => void
    onBackendLog: (callback: (log: string) => void) => void
    onBackendProgress: (callback: (progress: number) => void) => void
    onBackendModelStatus: (callback: (models: ModelMap) => void) => void
    getLanIp: () => Promise<string>
    getBackendState: () => Promise<BackendState>
  }
}
