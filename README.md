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
| AI (백엔드) | ASR, NMT, Qwen2.5-VL (슬라이드 번역), Surya OCR |
| TTS (클라이언트) | piper-tts-web — 수강자 브라우저 내 CPU ONNX WASM |
| 데스크탑 (선택) | Electron |

---

## 빠른 시작

### 사전 준비

| 도구 | 버전 |
|------|------|
| Node.js | 18+ |
| conda | Miniconda 또는 Anaconda |
| NVIDIA 드라이버 | CUDA 12.6 호환 (GPU 사용 시) |

### 초기 설치 (최초 1회)

```bash
npm run setup
```

conda 환경 생성(Python 3.11), Python 패키지 설치, AI 모델 다운로드(~17.5GB)까지 자동으로 처리됩니다.

> **설치 시간**: 약 20~40분 (AI 모델 다운로드 포함)  
> **GPU 없는 환경**: 자동으로 CPU 모드로 진행됩니다. 실시간 ASR 성능이 저하될 수 있습니다.

### .env 설정

`npm run setup` 실행 후 `.env`가 자동 생성됩니다. 기본값으로 바로 사용 가능합니다.

```env
# HuggingFace 토큰 (선택사항 — 다운로드 속도 향상)
HF_TOKEN=

ASR_MODEL=models/whisper-large-v3-turbo-ct2-int8
NMT_ASR_MODEL=facebook/nllb-200-distilled-600M
OCR_MODEL=surya

ASR_DEVICE=cuda
NMT_ASR_DEVICE=cpu
OCR_DEVICE=cpu
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
│   └── run.py                # 진입점
│
└── docs/                     # 문서
    ├── setting/              # 환경설정, 실행방법
    └── planning/             # 설계 문서
```

---

## 문서

| 문서 | 내용 |
|------|------|
| [실행방법](docs/setting/실행방법.md) | 웹/Electron 실행 상세 가이드 |
| [환경설정](docs/setting/환경설정.md) | .env 및 AI 모델 설정 |
| [백엔드 설계](docs/planning/백엔드_설계.md) | API 명세, AI 파이프라인 |
| [프론트 설계](docs/planning/프론트_설계.md) | 화면 구성, 디렉토리 구조 |
