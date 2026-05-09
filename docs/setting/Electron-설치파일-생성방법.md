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

| 도구 | 용도 | 버전 | 설치 방법 |
|---|---|---|---|
| **Conda 환경 `aunion`** | 백엔드 Python (PyTorch CUDA 등) | Python 3.10 | `npm run setup` (자동) |
| **Node.js / npm** | Electron / Vite 빌드 | Node 20+ | nodejs.org |
| **Electron** | 앱 셸 | **41+** | `package.json` devDependency |
| **electron-builder** | 패키징 도구 | **26+** | `package.json` devDependency |
| **NVIDIA GPU + CUDA** | 빌드 자체엔 필수 X, 백엔드 동작 검증엔 필요 | 12.x | nvidia.com |
| **Inno Setup** | 설치 파일 컴파일 | 6.x | `winget install JRSoftware.InnoSetup` |

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
| **관리자 권한** | ❌ | per-user 설치 (`%LOCALAPPDATA%\Programs\Aunion AI`) — 설치/실행 모두 UAC 안 뜸 |

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

VLM Base(`Qwen/Qwen2.5-VL-7B-Instruct`)는 약 14GB. 동봉할지에 따라 두 가지 빌드:

| 옵션 | 설치본 크기 | 첫 실행 시 다운로드 | 사용 케이스 |
|---|---|---|---|
| **(A) 동봉** | ~17GB (압축) | 없음 (즉시 사용) | 발표/시연 직전 PC 세팅 |
| **(B) 미동봉** (현재 기본) | ~3.2GB | 14GB HF 다운로드 (25~40분) | 일반 배포 |

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

> **⚠ 빌드 순서 주의**: PyInstaller가 `frontend/dist/`를 그 시점에 캡처해 `_internal/frontend_dist/`에 임베드합니다. 만약 PyInstaller 후에 `npm run build --prefix frontend`로 frontend를 다시 빌드하면 PyInstaller bundle의 frontend는 stale해집니다. 프론트엔드만 수정한 경우 다음을 사용:
>
> ```bash
> # 백엔드 코드 변경 없을 때 — frontend만 다시 빌드 + 동봉본만 갱신
> cd frontend && npm run build && cd .. \
>   && rm -rf setup/win-unpacked/resources/backend/_internal/frontend_dist/* \
>   && cp -r frontend/dist/. setup/win-unpacked/resources/backend/_internal/frontend_dist/ \
>   && "$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe" installer.iss
> ```
>
> Inno Setup만 다시 돌리므로 ~16분이면 끝.

---

## 첫 실행 마법사 (Install Wizard)

설치본을 처음 실행하는 사용자에게 VLM Base 16GB 다운로드를 안내하는 흐름. (B) 옵션 빌드의 첫 실행 시 자동으로 표시됨.

### 단계 (5단계)

1. **Intro** — 다운로드 안내 카드 + "다운로드 시작" 버튼
2. **Downloading** — 진행률(byte), 속도, ETA 실시간 표시
3. **Finalizing** — 다운로드 100% 도달 후 snapshot 생성 단계 (Windows 하드링크/복사). "다운로드를 마무리하고 있습니다" 메시지 + 보조 바 indeterminate
4. **Verifying** — safetensors 헤더 sanity 검사. "모델을 검증하고 있습니다" 메시지
5. **Complete** — 설치 완료 안내 + "확인" 버튼 → `/lecturer`

### 백엔드 상태 흐름

`/health` 응답의 `status` 필드:
- `wait_user_action` — VLM 미캐시 + 슬라이드 전용 모드 → 마법사 노출 후 사용자 클릭 대기
- `loading` + `download.phase=downloading` — 다운로드 진행
- `loading` + `download.phase=finalizing` — snapshot 생성 마무리
- `loading` + `download.phase=verifying` — 파일 검증
- `ready` / `ok` — 준비 완료 → Complete 화면

### 관련 파일

- [backend/app/main.py](../../backend/app/main.py) — `_load_models_sync`, `_start_byte_progress_watcher`, `_hf_repo_total_bytes`, `_start_download_event`
- [backend/app/routers/install.py](../../backend/app/routers/install.py) — `POST /api/install/start-download`
- [frontend/src/pages/Install.tsx](../../frontend/src/pages/Install.tsx) — 5단계 마법사 UI

