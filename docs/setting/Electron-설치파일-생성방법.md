# Electron 설치 파일 생성 방법

`setup/Aunion-AI-Setup-{버전}.exe`를 만드는 빌드 절차. 코드/모델이 업데이트될 때마다 이 문서대로 다시 빌드해 배포본을 갱신.

---

## 결과물 한 줄 요약

```
사용자 PC                              개발자 PC (이 문서)
────────────                           ────────────────
Aunion-AI-Setup-{버전}.exe              아래 3단계 빌드 → setup/Aunion-AI-Setup-{버전}.exe
        │
        └─ 더블클릭 → Inno Setup 마법사 → 설치 → 시작 메뉴 등록
```

---

## 사전 요구사항 (개발자 PC)

| 도구 | 용도 | 설치 방법 |
|---|---|---|
| **Conda 환경 `aunion`** | 백엔드 Python (PyTorch CUDA 등) | `npm run setup` (자동) |
| **Node.js 20+ / npm** | Electron / Vite 빌드 | nodejs.org |
| **NVIDIA GPU + CUDA 12.x 드라이버** | 빌드 자체엔 필수 X, 단 백엔드 동작 검증엔 필요 | nvidia.com |
| **Inno Setup 6** | 설치 파일 컴파일 | `winget install JRSoftware.InnoSetup` |

설치 후 Inno Setup 컴파일러 위치 확인:
```
%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
```

---

## 최종 사용자 PC 요구사항

설치본 받는 일반 사용자 입장에서 따로 깔아야 하는 건 거의 없음 — PyInstaller가 Python+의존성을 통째로 내장하고 Electron이 자체 Node 런타임을 가져옴.

| 항목 | 사용자가 따로 설치? | 설명 |
|---|---|---|
| Python / Conda | ❌ | `aunion_backend.exe`에 Python 3.10 인터프리터 + 모든 패키지 내장 |
| Node.js | ❌ | Electron이 자체 Node 런타임 포함 |
| AI 모델 (NMT/ASR/OCR/VLM-LoRA) | ❌ | 설치본에 동봉 |
| **NVIDIA GPU + CUDA 12.x 드라이버** | ✅ | PyTorch CUDA가 OS의 NVIDIA 드라이버에 의존. RTX 3060 이상 권장 (VRAM ~6GB+) |
| 인터넷 (첫 실행만) | ✅ | VLM Base 16GB HF에서 자동 다운로드 (~30~60분) |

CPU만 있는 PC에선 VLM 슬라이드 번역이 사실상 불가 (분 단위 소요). NVIDIA GPU 미보유 사용자는 미지원으로 안내.

---

## 빌드 절차 (3단계)

### 1️⃣ PyInstaller — 백엔드 exe 번들

```bash
conda run --no-capture-output -n aunion pyinstaller --noconfirm backend/aunion.spec
```

**산출**: `backend/dist/aunion_backend/` (61MB exe + 4.8GB `_internal/` 의존성)

**소요 시간**: ~5분

> 백엔드 코드(Python)나 [aunion.spec](../../backend/aunion.spec)을 수정한 경우에만 다시 돌리면 됨. 프론트엔드만 바꿨으면 스킵 가능.

---

### 2️⃣ electron-builder — Electron 패키징

```bash
npm run electron:build
```

**내부 동작**:
1. `npm run build --prefix frontend` — Vite로 프론트엔드 빌드 → `frontend/dist/`
2. `electron-builder --config electron-builder.json` — Electron + 프론트엔드 + 백엔드 번들 + 모델 동봉 → `setup/win-unpacked/`

**산출**: `setup/win-unpacked/` (약 6.6GB, VLM Base 17GB 미포함)

**소요 시간**: ~5~7분

> 산출물 폴더가 매번 갈아엎어짐. 따라서 PyInstaller 결과 변경 시에는 PyInstaller부터 다시 돌려야 반영.

---

### 3️⃣ Inno Setup — 단일 설치 파일 생성

```bash
"$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe" installer.iss
```

