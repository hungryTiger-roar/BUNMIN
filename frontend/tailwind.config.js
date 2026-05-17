/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      backgroundImage: {
        'home-gradient': 'linear-gradient(to right, var(--color-gradient-blue) 0%, var(--color-gradient-purple) 25%, var(--color-gradient-blue) 50%, var(--color-gradient-purple) 75%, var(--color-gradient-blue) 100%)',
      },

      keyframes: {
        'gradient-shift': {
          '0%': { backgroundPosition: '100% 50%' },
          '100%': { backgroundPosition: '0% 50%' },
        },
      },
      animation: {
        'gradient-shift': 'gradient-shift 15s linear infinite',
      },
      colors: {
        // Theme.kt의 ColorScheme 역할
        primary: "var(--color-primary)",
        secondary: "var(--color-secondary)",
        tertiary: "var(--color-tertiary)",
        primaryContainer: "var(--color-primary-container)",
        background: "var(--color-background)",
        onBackground: "var(--color-on-background)",
        surface: "var(--color-surface)",
        onSurface: "var(--color-on-surface)",
        onPrimary: "var(--color-on-primary)",
        error: "var(--color-error)",

        // 그라데이션 위에 띄우는 패널용 (ParticipantsPanel, 언어선택 팝업 등)
        overlaySurface: "var(--color-overlay-surface)",
        onOverlaySurface: "var(--color-on-overlay-surface)",
        overlayBorder: "var(--color-overlay-border)",

        // Gradient Colors (포인트 컬러)
        gradientBlue: "var(--color-gradient-blue)",
        gradientPurple: "var(--color-gradient-purple)",

        // 채팅 강사 강조색 (라이트/그라데이션=진한 보라, 다크=흰색)
        lecturerAccent: "var(--color-lecturer-accent)",

        // Color.kt에 정의된 기타 정적 색상 (다크모드 영향 안 받는 색상들)
        findId: "var(--color-find-id)",
        purple80: "#D0BCFF",
        purpleGrey80: "#CCC2DC",
        pink80: "#EFB8C8",
        purple40: "#6650a4",
        purpleGrey40: "#625b71",
        pink40: "#7D5260",

        // 첫 페이지 브랜드 보라 — '번역의' 텍스트, '강의 참여' 버튼, 검색창 테두리 공통
        bunmin: "#624de3"
      },
      fontFamily: {
        sans: ['"paybooc"', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        allimjang: ['"Hakgyoansim Allimjang"', 'sans-serif'],
        'special-gothic': ['"Special Gothic Expanded One"', 'sans-serif'],
        'a2z': ['"A2z"', 'sans-serif'],
        'eland': ['"ELAND Naise"', '"Hakgyoansim Allimjang"', 'sans-serif'],
      },
      fontSize: {
        // Type.kt의 Typography 역할
        bodyLarge: ['16px', {
          lineHeight: '24px',
          fontWeight: '400', // Normal
          letterSpacing: '0.5px'
        }],
      }
    },
  },
  plugins: [],
} 