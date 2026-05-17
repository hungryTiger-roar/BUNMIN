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
| **디스크 여유 공간** | ✅ | **35 GB 권장** — 앱 본체 3.5GB + VLM 14GB + symlink → copy 패치로 인한 사본 14GB + 안전 마진. 설치 마법사 / 앱 첫 실행 시 자동 검사 |

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

가장 간단:

```bash
node scripts/run-iscc.js installer.iss
```

이 스크립트가 PATH → `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe` → `C:\Program Files (x86)\Inno Setup 6\ISCC.exe` 순으로 자동 탐색합니다 (winget per-user 설치가 PATH 등록 안 해줘서 만든 헬퍼).

직접 호출:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

```bash
"$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe" installer.iss
```

> **3단계를 한 줄로**: `npm run build:installer` 가 백엔드 PyInstaller + electron-builder + ISCC 를 순차 실행합니다.

**산출**: `setup/Aunion-AI-Setup-{버전}.exe` (약 3.2GB)

**소요 시간**: ~15~20분 (lzma2/max 압축, PyTorch CUDA DLL이 가장 오래)

> 빌드 설정은 [installer.iss](../../installer.iss)에 있음. 버전 변경 시 `MyAppVersion`, VLM 동봉 토글은 `[Files]` 섹션의 `Excludes`로 조정.

---

## VLM Base 동봉 여부 (사이즈 vs 첫 실행 UX 트레이드)

VLM Base(`Qwen/Qwen3-VL-4B-Instruct`)는 약 8GB. 동봉할지에 따라 두 가지 빌드:

| 옵션 | 설치본 크기 | 첫 실행 시 다운로드 | 사용 케이스 |
|---|---|---|---|
| **(A) 동봉** | ~11GB (압축) | 없음 (즉시 사용) | 발표/시연 직전 PC 세팅 |
| **(B) 미동봉** (현재 기본) | ~3.5GB | ~8GB HF 다운로드 (15~30분) | 일반 배포 |

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
cp -r models/qwen3-vl-4b-instruct setup/win-unpacked/resources/backend/models/
```

이후 단계 3 ISCC 실행. 압축 시간이 ~30~40분으로 늘어남.

> dev 머신에 `models/qwen3-vl-4b-instruct/`가 있어야 가능. 없으면 `npm run setup`으로 먼저 받기.

---

## 한 줄 빌드 명령 (전체 체인)

코드와 모델이 모두 갱신된 상황에서 한 번에 끝까지:

```bash
# 권장 — package.json 스크립트 사용 (PyInstaller + electron-builder + ISCC 순차)
npm run build:installer
```

또는 원시 명령으로:

```bash
# 1+2+3 한꺼번에 (VLM 미동봉 기본)
npm run build:backend \
  && npm run electron:build \
  && node scripts/run-iscc.js installer.iss
