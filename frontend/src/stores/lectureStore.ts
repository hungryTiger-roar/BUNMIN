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

export interface ChatMessage {
  id: string
  sender: 'lecturer' | 'student'
  name: string
  text: string
  timestamp: number
  studentId?: string
}

export interface Participant {
  id: string
  name: string
}

export interface Participants {
  lecturer: { name: string; connected: boolean } | null
  students: Participant[]
}

type ModelMode = 'idle' | 'slide' | 'switching' | 'realtime'

interface LectureState {
  // AI 모델 모드 상태
  modelMode: ModelMode
  setModelMode: (mode: ModelMode) => void

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

  // 실시간 데이터
  subtitles: Subtitle[]

  addSubtitle: (subtitle: Omit<Subtitle, 'id'>) => void
  clearSubtitles: () => void

  // 채팅
  chatMessages: ChatMessage[]
  addChatMessage: (message: ChatMessage) => void
  clearChatMessages: () => void

  // 참여자
  participants: Participants
  setParticipants: (participants: Participants) => void

  // 강의 제목 (강사가 설정) + 강의자료 파일명 (fallback)
  lectureTitle: string
  slideFilename: string
  setLectureTitle: (title: string) => void
  setSlideFilename: (filename: string) => void

  // 전체 초기화
  reset: () => void
}

const initialState = {
  modelMode: 'idle' as ModelMode,
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
  subtitles: [],
  chatMessages: [] as ChatMessage[],
  participants: { lecturer: null, students: [] } as Participants,
  lectureTitle: '',
  slideFilename: '',
}

export const useLectureStore = create<LectureState>((set, get) => ({
  ...initialState,

  // AI 모델 모드 상태
  setModelMode: (mode) => set({ modelMode: mode }),

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

  // 실시간 데이터
  addSubtitle: (subtitle) => set((state) => ({
    subtitles: [
      ...state.subtitles.slice(-50), // 최근 50개만 유지
      // crypto.randomUUID는 secure context(HTTPS/localhost/file://) 전용 →
      // LAN HTTP로 접속한 수강자에서는 throw되어 자막이 누락됨
      { ...subtitle, id: typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2, 11)}` }
    ]
  })),
  clearSubtitles: () => set({ subtitles: [] }),

  // 채팅
  addChatMessage: (message) => set((state) => ({
    chatMessages: [...state.chatMessages.slice(-200), message],
  })),
  clearChatMessages: () => set({ chatMessages: [] }),

  // 참여자
  setParticipants: (participants) => set({ participants }),

  // 강의 제목
  setLectureTitle: (title) => set({ lectureTitle: title }),
  setSlideFilename: (filename) => set({ slideFilename: filename }),

  // 전체 초기화
  reset: () => set(initialState),
}))
