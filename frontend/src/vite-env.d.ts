/// <reference types="vite/client" />

// piper-tts-web 타입 선언 (패키지에 .d.ts 미동봉)
// class로 선언하면 type/value 양쪽으로 사용 가능
declare module 'piper-tts-web' {
  export class PiperWebEngine {
    constructor(...args: any[])
    [key: string]: any
  }
  export class OnnxWebRuntime {
    constructor(...args: any[])
    [key: string]: any
  }
  export class PhonemizeWebRuntime {
    constructor(...args: any[])
    [key: string]: any
  }
}

interface ModelEntry {
  status: 'pending' | 'loading' | 'done' | 'error' | 'skipped'
  progress: number
  label: string
  desc: string
}

interface ModelMap {
  asr: ModelEntry
  nmt_asr: ModelEntry
  ocr: ModelEntry
  vlm: ModelEntry
}

interface BackendState {
  progress: number
  models: ModelMap | null
  ready: boolean | null
}

interface ScreenSource {
  id: string
  name: string
  thumbnail: string  // data URL
  appIcon: string | null
  display_id: string
}

interface Window {
  electron?: {
    onBackendReady: (callback: (ready: boolean) => void) => void
    onBackendLog: (callback: (log: string) => void) => void
    onBackendProgress: (callback: (progress: number) => void) => void
    onBackendModelStatus: (callback: (models: ModelMap) => void) => void
    getLanIp: () => Promise<string>
    getBackendState: () => Promise<BackendState>
    getScreenSources: () => Promise<ScreenSource[]>
    quitApp: () => void
    // 윈도우 컨트롤 (자체 타이틀바)
    minimizeWindow: () => void
    toggleMaximizeWindow: () => void
    closeWindow: () => void
    isWindowMaximized: () => Promise<boolean>
    onWindowMaximizedChange: (callback: (maximized: boolean) => void) => () => void
  }
}