```

총 소요 시간: ~25~35분 (ISCC LZMA2 압축이 후반부 변동 폭 큼)

VLM 동봉본 만들려면 electron:build 뒤에 `cp -r models/qwen3-vl-4b-instruct setup/win-unpacked/resources/backend/models/` 한 줄 끼우고 `installer.iss`를 (A) 형태로 수정.

> **⚠ 빌드 순서 주의**: PyInstaller가 `frontend/dist/`를 그 시점에 캡처해 `_internal/frontend_dist/`에 임베드합니다. 만약 PyInstaller 후에 `npm run build --prefix frontend`로 frontend를 다시 빌드하면 PyInstaller bundle의 frontend는 stale해집니다.
>
> **자동 가드** (`backend/aunion.spec` 상단): PyInstaller 실행 시 `frontend/dist/index.html` 이 존재하지 않으면 빌드를 **즉시 중단**하고 `먼저 npm run build --prefix frontend 실행하세요` 메시지를 띄움. 이전 buildchain 사고 (옛 frontend_dist 가 그대로 setup.exe 에 박힘) 재발 방지. `npm run build:installer` 정상 흐름은 영향 없음.
>
> 프론트엔드만 수정한 경우 다음을 사용:
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

설치본 첫 실행 시 자동으로 표시. **이전엔 `/loading` + `/install` 두 페이지로 분리돼있었으나 통합됨** — 매 실행마다 `/install` 단일 진입점에서 백엔드 상태에 따라 phase 가 자동 전환.

### Phase (5단계)

1. **Preparing** — backend 가 모델 캐시 확인 + 로컬 로드 중. 4개 모델 카드(ASR/NMT/OCR/VLM) + 상태 칩(대기/로드 중/완료) 표시. 모든 모델이 캐시 hit 인 경우 (= 재실행) 이 단계만 거쳐 곧장 `/lecturer` 로 자동 진입 (Complete 페이지 스킵으로 마찰 제거).
2. **Intro** — VLM 미캐시 시 backend 가 `wait_user_action` 으로 대기 → "다운로드 시작" 버튼 + 디스크 체크 + 16GB 안내 카드.
3. **Downloading** — 진행률(byte), 속도, ETA 실시간 표시. **모델별 분리 카드** — VLM 14GB / (HF cache 가 비어있다면) Surya OCR ~2GB 등이 동시 다운로드 시 각자 카드 1개씩 깜빡임 없이 진행.
4. **Finalizing** — 다운로드 100% 도달 후 snapshot 생성 단계 (Windows 하드링크/복사). "다운로드를 마무리하고 있습니다" 메시지 + phase 칩 = "정리 중"
5. **Verifying** — safetensors 헤더 sanity 검사. "모델을 검증하고 있습니다" 메시지 + phase 칩 = "검증 중"
6. **Complete** — 설치 완료 안내 + "확인" 버튼 → `/lecturer`. (Preparing 만 거친 케이스에선 스킵)

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
| [installer.iss](../../installer.iss) `DefaultDirName` | `{localappdata}\Aunion AI` | 앱 본체와 사용자 데이터를 한 루트(`%LOCALAPPDATA%\Aunion AI`)에 모음 — 일반 사용자가 폴더 하나만 보면 됨 |

추가:
- `[Icons]`: `{autodesktop}` 사용 → 본인 바탕화면(`%USERPROFILE%\Desktop\`)에만 단축키 (다른 사용자 영향 X)
- `[Run]`: `runascurrentuser` 플래그 제거 (admin 매니페스트 없으니 권한 우회 불필요)

### 설치 위치 (`%LOCALAPPDATA%\Aunion AI\`)

```
%LOCALAPPDATA%\Aunion AI\
├─ Aunion AI.exe                   # 앱 본체 (Electron)
├─ resources\backend\              # PyInstaller 백엔드 + 동봉 자원 (재설치 시 덮어쓰기)
│   ├─ aunion_backend.exe
│   ├─ .env
│   ├─ models\                     # 인스톨러 동봉 (~2GB)
│   │   ├─ whisper-large-v3-turbo-ct2-int8\   # ASR (~1.5GB)
│   │   └─ nllb-200-distilled-600M-ct2\       # 실시간 NMT (~600MB)
│   └─ config\*.csv                # 용어집
├─ cache\                          # 사용자별 영구 (재설치로 안 날아감)
│   ├─ huggingface\hub\models--*\  # 첫 실행 마법사가 받는 VLM (~16GB, symlink→copy 패치로 실제 ~30GB)
│   └─ eta_learned.json            # 슬라이드 처리 시간 학습 baseline
├─ uploads\                        # 강의자 업로드 + 라이브러리
│   ├─ slides\<id>.pdf
│   ├─ library\<id>.meta.json
│   ├─ images\<id>\
│   ├─ translated\<id>\
│   └─ cache\<id>\                 # OCR/번역 중간 결과 (재시작 지원)
├─ transcripts\                    # 강의 자막 (json/srt/txt)
├─ logs\                           # 슬라이드 번역 디버그 로그
├─ error_log.txt                   # 백엔드/Electron 통합 에러 로그
└─ window-state.json               # 마지막 창 크기/위치
```

**경계**: `resources/backend/` 는 인스톨러가 덮어쓰는 영역(앱 본체 + 동봉 모델 Whisper/NLLB), 그 외 모든 폴더(`cache/`, `uploads/`, `transcripts/`, `logs/`)는 사용자 데이터 — 재설치/업그레이드해도 보존. 특히 VLM 은 `cache/huggingface/` 에 들어가므로 재설치 후 재다운로드 회피. 코드에선 [`app.config.DATA_ROOT`](../../backend/app/config.py) 한 곳에서 결정.

### 기존 설치본 사용자 마이그레이션

이전 버전을 깐 사용자가 새 빌드로 올라갈 때:

| 이전 위치 | 처리 |
|---|---|
| `C:\Program Files\Aunion AI\` (admin manifest 시절) | 제어판에서 제거 (UAC 1회) + 폴더 잔여 삭제 |
| `%LOCALAPPDATA%\Programs\Aunion AI\` (직전 per-user 빌드) | 제어판에서 제거 (UAC 없음) + 폴더 잔여 삭제 |
| `%LOCALAPPDATA%\Aunion AI\resources\backend\uploads\` (직전 빌드의 데이터 누적 위치) | 새 빌드는 `%LOCALAPPDATA%\Aunion AI\uploads\` 사용 — 옛 자료가 필요하면 한 단계 위로 옮겨야 함 |

**HF cache 정리 권장**: admin 프로세스로 받은 cache 안에 symlink 이 박혀 있으면 새 per-user(asInvoker) 프로세스가 traverse 거부 → WinError 448. `%LOCALAPPDATA%\Aunion AI\cache\huggingface\` 통째로 삭제 후 새 설치본 첫 실행 시 재다운로드 (또는 동봉본 사용).

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

## 트레이 아이콘 + 백그라운드 유지 ([frontend/electron/main.cjs](../../frontend/electron/main.cjs))

창 X 버튼 클릭 시 종료가 아니라 **시스템 트레이로 hide**. 강의자가 PDF 업로드 등 백그라운드 작업 진행 중일 때 창을 닫아도 작업 계속 + 다시 열면 같은 상태 유지.

### 동작

| 사용자 행동 | 결과 |
|---|---|
| 창 X 클릭 | 창 hide → 트레이 아이콘만 남음. `aunion_backend.exe` + Electron renderer 살아있음 |
| 트레이 아이콘 더블클릭 | 창 복원 + 포커스. React state / 라우트 / 스크롤 / fetch 진행 상황 모두 그대로 |
| 트레이 우클릭 → "종료" | `isQuitting=true` set → 진짜 종료. `before-quit` 흐름으로 백엔드 grace 정리 |

### 구현 포인트

- **`isQuitting` 플래그**: close 이벤트 핸들러가 이걸 보고 hide vs 진짜 종료 분기. 트레이 종료 / `before-quit` / 마법사 quit-app IPC 모두 set.
- **`webPreferences.backgroundThrottling: false`**: hide 후 hidden 상태에서 Chromium 이 setInterval / fetch 를 throttle 하지 않도록 비활성화. OCR 업로드처럼 진행 중인 fetch 가 정상 속도로 계속 진행.
- **`mainWindow.isDestroyed()` + `webContents.isDestroyed()` 가드**: 백엔드가 `detached: true` + 5분 grace 로 살아있어 mainWindow 파괴 뒤에도 stdout 이벤트 발생. `sendLog/sendProgress/sendModelStatus` 가 파괴된 webContents 에 접근하면 `TypeError: Object has been destroyed` crash → 가드로 방지.

### 임시 placeholder 아이콘

[frontend/electron/assets/tray-icon-{16,32}.png](../../frontend/electron/assets/) — indigo 배경에 "A" 글자. 정식 앱 아이콘 작업 시 교체 예정.

### 검증

1. 부팅 후 창 X → 트레이 아이콘만 남음 + 작업관리자에서 `aunion_backend.exe` PID 유지 확인
2. PDF 업로드 시작 → 진행률 보이는 동안 X → 트레이 더블클릭 → **진행률이 계속 진행** (`backgroundThrottling=false` 효과)
3. 트레이 우클릭 → 종료 → **crash 없이 깔끔히 종료** (이전엔 `TypeError: Object has been destroyed`)

---

## 창 위치/크기 영속화 ([frontend/electron/main.cjs](../../frontend/electron/main.cjs))

매 실행 시 디폴트 1280x800 가운데에서 시작하지 않고, 사용자가 마지막에 둔 **위치 + 크기 + maximize 상태**를 복원. `electron-window-state` 같은 외부 의존성 없이 자체 구현.

### 저장 위치

```
%LOCALAPPDATA%\Aunion AI\window-state.json
```

내용 예:
```json
{"x":120,"y":80,"width":1024,"height":720,"isMaximized":false}
```

### 동작 흐름

| 시점 | 동작 |
|---|---|
| 앱 시작 (`createWindow`) | JSON 로드 → width/height 적용. x/y 가 살아있는 디스플레이 안이면 적용, 아니면 무시 (디폴트 중앙). `isMaximized: true` 였으면 `mainWindow.maximize()` |
| `resize` / `move` | 500ms debounce 후 디스크 저장. 마지막 normal bounds 추적 |
| `maximize` / `unmaximize` | 즉시 저장 (debounced) |
| 창 X (트레이 hide) | 저장 X — bounds 변경 없음 |
| 진짜 종료 (`isQuitting=true`) | pending debounce flush + 동기 저장 |

### 핵심 안전장치

- **멀티모니터 가드**: `screen.getAllDisplays()` 로 저장 좌표가 살아있는 디스플레이의 workArea 안인지 확인. 보조 모니터 분리/꺼짐 후 재실행 시 창이 화면 밖으로 가는 사고 방지.
- **maximize-aware normal bounds**: `_lastNormalBounds` 변수가 직전 unmaximize 시점 bounds 추적. maximize 상태에서 종료해도 다음 unmaximize 시 자연 크기로 복원.
- **JSON 파싱 실패**: try/catch 로 디폴트 사용 — 빈 파일 / 손상된 JSON 에도 fallback.
- **debounce 500ms**: resize/move 드래그 중 폭주하는 이벤트로 인한 디스크 thrash 회피. close 시점 동기 flush 로 마지막 변경분 누락 차단.

### 코드 위치

- `loadWindowState()` / `_writeWindowState()` / `saveWindowState()` — `createWindow` 직전
- `_positionInsideAnyDisplay(x, y)` — 멀티모니터 검증 helper
- `_lastNormalBounds`, `_saveStateTimer` — 모듈 스코프 상태
- `createWindow` 안: `loadWindowState` → BrowserWindow 생성자에 spread → resize/move/maximize/unmaximize 이벤트 리스너 등록

### 검증

1. 창 크기/위치 임의 변경 → 트레이 "종료" → 재실행 → **같은 크기/위치 복원** ✅
2. Maximize → 종료 → 재실행 → **Maximize 로 시작** ✅
3. Maximize → restore (작은 크기) → 종료 → 재실행 → 작은 크기 ✅
4. 보조 모니터에 창 → 종료 → 모니터 분리 → 재실행 → **메인 모니터에 정상 표시** ✅

---

## 기본 메뉴바 제거 + 자체 타이틀바 ([frontend/electron/main.cjs](../../frontend/electron/main.cjs), [TitleBar.tsx](../../frontend/src/components/common/TitleBar.tsx))

기본 Electron chrome(File/Edit/View/Window/Help 메뉴 + OS 디폴트 흰색 타이틀바) 을 완전 제거하고 테마에 반응하는 자체 타이틀바를 그림. 데스크탑 앱 마감 완성도 ↑.

### 핵심 설정 3가지

| 위치 | 값 | 효과 |
|---|---|---|
| `main.cjs` (`whenReady`) | `Menu.setApplicationMenu(null)` | 메뉴바 + 기본 단축키 (Ctrl+R, Ctrl+Shift+I 등) 완전 제거 |
| `main.cjs` (BrowserWindow) | `frame: false` | OS 디폴트 타이틀바 + 윈도우 frame 제거. Windows 가장자리 8px 리사이즈는 그대로 유효 |
| `main.cjs` (BrowserWindow) | `backgroundColor: '#f5f5f4'` | 첫 페인트 전 흰 깜빡임 방지 (스플래시 컬러) |

### IPC + 자체 컨트롤 ([TitleBar.tsx](../../frontend/src/components/common/TitleBar.tsx))

자체 타이틀바는 32px fixed top 스트립. 좌측 indigo dot + "Aunion AI" 라벨, 우측 min/max/close SVG 버튼.

| IPC channel | 방향 | 동작 |
|---|---|---|
| `window-minimize` | renderer → main | `mainWindow.minimize()` |
| `window-toggle-maximize` | renderer → main | `mainWindow.isMaximized()` 여부에 따라 `maximize` / `unmaximize` |
| `window-close` | renderer → main | `mainWindow.close()` — 기존 close 핸들러로 들어가 트레이 hide 흐름 |
| `window-is-maximized` | renderer → main (invoke) | 현재 max 상태 boolean 반환 |
| `window-maximized-change` | main → renderer | maximize/unmaximize 이벤트 발생 시 renderer 에 통지 — 아이콘 토글용 |

스트립 전체에 `-webkit-app-region: drag` 으로 윈도우 드래그 핸들, 버튼들만 `no-drag` 로 클릭 가능.

### 테마 반영 (CSS 변수)

[styles/index.css](../../frontend/src/styles/index.css) 에 `--titlebar-bg` / `--titlebar-fg` 정의:

| 테마 | bg | fg |
|---|---|---|
| Light (default) | `#FFFFFF` (순백) | `#2A2F4A` (다크 navy) |
| Dark | `#1E2142` (다크 surface) | `#E8E9F5` (라이트) |
| Gradient | `rgba(46, 50, 87, 0.75)` 글래스 + `backdrop-filter: blur(8px)` | `#FFFFFF` |

