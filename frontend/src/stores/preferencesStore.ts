import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Lang = 'ko' | 'en'

export type SubtitleStyle = 'plain' | 'outline' | 'glow' | 'background'

// 학생 오디오 모드 — 한국어 원본 (WebRTC) / 영어 TTS 두 가지만 지원.
// 'off' 제거 (사운드 슬라이더 0 으로 대체). de/es/ru 는 실제 작동 안 했어서 제거.
export type AudioLang = 'original' | 'en'

// 학생 자막 언어 — NMT 가 한→영 만 지원하므로 의미 있는 값만.
// 'off' 는 자막 끄기. 'ko' = 한국어 원본, 'en' = 영어 번역.
export type SubtitleLang = 'off' | 'ko' | 'en'

// 하위 호환 — 기존 코드/Lecturer.tsx 의 LecturerLang 등과 별개로,
// 외부에서 generic union 으로 참조하는 경우만 폴백용으로 유지.
export type TranslationLang = AudioLang | SubtitleLang

export type AspectRatio = '16/9' | '4/3' | '5/3'

export type Theme = 'light' | 'dark' | 'gradient'

export interface SubtitleSettings {
  fontSize: number
  position: 'top' | 'bottom'
  opacity: number
  style: SubtitleStyle
  subtitleBgOpacity: number
}

interface PreferencesState {
  lang: Lang
  setLang: (lang: Lang) => void

  subtitleSettings: SubtitleSettings
  setSubtitleSettings: (settings: Partial<SubtitleSettings>) => void
  resetSubtitleSettings: () => void

  audioLang: AudioLang
  subtitleLang: SubtitleLang
  secondarySubtitleLang: SubtitleLang
  setAudioLang: (lang: AudioLang) => void
  setSubtitleLang: (lang: SubtitleLang) => void
  setSecondarySubtitleLang: (lang: SubtitleLang) => void

  aspectRatio: AspectRatio
  setAspectRatio: (ratio: AspectRatio) => void

  lecturerName: string
  setLecturerName: (name: string) => void

  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

const DEFAULT_SUBTITLE_SETTINGS: SubtitleSettings = {
  fontSize: 18,
  position: 'bottom',
  opacity: 0.9,
  style: 'outline',
  subtitleBgOpacity: 0.8,
}

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      lang: 'en',
      setLang: (lang) => set({ lang }),

      subtitleSettings: DEFAULT_SUBTITLE_SETTINGS,
      setSubtitleSettings: (settings) =>
        set((state) => ({
          subtitleSettings: { ...state.subtitleSettings, ...settings },
        })),
      resetSubtitleSettings: () =>
        set({ subtitleSettings: DEFAULT_SUBTITLE_SETTINGS }),

      audioLang: 'en',
      subtitleLang: 'en',
      secondarySubtitleLang: 'ko',
      setAudioLang: (lang) => set({ audioLang: lang }),
      setSubtitleLang: (lang) => set({ subtitleLang: lang }),
      setSecondarySubtitleLang: (lang) => set({ secondarySubtitleLang: lang }),

      aspectRatio: '4/3',
      setAspectRatio: (ratio) => set({ aspectRatio: ratio }),

      lecturerName: '',
      setLecturerName: (name) => set({ lecturerName: name }),

      theme: 'light',
      setTheme: (theme) => set({ theme }),
      toggleTheme: () =>
        set((state) => {
          const next: Theme =
            state.theme === 'light'
              ? 'dark'
              : state.theme === 'dark'
                ? 'gradient'
                : 'light'
          return { theme: next }
        }),
    }),
    {
      name: 'aunion-preferences',
      version: 10,
      migrate: (persistedState, version) => {
        if (!persistedState) return persistedState as unknown as PreferencesState
        const state = persistedState as Partial<PreferencesState>
        if (version < 9) {
          // v9: 기본 UI 언어를 영어로 변경. 기존에 저장된 lang 값은 무시하고 'en'으로 리셋.
          state.lang = 'en'
        }
        if (version < 10) {
          // v10: audioLang/subtitleLang/secondarySubtitleLang 가짜 옵션 (de/es/ru/both/off-for-audio) 제거.
          // localStorage 의 무효 값 → 안전한 기본값으로 정규화. 'off' 는 subtitle 에선 유효.
          const validAudio = state.audioLang === 'original' || state.audioLang === 'en'
          if (!validAudio) state.audioLang = 'en'

          const validSub = (v: unknown) => v === 'off' || v === 'ko' || v === 'en'
          if (!validSub(state.subtitleLang)) state.subtitleLang = 'en'
          if (!validSub(state.secondarySubtitleLang)) state.secondarySubtitleLang = 'ko'
        }
        return state as PreferencesState
      },
    }
  )
)