(Bash) — 또는 PowerShell:
```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

**산출**: `setup/Aunion-AI-Setup-{버전}.exe` (약 3.2GB)

**소요 시간**: ~15~20분 (lzma2/max 압축, PyTorch CUDA DLL이 가장 오래)

> 빌드 설정은 [installer.iss](../../installer.iss)에 있음. 버전 변경 시 `MyAppVersion`, VLM 동봉 토글은 `[Files]` 섹션의 `Excludes`로 조정.

---

## VLM Base 동봉 여부 (사이즈 vs 첫 실행 UX 트레이드)

VLM Base(`Qwen/Qwen2.5-VL-7B-Instruct`)는 17GB. 동봉할지에 따라 두 가지 빌드:

| 옵션 | 설치본 크기 | 첫 실행 시 다운로드 | 사용 케이스 |
|---|---|---|---|
| **(A) 동봉** | ~15GB (압축) | 없음 (즉시 사용) | 발표/시연 직전 PC 세팅 |
| **(B) 미동봉** (현재 기본) | ~3.2GB | 16GB HF 다운로드 (30~60분) | 일반 배포 |

### (A)로 빌드하려면

`installer.iss`의 `[Files]` 섹션에서 Excludes 줄을 제거:

```ini
[Files]
; Excludes 라인을 빼면 win-unpacked의 모든 파일이 포함됨 (VLM 포함)
Source: "setup\win-unpacked\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs
```

그리고 단계 2 후에 win-unpacked로 VLM을 직접 복사:

```bash
cp -r models/qwen2.5-vl-7b-instruct setup/win-unpacked/resources/backend/models/
```

이후 단계 3 ISCC 실행. 압축 시간이 ~30~40분으로 늘어남.

> dev 머신에 `models/qwen2.5-vl-7b-instruct/`가 있어야 가능. 없으면 `npm run setup`으로 먼저 받기.

---

## 한 줄 빌드 명령 (전체 체인)

코드와 모델이 모두 갱신된 상황에서 한 번에 끝까지:

```bash
# 1+2+3 한꺼번에 (VLM 미동봉 기본)
cd backend && conda run --no-capture-output -n aunion pyinstaller --noconfirm aunion.spec && cd .. \
  && npm run electron:build \
  && "$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe" installer.iss
```

총 소요 시간: ~25~30분

VLM 동봉본 만들려면 electron:build 뒤에 `cp -r models/qwen2.5-vl-7b-instruct setup/win-unpacked/resources/backend/models/` 한 줄 끼우고 `installer.iss`를 (A) 형태로 수정.

---

## 자주 막히는 지점 (트러블슈팅)

### "Aunion AI.exe: Access is denied" — electron-builder 실패

이전에 켰던 앱이 살아 있어 파일 잠금 발생.

```powershell
$names = @('Aunion AI', 'aunion_backend')
foreach ($n in $names) {
  Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill(); $_.WaitForExit(3000) }
}
```

후 다시 빌드.

### 빌드는 성공했는데 설치본이 마이크/카메라 못 잡음

프론트엔드를 `file://`로 로드하면 Chromium이 secure context로 안 봐서 `getUserMedia`가 차단됨.

[main.cjs](../../frontend/electron/main.cjs)가 백엔드 HTTP(`http://127.0.0.1:8000`) 응답을 기다린 뒤 거기서 frontend를 로드하도록 되어 있음. 백엔드가 늦게 뜨면 한참 빈 창이 뜰 수 있음 — 정상.

### 첫 실행 시 VLM 다운로드가 안 되거나 잘못된 위치로 받음

[backend/app/main.py](../../backend/app/main.py)의 `_vlm_default()`가 다음 순서로 찾음:
1. `%LOCALAPPDATA%/Aunion AI/models/qwen2.5-vl-7b-instruct/` (사용자 데이터)
2. `<install>/resources/backend/models/qwen2.5-vl-7b-instruct/` (동봉본)
3. 없으면 HF repo_id `Qwen/Qwen2.5-VL-7B-Instruct`로 다운로드

다운로드된 모델은 HF 캐시(`%LOCALAPPDATA%/Aunion AI/cache/huggingface/`)에 들어감.

### `silero_vad_v6.onnx: File doesn't exist` (ASR 에러)

`faster_whisper`의 ONNX VAD 파일이 누락. [aunion.spec](../../backend/aunion.spec)에 `collect_data_files('faster_whisper')`가 있는지 확인.