테마 변경 (설정 페이지의 light / dark / gradient 토글) → `documentElement.classList` 갱신 → CSS 변수 자동 재바인딩 → 타이틀바 색 즉시 반영.

### `min-h-screen` 글로벌 override (레이아웃 충돌 방지)

자체 타이틀바 32px 가 추가됐는데 페이지들이 `min-h-screen` (= 100vh) 을 쓰면 viewport 를 32px 초과해 스크롤바 생김 + 콘텐츠가 타이틀바 영역 침범.

해결: [index.css](../../frontend/src/styles/index.css) 의 `@layer utilities` 에서 `.min-h-screen` 과 `.h-screen` 을 `calc(100vh - 32px)` 로 override. App.tsx wrapper 의 `pt-8` (32px 패딩) 과 합쳐 정확히 viewport 에 맞춰짐.

> **주의**: 글로벌 override 라 향후 모달/팝업/오버레이 컴포넌트에서 `min-h-screen` 쓰면 잘못된 높이가 적용됨. 그런 경우 `h-full` 또는 `min-h-[80vh]` 같은 임의 값 사용.

### 검증

1. 메뉴바 없음 — Alt 눌러도 안 나타남
2. OS 디폴트 흰색 타이틀바 없음 — 자체 32px 스트립
3. 드래그로 윈도우 이동, min/max/close 동작 (close 는 트레이 hide)
4. 테마 변경 시 타이틀바 색 즉시 반영
5. 스크롤바 없음, 콘텐츠가 타이틀바 영역 안 침범

