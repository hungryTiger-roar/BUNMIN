# Aunion AI

> ## 🎓 대학교 강의 실시간 번역 서비스

- **서비스명**: Aunion AI
- **개발 기간**: 2026.04.06 ~ 2026.05.21
- **개발 인원**: 6명 (AI · Frontend · Backend)

![서비스 데모](https://img.youtube.com/vi/IbezGHkY-hA/0.jpg)](https://youtu.be/IbezGHkY-hA)

<br>

# 목차

- [💡 기획 배경](#-기획-배경)
- [✨ 서비스 주요 기능](#-서비스-주요-기능)
- [🛠️ 프로젝트 핵심 기술](#core-tech)
- [👥 팀원 소개](#-팀원-소개)
- [⚙️ 기술 스택](#tech-stack)

<br>

# 💡 기획 배경

### 대학 강의 현장의 언어 장벽

<table>
  <tr>
    <td align="center" width="25%">🌍<br/><b>외국인 수강생 증가</b><br/><sub>한국어 강의를 따라가지 못해 학습 공백이 생김</sub></td>
    <td align="center" width="25%">📝<br/><b>강의 자료도 한국어</b><br/><sub>슬라이드·판서까지 한국어라 번역본 없이 내용 파악이 어려움</sub></td>
    <td align="center" width="25%">🔇<br/><b>기존 번역 도구의 한계</b><br/><sub>음성·화면·자막이 따로 작동해 동기화가 맞지 않거나 지연이 심함</sub></td>
    <td align="center" width="25%">💸<br/><b>고비용 클라우드 의존</b><br/><sub>외부 서버 전송을 요구해 개인정보 우려 및 비용 발생</sub></td>
  </tr>
</table>

### 현장의 목소리

[![교수님 인터뷰](https://img.youtube.com/vi/YeBRpQnEQjE/0.jpg)](https://youtu.be/YeBRpQnEQjE)

### **✨ 번역의 민족 ✨**

> **강의자는 평소대로 말하고, 수강자는 모국어로 듣는다**

- ⚡ **즉각적인 번역** — 강의자의 발화가 끝나는 즉시 ASR → NMT → TTS 파이프라인으로 영어 음성 제공
- 🖥️ **슬라이드까지 번역** — PDF 업로드만 하면 VLM이 레이아웃을 보존하며 슬라이드 전체를 영어로 변환
- 🔒 **완전 로컬 추론** — 음성·슬라이드 원문이 외부 서버로 전송되지 않고 강사 PC에서만 처리
- 🎯 **4채널 완전 동기화** — 원본 음성·TTS·자막·판서가 같은 박자로 학생에게 도착

<br>

# ✨ 서비스 주요 기능

### 🎤 실시간 음성 번역

- Silero VAD로 발화 단위 감지 → Whisper turbo로 한국어 인식 → NLLB-200으로 영어 번역
- 8초 강제 분할로 최악 지연 20초 이내 보장
- 번역 실패 시 원본 한국어 텍스트로 자동 폴백

### 🔊 영어 TTS (수강자 브라우저 내 합성)

- piper-tts-web(WASM)을 학생 브라우저에서 직접 실행해 백엔드 부하 제거
- 첫 접속 후 IndexedDB에 모델 캐시 → 재접속 시 즉시 로드
- 최대 1.2배속 재생으로 합성 지연 단축

### 📄 슬라이드 자동 번역

- PDF 업로드 → Surya OCR 텍스트 추출 → Qwen3-VL-4B 번역 → 레이아웃 보존 PDF 생성
- 페이지별 재시도·캐시 재사용으로 부분 수정 가능
- 번역 오버레이를 학생 화면에 실시간 반영

### 🖥️ 화면 공유 + 판서 동기화

- WebRTC sendonly로 강사 화면을 학생에게 실시간 전달
- 판서(draw_begin / draw_point / draw_end)·커서·페이지 전환을 동기화된 타이밍으로 재생
- SSAFY 같은 P2P 차단 환경은 내장 TURN 서버가 자동 우회

### ⏱️ 4채널 적응형 동기화

- 원본 음성·TTS·자막·시각 이벤트 4채널이 동일 `currentDelay`로 정렬
- 최근 20번 실측 P90 + jitter 마진으로 2~20초 범위 자동 조정
- 지연이 늘어나면 즉시 증가, 줄어들면 점진적으로 수렴

### 🏠 멀티플레이 강의

- 강사는 Electron 앱 실행, 수강자는 LAN 브라우저 접속으로 별도 설치 불필요
- 여러 수강자 동시 접속 지원, 개인별 음성·자막·언어 모드 독립 설정
- 강의 종료 후 5분 grace 동안 자막 파일 다운로드 가능


<br>

<a name="core-tech"></a>

# 🛠️ 프로젝트 핵심 기술

### ⚡ 4채널 적응형 동기화 (Adaptive Sync Delay)

- 강사 원본 음성·영어 TTS·자막·시각 이벤트(판서/페이지/커서) 4채널이 처리 시간이 각기 다름
- 최근 20번 실측값의 P90 + jitter 마진을 `currentDelay`로 산정해 가장 느린 채널에 맞춰 정렬
- 지연 급증 시 즉시 반영, 회복 시 점진적 수렴으로 빨리 감기 현상 방지
- `currentDelay` 범위: 2초(하한) ~ 20초(상한) 자동 조정

### 🔗 WebRTC sendonly + TURN 서버 내장

- 마이크·화면 토글을 PC 재협상 없이 `replaceTrack(null)` swap으로 처리 — 학생 측 오디오 파이프라인 유지
- P2P 우선 시도, 실패 시 내장 TURN 서버(node-turn, UDP+TCP)로 자동 우회
- SSAFY 같은 사내망 P2P 차단 환경에서도 화면 공유·음성 전달 동작

### 🧠 완전 로컬 AI 파이프라인

- Whisper turbo(CTranslate2 int8) → NLLB-200(CT2 int8) → piper-tts-web(WASM) 전 구간 로컬 처리
- 슬라이드 번역: Surya OCR → Qwen3-VL-4B(4bit/8bit 자동 양자화) 로컬 추론
- 음성·슬라이드 원문이 외부 서버로 전송되지 않음 — HuggingFace Hub은 모델 최초 다운로드에만 사용

### 📦 Electron 단일 설치 파일

- PyInstaller로 백엔드 exe 패키징 → electron-builder → Inno Setup으로 setup.exe 생성
- 강사 PC에 설치 시 백엔드·TURN 서버 자동 기동, 수강자는 브라우저만으로 접속
- VRAM 용량에 따라 4bit/8bit 자동 선택으로 6GB 카드도 지원

<br>

# 👥 팀원 소개

<table>
  <tr>
    <td align="center">
      <img src="https://img.shields.io/badge/팀장%20%7C%20Backend%20%7C%20Infra-4285F4?style=for-the-badge&logoColor=white"/>
    </td>
    <td align="center">
      <img src="https://img.shields.io/badge/AI%20%7C%20Frontend-9B59B6?style=for-the-badge&logoColor=white"/>
    </td>
    <td align="center">
      <img src="https://img.shields.io/badge/Frontend%20%7C%20Backend-61DAFB?style=for-the-badge&logoColor=black"/>
    </td>
  </tr>
  <tr>
    <td align="center">
      <!-- GitHub 계정명 확인 후 수정 -->
      <img width="130" src="https://github.com/doyoungkim-code.png" /><br/>
      <a href="https://github.com/doyoungkim-code">김도영</a>
    </td>
    <td align="center">
      <img width="130" src="https://github.com/tkdgns11.png" /><br/>
      <a href="https://github.com/tkdgns11">윤상훈</a>
    </td>
    <td align="center">
      <img width="130" src="https://github.com/gkdud112837.png" /><br/>
      <a href="https://github.com/gkdud112837">이하영</a>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="https://img.shields.io/badge/AI%20%7C%20Backend-4285F4?style=for-the-badge&logoColor=white"/>
    </td>
    <td align="center">
      <img src="https://img.shields.io/badge/Frontend%20%7C%20Backend-61DAFB?style=for-the-badge&logoColor=black"/>
    </td>
    <td align="center">
      <img src="https://img.shields.io/badge/AI%20%7C%20Backend-4285F4?style=for-the-badge&logoColor=white"/>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img width="130" src="https://github.com/JinYunSe.png" /><br/>
      <a href="https://github.com/JinYunSe">진윤세</a>
    </td>
    <td align="center">
      <img width="130" src="https://github.com/hungryTiger-roar.png" /><br/>
      <a href="https://github.com/hungryTiger-roar">한민지</a>
    </td>
    <td align="center">
      <img width="130" src="https://github.com/s00cong.png" /><br/>
      <a href="https://github.com/s00cong">황수빈</a>
    </td>
  </tr>
</table>

<br>

<a name="tech-stack"></a>

# ⚙️ 기술 스택

### AI / Backend

<div>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/Whisper-412991?style=for-the-badge&logo=openai&logoColor=white"/>
  <img src="https://img.shields.io/badge/NLLB--200-0467DF?style=for-the-badge&logo=meta&logoColor=white"/>
  <img src="https://img.shields.io/badge/Qwen3--VL-FF6A00?style=for-the-badge&logoColor=white"/>
</div>

### Frontend / Client

<div>
  <img src="https://img.shields.io/badge/React-61DAFB?style=for-the-badge&logo=react&logoColor=black"/>
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white"/>
  <img src="https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white"/>
  <img src="https://img.shields.io/badge/Electron-47848F?style=for-the-badge&logo=electron&logoColor=white"/>
  <img src="https://img.shields.io/badge/piper--tts--web-FF9900?style=for-the-badge&logoColor=white"/>
</div>

### 실시간 통신

<div>
  <img src="https://img.shields.io/badge/WebSocket-010101?style=for-the-badge&logo=socketdotio&logoColor=white"/>
  <img src="https://img.shields.io/badge/WebRTC-333333?style=for-the-badge&logo=webrtc&logoColor=white"/>
</div>

### Cooperation

<div>
  <a href="https://lab.ssafy.com/s14-final/S14P31S205.git"><img src="https://img.shields.io/badge/GitLab-FC6D26?style=for-the-badge&logo=gitlab&logoColor=white"/></a>
  <a href="https://ssafy.atlassian.net/jira/software/c/projects/S14P31S205/boards/13217"><img src="https://img.shields.io/badge/Jira-0052CC?style=for-the-badge&logo=jira&logoColor=white"/></a>
  <a href="https://app.notion.com/p/33ab3290c140808e824ef4654709e538?source=copy_link"><img src="https://img.shields.io/badge/Notion-000000?style=for-the-badge&logo=notion&logoColor=white"/></a>
</div>

<br>

