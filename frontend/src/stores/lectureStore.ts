import { create } from 'zustand'

interface Subtitle {
  id: string
  original: string
  translated: string
  timestamp: number
  inputTime?: number  // 오디오 전송 시각 (ms)
}

interface SlidePage {
  pageNumber: number
  imageUrl: string
  ocrText?: string
}

interface LectureState {
  // 수강자 이름
  studentName: string
  setStudentName: (name: string) => void

  // 현재 접속 중인 수강자 수 (서버가 student_count 메시지를 보낼 때 갱신)
  studentCount: number
  setStudentCount: (count: number) => void

  // 연결 상태
  isConnected: boolean
  setConnected: (connected: boolean) => void

  // 강의자 상태
  isMicOn: boolean
  isLectureStarted: boolean
  isPaused: boolean
  presentationMode: 'slide' | 'screen'
  currentScreen: string | null

  setMicOn: (on: boolean) => void
  setLectureStarted: (started: boolean) => void
  setPaused: (paused: boolean) => void
  setPresentationMode: (mode: 'slide' | 'screen') => void
  setCurrentScreen: (screen: string | null) => void

  // 슬라이드 상태
  slideId: string | null
  slideStatus: 'none' | 'uploading' | 'processing' | 'ready'
  currentPage: number
  totalPages: number
  slidePages: SlidePage[]

  setSlideId: (id: string | null) => void
  setSlideStatus: (status: 'none' | 'uploading' | 'processing' | 'ready') => void
  setCurrentPage: (page: number) => void
  setTotalPages: (total: number) => void
  setSlidePages: (pages: SlidePage[]) => void
  nextPage: () => void
  prevPage: () => void

  // 수강자 상태
  viewMode: 'original' | 'translated'
  isAudioOn: boolean
  isSubtitleOn: boolean

  setViewMode: (mode: 'original' | 'translated') => void
  setAudioOn: (on: boolean) => void
  setSubtitleOn: (on: boolean) => void

  // 자막 설정 (커스터마이징)
  subtitleSettings: {
    fontSize: number
    position: 'top' | 'bottom'
    opacity: number
  }
  setSubtitleSettings: (settings: Partial<LectureState['subtitleSettings']>) => void

  // 실시간 데이터
  subtitles: Subtitle[]

  addSubtitle: (subtitle: Omit<Subtitle, 'id'>) => void
  clearSubtitles: () => void

  // 전체 초기화
  reset: () => void
}

const initialState = {
  studentName: '',
  studentCount: 0,
  isConnected: false,
  isMicOn: false,
  isLectureStarted: false,
  isPaused: false,
  presentationMode: 'slide' as const,
  currentScreen: null as string | null,
  slideId: null,
  slideStatus: 'none' as const,
  currentPage: 1,
  totalPages: 0,
  slidePages: [],
  viewMode: 'original' as const,
  isAudioOn: true,
  isSubtitleOn: true,
  subtitleSettings: {
    fontSize: 18,
    position: 'bottom' as const,
    opacity: 0.9,
  },
  subtitles: [],
}

export const useLectureStore = create<LectureState>((set, get) => ({
  ...initialState,

  // 수강자 이름
  setStudentName: (name) => set({ studentName: name }),
  setStudentCount: (count) => set({ studentCount: count }),

  // 연결 상태
  setConnected: (connected) => set({ isConnected: connected }),

  // 강의자 상태
  setMicOn: (on) => set({ isMicOn: on }),
  setLectureStarted: (started) => set({ isLectureStarted: started }),
  setPaused: (paused) => set({ isPaused: paused }),
  setPresentationMode: (mode) => set({ presentationMode: mode }),
  setCurrentScreen: (screen) => set({ currentScreen: screen }),

  // 슬라이드 상태
  setSlideId: (id) => set({ slideId: id }),
  setSlideStatus: (status) => set({ slideStatus: status }),
  setCurrentPage: (page) => set({ currentPage: page }),
  setTotalPages: (total) => set({ totalPages: total }),
  setSlidePages: (pages) => set({ slidePages: pages, totalPages: pages.length }),

  nextPage: () => {
    const { currentPage, totalPages } = get()
    if (currentPage < totalPages) {
      set({ currentPage: currentPage + 1 })
    }
  },

  prevPage: () => {
    const { currentPage } = get()
    if (currentPage > 1) {
      set({ currentPage: currentPage - 1 })
    }
  },

  // 수강자 상태
  setViewMode: (mode) => set({ viewMode: mode }),
  setAudioOn: (on) => set({ isAudioOn: on }),
  setSubtitleOn: (on) => set({ isSubtitleOn: on }),

  // 자막 설정
  setSubtitleSettings: (settings) => set((state) => ({
    subtitleSettings: { ...state.subtitleSettings, ...settings }
  })),

  // 실시간 데이터
  addSubtitle: (subtitle) => set((state) => ({
    subtitles: [
      ...state.subtitles.slice(-50), // 최근 50개만 유지
      { ...subtitle, id: crypto.randomUUID() }
    ]
  })),
  clearSubtitles: () => set({ subtitles: [] }),

  // 전체 초기화
  reset: () => set(initialState),
}))
