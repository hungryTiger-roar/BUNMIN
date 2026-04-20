# Aunion AI

대학교 강의 실시간 번역 서비스.
강의자의 한국어 음성을 영어로 번역하고, 강의 슬라이드를 자동 번역해 수강자에게 제공합니다.

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| Frontend | React + TypeScript + Vite |
| Backend | FastAPI + uvicorn |
| 실시간 통신 | WebSocket |
| AI | faster-whisper, Helsinki-NLP, mms-tts-eng, RapidOCR |
| 데스크탑 (선택) | Electron |

---

## 빠른 시작

### 사전 준비

- Node.js 18+
- Python 3.10+
- 루트와 프론트엔드 의존성 설치

```bash
# 루트 (concurrently, Electron 관련 deps)
npm install

# 프론트엔드
cd frontend && npm install && cd ..
```

- 백엔드 conda 환경

```bash
conda create -n aunion python=3.10
conda activate aunion
pip install -r backend/requirements.txt
```

- `.env` 설정 (`backend/.env` 생성)

```env
ASR_MODEL=ghost613/faster-whisper-large-v3-turbo-korean
NMT_MODEL=Helsinki-NLP/opus-mt-ko-en
TTS_MODEL=facebook/mms-tts-eng
ASR_DEVICE=cuda
NMT_DEVICE=cuda
TTS_DEVICE=cuda
OCR_DEVICE=cuda
```

---

## 실행 방법

### 웹 개발 (팀원 전체)

```bash
# 루트에서 실행 — 프론트엔드(Vite) + 백엔드(FastAPI) 동시 실행
npm run dev
```

브라우저에서 `http://localhost:3000` 접속

### Electron 개발

```bash
npm run electron:dev
```

### Electron 빌드 (배포용 exe)

```bash
# 백엔드 먼저 빌드
cd backend && pyinstaller aunion.spec && cd ..

# Electron 패키징
npm run electron:build
```

결과물: `setup/` 폴더에 NSIS 인스톨러 생성

---

## 프로젝트 구조

```
S14P31S205/
├── package.json              # 루트 스크립트 (dev, electron:dev, electron:build)
├── electron-builder.json     # Electron 빌드 설정
│
├── frontend/                 # React 웹앱
│   ├── electron/             # Electron 메인 프로세스
│   └── src/                  # React 소스
│
├── backend/                  # FastAPI 서버
│   ├── app/                  # 라우터 + 서비스
│   ├── evaluation/           # AI 모델 평가 스크립트
│   └── run.py                # 진입점
│
└── docs/                     # 문서
    ├── setting/              # 환경설정, 실행방법
    ├── planning/             # 설계 문서
    └── evaluation/           # 평가 시스템
```

---

## 문서

| 문서 | 내용 |
|------|------|
| [실행방법](docs/setting/실행방법.md) | 웹/Electron 실행 상세 가이드 |
| [환경설정](docs/setting/환경설정.md) | .env 및 AI 모델 설정 |
| [백엔드 설계](docs/planning/백엔드_설계.md) | API 명세, AI 파이프라인 |
| [프론트 설계](docs/planning/프론트_설계.md) | 화면 구성, 디렉토리 구조 |
| [평가 시스템](docs/evaluation/평가시스템.md) | AI 모델 품질/속도 평가 |