---

## install / uninstall 시 백엔드 자동 종료 ([installer.iss](../../installer.iss) `[Code]`)

백엔드는 부모 Electron 종료 후에도 **5분 grace 동안 살아남아** 학생 자막 다운로드를 처리함 (`757bd35` 워치독). 이 grace 도중에 새 설치본을 실행하거나 제거를 시도하면 살아있는 `aunion_backend.exe` 가 파일 락을 잡아 Inno Setup 이 파일을 못 지움 → "닫아주세요" 다이얼로그 / "수동 삭제하세요" 메시지가 뜸.

해결: Inno Setup 의 두 후크에서 진입 직전에 백엔드 강제 종료.

```pascal
procedure KillAunionProcesses();
var ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM aunion_backend.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM "Aunion AI.exe" /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);  { Windows 핸들 정리 대기 }
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin KillAunionProcesses(); Result := ''; end;

function InitializeUninstall(): Boolean;
begin KillAunionProcesses(); Result := True; end;
```

`Aunion AI.exe` 까지 같이 kill 하는 이유 — Electron 메인 프로세스도 살아있으면 자기 자신 (`{app}\Aunion AI.exe`) 파일 락 잡음.

---

## 언인스톨 시 사용자 데이터 삭제 프롬프트 ([installer.iss](../../installer.iss) `[Code]`)