### 디자인 가이드

- **배경**: stone-100 (`#f5f5f4`)
- **카드**: 흰색 + 부드러운 그림자 + stone-200 보더
- **헤드라인**: stone-900, 26px, semibold, 트래킹 -1%
- **본문**: stone-500/600
- **강조 컬러**: indigo-600 (다운로드 단계)
- **완료 컬러**: emerald-600 (Complete 단계)
- **에러 컬러**: red-600 (Error 단계)
- **타이포그래피**: 본문 sans-serif, 사이즈/속도 mono(tabular-nums)

---

## 설치 위치 및 권한 (per-user install)

`Aunion AI`는 **관리자 권한 없이** 설치/실행되도록 구성. 설치 마법사도, 앱 실행도, 매번 UAC 프롬프트가 뜨지 않음.

### 핵심 설정 3개

| 위치 | 값 | 효과 |
|---|---|---|
| [electron-builder.json](../../electron-builder.json) `requestedExecutionLevel` | `asInvoker` | 앱 실행 시 부모 프로세스(탐색기)와 같은 권한 — UAC 없음 |
| [installer.iss](../../installer.iss) `PrivilegesRequired` | `lowest` | Inno Setup 마법사 자체가 admin 안 요구 |
| [installer.iss](../../installer.iss) `DefaultDirName` | `{autopf}\Aunion AI` | `PrivilegesRequired=lowest`이면 `{autopf}` 가 `%LOCALAPPDATA%\Programs\` 로 자동 풀림 |

추가:
- `[Icons]`: `{autodesktop}` 사용 → 본인 바탕화면(`%USERPROFILE%\Desktop\`)에만 단축키 (다른 사용자 영향 X)
- `[Run]`: `runascurrentuser` 플래그 제거 (admin 매니페스트 없으니 권한 우회 불필요)

### 설치 위치

```
%LOCALAPPDATA%\Programs\Aunion AI\          # 앱 본체 (Aunion AI.exe 등)
%LOCALAPPDATA%\Aunion AI\                   # 사용자 데이터 (로그, HF 캐시, 모델)
└─ cache\huggingface\hub\models--*\         # HF Hub 다운로드
└─ models\qwen2.5-vl-7b-instruct\           # 사전 다운로드된 VLM (선택)
└─ error_log.txt                            # 백엔드 로그
```

### 기존 admin 설치본 사용자 마이그레이션

이전 버전(admin manifest, `C:\Program Files\Aunion AI`)을 깐 사용자가 새 per-user 빌드로 올라갈 때:

1. **Inno Setup이 기존 HKLM admin 설치를 못 알아봄** (HKCU만 보므로) → 그냥 깔면 두 곳에 이중 설치
2. 따라서 **기존 설치를 먼저 제거**해야 함:
   - 설정 → 앱 → 설치된 앱 → "Aunion AI" 제거 (UAC 한 번 — 마지막)
   - `C:\Program Files\Aunion AI\` 폴더 잔여 시 수동 삭제
3. **HF cache 정리 권장**: admin 프로세스로 받은 cache 안에 symlink이 박혀 있어 새 per-user(asInvoker) 프로세스가 traverse 거부 → WinError 448. `%LOCALAPPDATA%\Aunion AI\cache\` 통째로 삭제 후 새 설치본 첫 실행 시 재다운로드.

### HF Hub symlink → copy 대체 ([backend/run.py](../../backend/run.py))

Windows에서는 HF Hub이 cache `snapshots/<commit>/file` 위치에 **symlink** 을 만들어 `blobs/<hash>` 를 가리키게 함 (디스크 절약 목적). 그러나 새 Windows 보안 정책이 사용자 프로세스가 만든 symlink을 "untrusted mount point"로 판정해 다른 프로세스가 traverse 하려 하면 **WinError 448** 로 막힘.

해결: `backend/run.py` 최상단에서 `os.symlink` 자체를 `shutil.copyfile` 로 대체. HF Hub 입장에선 symlink 성공으로 보이지만 실제로는 reparse point 대신 일반 파일 복사본이 생성됨.

```python
if sys.platform == "win32":
    import shutil as _shutil

    def _symlink_as_copy(src, dst, target_is_directory=False, *, dir_fd=None):
        src_str = os.fspath(src)
        dst_str = os.fspath(dst)
        # symlink 의 src 는 보통 dst 디렉토리 기준 상대경로 — resolve
        if not os.path.isabs(src_str):
            resolved_src = os.path.normpath(os.path.join(os.path.dirname(dst_str), src_str))
        else:
            resolved_src = src_str
        if target_is_directory:
            return
        _shutil.copyfile(resolved_src, dst_str)

    os.symlink = _symlink_as_copy
