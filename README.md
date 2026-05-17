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
| AI (백엔드) | ASR (Whisper turbo CT2), NMT (NLLB-200), Qwen3-VL-4B (슬라이드 번역), Surya OCR |
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

conda 환경 생성(Python 3.11), Python 패키지 설치, AI 모델 다운로드(~10GB — Whisper-turbo 800MB + NLLB-200 600MB + Qwen3-VL-4B 8GB + Surya OCR 500MB)까지 자동으로 처리됩니다.

> **설치 시간**: 약 15~30분 (AI 모델 다운로드 포함, 회선 따라 다름)  
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
NMT_ASR_DEVICE=cuda
OCR_DEVICE=cpu
```

---

## 실행 방법

### 웹 개발 (팀원 전체)

```bash
# 루트에서 실행 — 프론트엔드(Vite) + 백엔드(FastAPI) 동시 실행
npm run dev
```

브라우저에서 `http://localhost:43000` 접속 (백엔드는 48000)

### Electron 개발

```bash
npm run electron:dev
```

### Electron 빌드 (배포용 setup.exe)

```bash
# 통합 빌드 — backend PyInstaller + frontend Vite + electron-builder + Inno Setup
npm run build:installer
```

결과물: `setup/Aunion-AI-Setup-<version>.exe` (Inno Setup 인스톨러). 본체 ~3.5GB, 첫 실행 시 VLM(Qwen3-VL-4B ~8GB) 자동 다운로드 마법사가 뜸. 자세한 빌드 절차는 [Electron-설치파일-생성방법](docs/setting/Electron-설치파일-생성방법.md) 참고.

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