기본 Inno Setup uninstall 은 `{app}` (설치 위치) 만 삭제. `%LOCALAPPDATA%\Aunion AI\` (HF 모델 캐시 ~14GB+, 로그, 설정) 는 그대로 남아 사용자 디스크 영구 점유.

해결: 메인 uninstall 끝난 후 (`usPostUninstall`) 프롬프트로 yes/no 받기.

```pascal
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var UserDataDir: String; Response: Integer;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  if UninstallSilent then Exit;  { 무인 제거 시엔 안전하게 데이터 유지 }

  UserDataDir := ExpandConstant('{localappdata}\Aunion AI');
  if not DirExists(UserDataDir) then Exit;

  Response := MsgBox(
    '사용자 데이터를 함께 삭제하시겠습니까?'#13#10#13#10 +
    '위치: ' + UserDataDir + #13#10 +
    '내용: 다운받은 AI 모델 캐시(~14GB+), 로그, 설정'#13#10#13#10 +
    '[예] 함께 삭제 — 디스크 공간 회복'#13#10 +
    '[아니오] 데이터 유지 — 재설치 시 모델 재다운로드 안 받음 (권장)',
    mbConfirmation, MB_YESNO);

  if Response = IDYES then
    DelTree(UserDataDir, True, True, True);
end;
```

### UX 디테일

| 결정 | 이유 |
|---|---|
| 디폴트 권장 = "아니오" | 14GB 모델 캐시 보존이 안전. 재설치 시 다운로드 X |
| `UninstallSilent` 면 스킵 | 자동 업데이트 / 무인 제거에서 의도치 않게 날리는 것 차단 |
| `DirExists` 체크 | 이미 깨끗하면 프롬프트 안 뜸 |
| 삭제 실패 안내 | 권한 / 파일 락 문제 시 수동 삭제 경로 안내 |

---

## 인스톨러 비주얼 자산 ([installer-assets/](../../installer-assets/))

마법사를 줄글 위주에서 브랜드 색 사이드바 + 아이콘으로 강화. 모두 placeholder — 정식 디자인 나오면 동일 경로 파일 교체만 하면 됨.

### 자산 3종

| 파일 | 크기 / 포맷 | 용도 |
|---|---|---|
| [installer-assets/icon.ico](../../installer-assets/icon.ico) | multi-resolution ICO (256/128/64/48/32/16) | `SetupIconFile` — setup.exe 파일 아이콘 + 마법사 창 타이틀바 |
| [installer-assets/wizard-image.bmp](../../installer-assets/wizard-image.bmp) | 497x312 24-bit BMP | `WizardImageFile` — Welcome / Finished 페이지 좌측 사이드바 |
| [installer-assets/wizard-small.bmp](../../installer-assets/wizard-small.bmp) | 55x55 24-bit BMP | `WizardSmallImageFile` — 설치 진행 페이지 우상단 코너 |

### installer.iss 디렉티브 (4줄)

```ini
[Setup]
SetupIconFile=installer-assets\icon.ico
WizardImageFile=installer-assets\wizard-image.bmp
WizardSmallImageFile=installer-assets\wizard-small.bmp
WizardImageStretch=no
```

### 정식 디자인 도입 시

- Figma / Photoshop 등에서 디자인 → 위 사이즈로 export
- `installer-assets/` 의 4개 파일 (icon.ico + wizard-image.bmp + wizard-small.bmp + [frontend/electron/assets/icon.ico](../../frontend/electron/assets/icon.ico)) 교체
- Inno Setup 재컴파일 — 코드 변경 없음

> Electron 빌드 자산 (`frontend/electron/assets/icon.ico`) 도 같은 .ico 로 자동 배치. 추후 앱 아이콘 작업 시 그대로 활용.

---

## 모델별 분리 다운로드 UI (`_model_status["downloads"]`)

병렬 다운로드 (예: VLM + Surya OCR) 가 동시에 진행될 때 단일 `_model_status["download"]` 필드를 두 watcher 가 덮어쓰면서 UI 가 한 모델 / 다른 모델 사이로 깜빡이던 문제 해소.

`_model_status["downloads"]` (plural dict, key=model_key) 로 변경 — VLM watcher 는 `downloads["vlm"]` 에, NMT watcher 는 `downloads["nmt_asr"]` 에 독립적으로 기록. 프론트엔드는 활성 키마다 카드 1개씩 렌더링 (current/total 바이트 + 속도 + ETA + phase 칩).

`_is_cached` 도 같이 보강 — HF repo_id 가 default 인 모델 (예: NLLB) 의 **CT2 동봉본** 디렉토리(`<name>-ct2`) 가 설치 위치에 있으면 캐시 hit 으로 판정. 이전엔 HF cache 만 검사해서 fresh install 시 NMT 가 불필요하게 HF 원본 ~2.3GB 를 다운받았고 끝나면 안 쓰임.

---

## 디스크 공간 사전 체크

VLM 모델은 HF에서 ~14GB 다운로드되고, symlink → copy 패치 때문에 `blobs/` + `snapshots/` 양쪽에 사본이 생겨 실제 디스크 사용량이 **~28GB** 까지 늘어남. 여기에 앱 본체(~3.5GB)와 안전 마진을 더해 **35GB** 가 권장 여유 공간.

여유 부족 시 30~40분 다운로드 끝에 "out of space" 로 실패하는 최악 UX 를 막기 위해 **두 단계로 사전 체크**.

### 1️⃣ Inno Setup 안내 페이지 ([installer.iss](../../installer.iss) `[Code]` 섹션)

설치 마법사의 Welcome 페이지 다음에 **"AI 모델 추가 다운로드 안내"** 페이지가 추가됨. 사용자에게 첫 실행 시 14GB 추가 다운로드와 ~35GB 디스크 여유를 권장한다고 사전 안내.

`NextButtonClick` 핸들러가 설치 디렉토리 드라이브의 free space 를 `GetSpaceOnDisk64` 로 조회해서 35GB 미만이면 **확인 모달**(예/아니오)을 띄움. 사용자가 그래도 진행하겠다고 하면 설치 계속, 거부하면 페이지에 머무름.

```pascal
const RequiredFreeGB = 35;
{ ... CreateOutputMsgPage + GetFreeGB + NextButtonClick ... }
```

### 2️⃣ 앱 Install 마법사 디스크 체크 ([backend/app/routers/install.py](../../backend/app/routers/install.py) + [frontend/src/pages/Install.tsx](../../frontend/src/pages/Install.tsx))

설치 후 첫 실행 시 표시되는 Install 마법사의 Intro 단계에서:

- 백엔드 `GET /api/install/disk-check` → `shutil.disk_usage()` 로 `%LOCALAPPDATA%` 드라이브 free space 측정
- 프론트가 응답을 받아 카드형 UI 로 표시 (충분: 초록 / 부족: 빨강 + 부족분 안내)
- **부족 시 "다운로드 시작" 버튼 disable** + "디스크 부족" 라벨로 변경

추가 안전장치 — `POST /api/install/start-download` 자체가 디스크 재검사 후 부족하면 **HTTP 400 + `code: insufficient_disk`** 로 거부. 프론트가 disk-check 를 우회하더라도 다운로드가 시작되지 않음.

상수: [backend/app/routers/install.py](../../backend/app/routers/install.py) 의 `REQUIRED_GB = 30.0` (Inno 측의 35GB 보다 5GB 작음 — 설치본 자체 차지를 빼고 다운로드/cache 만 산정).

### 디스크 부족 시뮬레이션 (테스트용)

`REQUIRED_GB = 30.0` 을 임시로 `1000.0` 같은 큰 값으로 바꾸고 백엔드 재시작하면 부족 분기 UI 와 백엔드 거부 응답을 검증 가능.

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

[main.cjs](../../frontend/electron/main.cjs)가 백엔드 HTTP(`http://127.0.0.1:48000`) 응답을 기다린 뒤 거기서 frontend를 로드하도록 되어 있음. 백엔드가 늦게 뜨면 한참 빈 창이 뜰 수 있음 — 정상.

