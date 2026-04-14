import { create } from 'zustand'

interface Subtitle {
  id: string
  original: string
  translated: string
  timestamp: number
}

interface OverlayItem {
  original: string
  translated: string
  bbox: number[]
  confidence: number
}

interface LectureState {
  // 연결 상태
  isConnected: boolean
  setConnected: (connected: boolean) => void

  // 강의자 상태
  isMicOn: boolean
  isScreenSharing: boolean
  slideId: string | null
  slideStatus: 'none' | 'uploading' | 'processing' | 'ready'

  setMicOn: (on: boolean) => void
  setScreenSharing: (sharing: boolean) => void
  setSlideId: (id: string | null) => void
  setSlideStatus: (status: 'none' | 'uploading' | 'processing' | 'ready') => void

  // 수강자 상태
  viewMode: 'original' | 'translated'
  isAudioOn: boolean
  isSubtitleOn: boolean

  setViewMode: (mode: 'original' | 'translated') => void
  setAudioOn: (on: boolean) => void
  setSubtitleOn: (on: boolean) => void

  // 실시간 데이터
  subtitles: Subtitle[]
  overlayItems: OverlayItem[]
  currentScreen: string | null

  addSubtitle: (subtitle: Omit<Subtitle, 'id'>) => void
  setOverlayItems: (items: OverlayItem[]) => void
  setCurrentScreen: (screen: string | null) => void
  clearSubtitles: () => void
}

export const useLectureStore = create<LectureState>((set) => ({
  // 연결 상태
  isConnected: false,
  setConnected: (connected) => set({ isConnected: connected }),

  // 강의자 상태
  isMicOn: false,
  isScreenSharing: false,
  slideId: null,
  slideStatus: 'none',

  setMicOn: (on) => set({ isMicOn: on }),
  setScreenSharing: (sharing) => set({ isScreenSharing: sharing }),
  setSlideId: (id) => set({ slideId: id }),
  setSlideStatus: (status) => set({ slideStatus: status }),

  // 수강자 상태
  viewMode: 'translated',
  isAudioOn: true,
  isSubtitleOn: true,

  setViewMode: (mode) => set({ viewMode: mode }),
  setAudioOn: (on) => set({ isAudioOn: on }),
  setSubtitleOn: (on) => set({ isSubtitleOn: on }),

  // 실시간 데이터
  subtitles: [],
  overlayItems: [],
  currentScreen: null,

  addSubtitle: (subtitle) => set((state) => ({
    subtitles: [
      ...state.subtitles.slice(-50), // 최근 50개만 유지
      { ...subtitle, id: crypto.randomUUID() }
    ]
  })),
  setOverlayItems: (items) => set({ overlayItems: items }),
  setCurrentScreen: (screen) => set({ currentScreen: screen }),
  clearSubtitles: () => set({ subtitles: [] }),
}))
