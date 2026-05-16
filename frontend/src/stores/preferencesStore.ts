import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Lang = 'ko' | 'en'

export type SubtitleStyle = 'plain' | 'outline' | 'glow' | 'background'

export type TranslationLang =
  | 'off'
  | 'original'
  | 'ko'
  | 'en'
  | 'both'
  | 'de'
  | 'es'
  | 'ru'

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

  audioLang: TranslationLang
  subtitleLang: TranslationLang
  secondarySubtitleLang: TranslationLang
  setAudioLang: (lang: TranslationLang) => void
  setSubtitleLang: (lang: TranslationLang) => void
  setSecondarySubtitleLang: (lang: TranslationLang) => void

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
      version: 9,
      migrate: (persistedState, version) => {
        const state = persistedState as Partial<PreferencesState> | undefined
        if (version < 9 && state) {
          // v9: 기본 UI 언어를 영어로 변경. 기존에 저장된 lang 값은 무시하고 'en'으로 리셋.
          return { ...state, lang: 'en' } as PreferencesState
        }
        return state as PreferencesState
      },
    }
  )
)