### `translate_slide_v3 모듈 없음`

PyInstaller가 프로젝트 루트의 `translate_slide_v3.py`를 못 찾는 경우. [aunion.spec](../../backend/aunion.spec)의 `pathex`에 `'..'`가 있고 `hiddenimports`에 `'translate_slide_v3'`가 있는지 확인.

### NSIS 설치본 만들고 싶을 때 4GB mmap 에러

NSIS는 32-bit mmap 한계 때문에 4GB+ 페이로드 압축 못 함. 그래서 Inno Setup으로 우회한 것. 다시 NSIS로 가지 말 것.

### `Could not find a declaration file for module 'piper-tts-web'` (TS 빌드 에러)

`piper-tts-web` 패키지가 .d.ts 타입 선언을 동봉하지 않음. [frontend/src/vite-env.d.ts](../../frontend/src/vite-env.d.ts)에 `class` 형태로 모듈 선언이 있어야 함:

```ts
declare module 'piper-tts-web' {
  export class PiperWebEngine {
    constructor(...args: any[])
    [key: string]: any
  }
  export class OnnxWebRuntime { ... }
  export class PhonemizeWebRuntime { ... }
}
```

`declare module 'piper-tts-web'` 단순 선언은 `PiperWebEngine`을 type으로 못 쓰므로(TS2709 에러) `class`로 선언해야 함.

### 설치 끝에 자동 실행 시 "CreateProcess 실패; 코드 740" (권한 상승 필요)

`Aunion AI.exe`가 [electron-builder.json](../../electron-builder.json)의 `requestedExecutionLevel: requireAdministrator`로 admin manifest를 가짐. Inno Setup 마법사 종료 시 일반 권한으로 실행 시도하면 Windows가 차단.

[installer.iss](../../installer.iss)의 `[Run]` 섹션에 `runascurrentuser` 플래그가 있어야 함:

```ini
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "..."; \
  Flags: nowait postinstall skipifsilent runascurrentuser
```

플래그가 빠진 이전 빌드를 사용 중이면 시작 메뉴/바탕화면에서 직접 실행 (UAC 한 번 뜨고 정상 동작).

### "VLM 모델이 지정된 로컬 경로에 없습니다" 에러 (설치본에서)

VLM Base를 동봉하지 않은 (B) 빌드인데, Inno Setup의 Excludes가 파일은 빼지만 **빈 디렉토리는 만들어 놓음**. 백엔드의 `resolve_model_dir`이 빈 폴더를 valid 모델로 오인.

영구 fix: [backend/app/config.py](../../backend/app/config.py)의 `resolve_model_dir`이 가중치 파일(`*.safetensors/*.bin/*.onnx/*.pt/*.pth`) 존재까지 검사하도록 강화 ([translate_slide_v3.py](../../translate_slide_v3.py)도 동일).

이미 적용되어 있으면 재빌드만 하면 해결. 임시 우회: 설치 위치의 `resources\backend\models\qwen2.5-vl-7b-instruct` 빈 폴더 삭제 → 앱 재시작 → 자동으로 HF에서 다운로드 시도.

---

## 산출물 위치 정리

| 경로 | 의미 | 배포 |
|---|---|---|
| `setup/Aunion-AI-Setup-{버전}.exe` | **단일 설치 파일** (사용자에게 전달) | ✅ |
| `setup/win-unpacked/` | 검증용 풀린 폴더 (직접 실행 가능) | ❌ (개발자 검증용) |
| `backend/dist/aunion_backend/` | PyInstaller 중간 산출물 | ❌ |
| `frontend/dist/` | Vite 빌드 산출물 | ❌ |

`setup/`은 전체가 [.gitignore](../../.gitignore)에 의해 git 제외 — 빌드 산출물은 커밋 대상 아님.

---

## 버전 갱신 절차

1. `package.json`의 `version` 올림 (예: `0.1.0` → `0.1.1`)
2. `installer.iss`의 `MyAppVersion`도 동일하게 변경
3. 위 3단계 빌드 재실행
4. 결과물 파일명: `setup/Aunion-AI-Setup-0.1.1.exe`

이전 버전 설치본은 새 버전으로 덮어 설치됨 (Inno Setup의 AppId 기준 동일 앱으로 인식).