```

> **이전 시도 (deprecated)**: `os.symlink` 을 `OSError` 던지게 해서 HF Hub의 `shutil.copyfile` fallback 을 유도했는데, **xet 다운로드 경로** 또는 `new_blob=False` 인 재호출 등에서는 fallback 자체가 없어 `OSError` 가 그대로 전파돼 다운로드 실패. 직접 copy 로 대체하는 현재 방식이 안전.

> **트레이드오프**: blobs/ 와 snapshots/ 양쪽에 동일 콘텐츠가 들어가 디스크 사용량 ~2배 (VLM 14GB → ~28GB). per-user 설치 안정성을 위한 비용.

### VLM 다운로드 진행률 측정 ([backend/app/main.py](../../backend/app/main.py))

`_measure_dir_size` 가 위 symlink → copy 대체와 함께 동작하도록 두 가지 보강:

1. **`max(blobs/, snapshots/)`**: HF Hub 의 두 가지 layout 을 모두 다룸. symlink 가능 환경에선 blobs/ 에 실제 파일, symlink 차단 환경에선 snapshots/ 에 파일이 들어감. 어느 쪽이든 큰 값을 취하면 정확.
2. **단조 증가 clamp** (in `_start_byte_progress_watcher`): atomic move/rename 순간이나 partial 삭제 후 재시작으로 측정값이 일시 감소해도 UI 가 뒤로 가지 않게 직전 값으로 clamp.

이전 구현은 `blobs/` 직속만 non-recursive 합산이라 symlink 차단 환경에선 항상 0 GB 로 측정 → 진행률이 7GB → 2GB 같은 부정확한 표시가 났음.

---

## 단일 인스턴스 락 (Single Instance Lock)

설치된 `Aunion AI.exe`는 **한 번에 하나만** 실행되도록 [main.cjs](../../frontend/electron/main.cjs)가 강제. 사용자가 시작메뉴/바탕화면에서 두 번 더블클릭하거나 이미 켜져 있는 상태에서 다시 실행하면 두 번째 시도는 즉시 종료되고 첫 인스턴스 창이 포커스됨.

### 왜 필요한가

두 번째 인스턴스가 정상 부팅되면 다음 두 가지가 모두 첫 인스턴스를 망가뜨림:

1. **포트 충돌**: 백엔드가 8000 포트를 사용 중인데 두 번째 인스턴스도 같은 포트로 띄우려다 실패
2. **백엔드 학살**: 두 번째 인스턴스의 `startBackend()` 시작 부분에서 `taskkill /F /IM aunion_backend.exe /T` 실행 → **첫 인스턴스의 백엔드까지 죽임** (모델 로딩 중이었다면 사용자 데이터 손실)

### 구현 위치

[main.cjs](../../frontend/electron/main.cjs)에 두 부분:

1. **모듈 로드 시점** — 로그 setup 직후, 다른 모든 핸들러 등록 *전*:
   ```js
   if (!app.requestSingleInstanceLock()) {
     appendLog('이미 실행 중인 인스턴스가 있어 종료합니다')
     process.exit(0)   // app.quit() 은 비동기라 위험 핸들러 등록을 막을 수 없음
   }
   ```
   `process.exit(0)` 으로 즉시 종료해야 `before-quit`/`window-all-closed`의 `taskkill`이 절대 안 돌게 됨.

2. **`second-instance` 이벤트 핸들러** — 첫 인스턴스에서만 발화:
   ```js
   app.on('second-instance', () => {
     if (mainWindow && !mainWindow.isDestroyed()) {
       if (mainWindow.isMinimized()) mainWindow.restore()
       if (!mainWindow.isVisible()) mainWindow.show()
       mainWindow.focus()
     }
   })
   ```

### 검증 시나리오 (4가지)

설치본 설치 후 검증:

| # | 시나리오 | 기대 동작 |
|---|---|---|
| 1 | 부팅 완료 후 시작메뉴에서 두 번째 더블클릭 | 새 창 X, 첫 창 자동 포커스 |
| 2 | 백엔드 PID 메모 → 두 번째 실행 시도 → PID 재확인 | 같은 PID 유지 (백엔드 보호) |
| 3 | 첫 창 최소화 → 두 번째 실행 시도 | 최소화 창 자동 복원 + 포커스 |
| 4 | 첫 인스턴스 X 종료 → 단축키 재실행 | 정상 부팅 (락 해제) |

`%LOCALAPPDATA%\Aunion AI\error_log.txt`에 다음 라인이 찍히면 정상:
```
[...] 두 번째 인스턴스 차단 — 기존 창 활성화          # 첫 인스턴스 측
[...] 이미 실행 중인 인스턴스가 있어 종료합니다        # 두 번째 인스턴스 측
```

### 적용 범위

- ✅ **앱 본체** (`Aunion AI.exe`) — 락 적용
- ❌ **설치 프로그램** (`Aunion-AI-Setup-{버전}.exe`) — Inno Setup 측에서 별도 처리 필요. 현재는 두 번 더블클릭 시 마법사 두 개 뜸. 필요하면 `installer.iss`의 `[Setup]`에 `AppMutex=AunionAISetupMutex` 추가.

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

### 설치 끝에 자동 실행 시 "CreateProcess 실패; 코드 740" (구버전 admin 빌드 잔재)

> **현재 버전엔 발생 안 함** — `requestedExecutionLevel`을 `asInvoker`로 바꾸고 per-user 설치로 전환한 뒤 admin manifest 가 사라져 코드 740 시나리오 자체가 없어졌음. 아래는 이전 admin 빌드(`requireAdministrator`)에서 발생한 문제 기록용.

이전 admin manifest 빌드에서: `Aunion AI.exe`가 admin manifest를 가지므로 Inno Setup 마법사 종료 후 일반 권한으로 실행 시도하면 Windows가 차단. `[Run]` 섹션에 `runascurrentuser` 플래그가 있어야 했음.

### `[WinError 448] 경로에 신뢰할 수 없는 탑재 지점이 포함되어 있기 때문에` (모델 로딩 실패)

per-user(asInvoker) 프로세스가 cache 안 symlink을 traverse 하려 하면 새 Windows 보안 정책이 "untrusted mount point"로 판정해 차단. 보통 다음 두 케이스에서 발생:

1. **이전 admin 빌드의 cache 잔재**: admin 프로세스가 만든 symlink을 새 per-user 앱이 못 읽음
2. **Dev Mode 등으로 symlink 생성이 가능한 환경**: 매 다운로드마다 재현

영구 fix: [backend/run.py](../../backend/run.py) 최상단에서 `os.symlink` 자체를 `shutil.copyfile` 로 대체 (위 "설치 위치 및 권한 → HF Hub symlink → copy 대체" 섹션 참고).

이미 손상된 cache를 가진 사용자는 `%LOCALAPPDATA%\Aunion AI\cache\` 통째로 삭제 후 앱 재실행 → 자동 재다운로드.

진단 (PowerShell):
```powershell
$f = "$env:LOCALAPPDATA\Aunion AI\cache\huggingface\hub\models--Qwen--Qwen2.5-VL-7B-Instruct\snapshots\<commit>\.gitattributes"
Get-Item $f | Select-Object Name, LinkType, Target
# LinkType=SymbolicLink 이면 위 fix 필요
```

### Install 마법사가 안 뜨고 옛 Loading 화면이 나옴

`setup/win-unpacked/resources/backend/_internal/frontend_dist/` 안의 frontend가 stale한 경우. PyInstaller가 frontend dist를 임베드한 시점 이후에 `npm run build`가 다시 돌았을 때 발생.

해결: 위의 "한 줄 빌드 명령" 박스 안의 frontend-only 흐름으로 frontend_dist만 갱신하거나, PyInstaller부터 다시 빌드.

검증:
```bash
grep -o "wait_user_action" setup/win-unpacked/resources/backend/_internal/frontend_dist/assets/*.js
```
나와야 정상.

### Install 마법사 Complete 화면을 못 보고 강의자 페이지로 직행

[Loading.tsx](../../frontend/src/pages/Loading.tsx)의 IPC 리스너(`onBackendReady` 등)가 cleanup 없이 등록되어, 사용자가 `/install`로 이동한 뒤에도 `backend-ready` IPC가 도착하면 leaked 리스너가 `navigate('/lecturer')`를 호출함.

fix: Loading.tsx의 모든 IPC 콜백 첫 줄에 `if (!window.location.hash.startsWith('#/loading')) return` 가드 추가됨. 새 리스너가 추가되면 동일 가드 필요.

### "VLM 모델이 지정된 로컬 경로에 없습니다" 에러 (설치본에서)

VLM Base를 동봉하지 않은 (B) 빌드인데, Inno Setup의 Excludes가 파일은 빼지만 **빈 디렉토리는 만들어 놓음**. 백엔드의 `resolve_model_dir`이 빈 폴더를 valid 모델로 오인.

영구 fix: [backend/app/config.py](../../backend/app/config.py)의 `resolve_model_dir`이 가중치 파일(`*.safetensors/*.bin/*.onnx/*.pt/*.pth`) 존재까지 검사하도록 강화 ([translate_slide_v3.py](../../translate_slide_v3.py)도 동일).

이미 적용되어 있으면 재빌드만 하면 해결. 임시 우회: 설치 위치의 `resources\backend\models\qwen2.5-vl-7b-instruct` 빈 폴더 삭제 → 앱 재시작 → 자동으로 HF에서 다운로드 시도.

### `models/qwen2.5-vl-7b-instruct is not a local folder and is not a valid model identifier`

`%APPDATA%/Aunion AI/`를 지운 직후나 `.env`의 `VLM_BASE_MODEL`이 `models/...` 같은 로컬 상대경로일 때 발생. 로컬 경로가 실제로 존재하지 않으면 Transformers가 그 문자열을 HF repo_id로도 시도하다가 실패.

영구 fix: [backend/app/main.py](../../backend/app/main.py)와 [translate_slide_v3.py](../../translate_slide_v3.py)의 `_resolve_vlm`이 로컬 경로(`models/...`, `./...`, `../...`)가 풀리지 않을 때 `_vlm_default()` (HF repo_id `Qwen/Qwen2.5-VL-7B-Instruct`)로 fallback. 같은 로직이 두 군데에 있으니 한쪽만 고치지 말 것.

### 설치 후 첫 실행 시 흰 화면 (Chromium HTTP 캐시 stale)

Electron이 같은 origin(`http://127.0.0.1:8000`)에서 frontend를 로드하고 Chromium은 기본적으로 그 응답을 디스크 캐시에 저장. 신버전 설치본의 frontend는 Vite 해시(`index-XXXX.js`)가 바뀌어 있는데 사용자 PC에는 구버전 `index.html`이 캐시되어 있어 존재하지 않는 옛날 asset을 요청 → 404 → 흰 화면.

진단:
```js
// DevTools Console
await fetch('/').then(r => r.text()).then(html => html.match(/index-[\w-]+\.(js|css)/g))
```
실제 디스크의 `index.html`과 다르면 캐시 stale.

영구 fix: [backend/app/main.py](../../backend/app/main.py)의 `spa_fallback`이 `index.html`을 응답할 때 `Cache-Control: no-store, no-cache, must-revalidate` 헤더를 붙임. asset(`*.js`/`*.css`)은 해시 파일명이라 캐시 OK — html만 매번 갱신.

이미 적용된 빌드라면 사용자 측에서 Ctrl+Shift+R (Hard reload)로 한 번만 풀면 됨.

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