### 첫 실행 시 VLM 다운로드가 안 되거나 잘못된 위치로 받음

[backend/app/main.py](../../backend/app/main.py)의 `_vlm_default()`가 다음 순서로 찾음:
1. `%LOCALAPPDATA%/Aunion AI/models/qwen3-vl-4b-instruct/` (사용자 데이터)
2. `<install>/resources/backend/models/qwen3-vl-4b-instruct/` (동봉본)
3. 없으면 HF repo_id `Qwen/Qwen3-VL-4B-Instruct`로 다운로드

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
$f = "$env:LOCALAPPDATA\Aunion AI\cache\huggingface\hub\models--Qwen--Qwen3-VL-4B-Instruct\snapshots\<commit>\.gitattributes"
Get-Item $f | Select-Object Name, LinkType, Target
# LinkType=SymbolicLink 이면 위 fix 필요
```

### Install 마법사가 안 뜨고 옛 Loading 화면이 나옴 (구버전 — Loading 페이지 삭제됨)

> **현재 버전 (S14P31S205-145 이후) 엔 해당 안 됨** — `/loading` 페이지가 삭제되고 `/install` 단일 진입점으로 통합됨. 아래는 통합 이전 빌드 사용 시 디버깅 메모.

이전 빌드 디버깅: `setup/win-unpacked/resources/backend/_internal/frontend_dist/` 안의 frontend가 stale한 경우. PyInstaller가 frontend dist를 임베드한 시점 이후에 `npm run build`가 다시 돌았을 때 발생. 해결: frontend-only 흐름으로 frontend_dist 갱신 또는 PyInstaller 부터 다시 빌드.

### Install 마법사 Complete 화면을 못 보고 강의자 페이지로 직행 (S14P31S205-145 이후 의도된 동작)

> **현재**: 모델 캐시 hit (= 모든 모델 즉시 로드) 시 Complete 페이지를 스킵하고 곧장 `/lecturer` 로 자동 진입. 사용자의 불필요한 "확인" 클릭 제거. VLM 다운로드를 거친 케이스에선 여전히 Complete 표시.
>
> 구버전(Loading.tsx 가 분리되어 있던 시점) 의 IPC 리스너 leak 으로 인한 강제 navigate 버그는 Loading 페이지 통합 시 사라짐.

### "VLM 모델이 지정된 로컬 경로에 없습니다" 에러 (설치본에서)

VLM Base를 동봉하지 않은 (B) 빌드인데, Inno Setup의 Excludes가 파일은 빼지만 **빈 디렉토리는 만들어 놓음**. 백엔드의 `resolve_model_dir`이 빈 폴더를 valid 모델로 오인.

영구 fix: [backend/app/config.py](../../backend/app/config.py)의 `resolve_model_dir`이 가중치 파일(`*.safetensors/*.bin/*.onnx/*.pt/*.pth`) 존재까지 검사하도록 강화 ([translate_slide_v3.py](../../translate_slide_v3.py)도 동일).

이미 적용되어 있으면 재빌드만 하면 해결. 임시 우회: 설치 위치의 `resources\backend\models\qwen3-vl-4b-instruct` 빈 폴더 삭제 → 앱 재시작 → 자동으로 HF에서 다운로드 시도.

### `models/qwen3-vl-4b-instruct is not a local folder and is not a valid model identifier`

`%APPDATA%/Aunion AI/`를 지운 직후나 `.env`의 `VLM_BASE_MODEL`이 `models/...` 같은 로컬 상대경로일 때 발생. 로컬 경로가 실제로 존재하지 않으면 Transformers가 그 문자열을 HF repo_id로도 시도하다가 실패.

영구 fix: [backend/app/main.py](../../backend/app/main.py)와 [translate_slide_v3.py](../../translate_slide_v3.py)의 `_resolve_vlm`이 로컬 경로(`models/...`, `./...`, `../...`)가 풀리지 않을 때 `_vlm_default()` (HF repo_id `Qwen/Qwen3-VL-4B-Instruct`)로 fallback. 같은 로직이 두 군데에 있으니 한쪽만 고치지 말 것.

### Install 마법사에 "디스크 부족" 빨간 카드가 뜸 → 다운로드 버튼 비활성

`%LOCALAPPDATA%` 가 있는 드라이브의 free space 가 30GB 미만이면 발생. VLM ~14GB 다운로드 + symlink → copy 패치로 인한 사본 ~14GB + 안전 마진 = 30GB 필요.

해결: 다른 파일 정리해서 디스크 여유 확보 후 앱 재시작. 또는 설치 위치를 `%LOCALAPPDATA%` 와 다른 드라이브로 옮기는 건 미지원 — 캐시는 항상 `%LOCALAPPDATA%\Aunion AI\cache\` 사용.

상수 위치: [backend/app/routers/install.py](../../backend/app/routers/install.py) 의 `REQUIRED_GB`. 검증 시 임시로 큰 값으로 바꿔 부족 시나리오 재현 가능.

### 설치 후 첫 실행 시 흰 화면 (Chromium HTTP 캐시 stale)

Electron이 같은 origin(`http://127.0.0.1:48000`)에서 frontend를 로드하고 Chromium은 기본적으로 그 응답을 디스크 캐시에 저장. 신버전 설치본의 frontend는 Vite 해시(`index-XXXX.js`)가 바뀌어 있는데 사용자 PC에는 구버전 `index.html`이 캐시되어 있어 존재하지 않는 옛날 asset을 요청 → 404 → 흰 화면.

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
