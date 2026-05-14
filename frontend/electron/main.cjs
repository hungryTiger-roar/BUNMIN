const { app, BrowserWindow, ipcMain, desktopCapturer, session, Tray, Menu, nativeImage, screen } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const http = require('http')
const os = require('os')
const fs = require('fs')

// ─── 로그 파일 설정 ────────────────────────────────────────────────
// app.getPath('userData') 는 app.whenReady() 이후에만 쓸 수 있으므로
// LOCALAPPDATA 기반 경로를 직접 계산
const _logDir = path.join(
  process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'),
  'Aunion AI',
)
try { fs.mkdirSync(_logDir, { recursive: true }) } catch {}
const LOG_FILE = path.join(_logDir, 'error_log.txt')
const WINDOW_STATE_FILE = path.join(_logDir, 'window-state.json')

let _logInitialized = false

function appendLog(msg) {
  // 첫 호출 시 덮어쓰기, 이후 append
  const flag = _logInitialized ? 'a' : 'w'
  _logInitialized = true
  try {
    fs.writeFileSync(LOG_FILE, msg + '\n', { flag, encoding: 'utf8' })
  } catch {}
}

// 세션 시작 헤더
appendLog('='.repeat(60))
appendLog(`[${new Date().toISOString()}] Electron main 시작`)
appendLog(`Log: ${LOG_FILE}`)
appendLog('='.repeat(60))

// ─── 단일 인스턴스 락 ────────────────────────────────────────────
// 두 번째 인스턴스가 startBackend()로 가면 8000포트 충돌 + 모듈 상단의
// taskkill /F /IM aunion_backend.exe 가 첫 인스턴스의 백엔드까지 죽임.
// 따라서 이벤트 핸들러 등록 *이전* 시점에 락 실패 → 즉시 종료.
if (!app.requestSingleInstanceLock()) {
  appendLog(`[${new Date().toISOString()}] 이미 실행 중인 인스턴스가 있어 종료합니다`)
  // app.quit() 은 비동기라 module 평가가 계속됨 → before-quit/window-all-closed
  // 핸들러가 위험한 taskkill 을 부를 수 있어 process.exit(0) 으로 즉시 종료.
  process.exit(0)
}

function getLanIp() {
  const interfaces = os.networkInterfaces()
  for (const name of Object.keys(interfaces)) {
    for (const iface of interfaces[name]) {
      if (iface.family === 'IPv4' && !iface.internal) {
        return iface.address
      }
    }
  }
  return '127.0.0.1'
}

let mainWindow = null
let backendProcess = null
let tray = null
// 사용자가 트레이 "종료" 클릭, 설치 마법사 quit-app IPC, 또는 OS 셧다운 등 진짜 종료
// 의사를 표명한 경우만 true. close 핸들러가 이 플래그를 보고 hide vs 종료 분기.
let isQuitting = false

const isDev = process.env.NODE_ENV === 'development'
const BACKEND_PORT = 8000
const HEALTH_PORT = 18765   // GIL 독립 전용 health 서버 포트
const FRONTEND_PORT = 3000

// dev 모드에서 concurrently 터미널에 라이프사이클 추적 로그 출력
function devLog(msg) {
  console.log(`[main] ${msg}`)
}
devLog(`Electron main 시작 (isDev=${isDev}, NODE_ENV=${process.env.NODE_ENV || 'unset'})`)

// ─── renderer 메시지 전송 + 마지막 상태 캐시 ────────────────────────
// renderer mount 타이밍이 늦어 IPC 이벤트를 놓칠 수 있으므로
// 마지막 상태를 캐시하고 'get-backend-state' invoke로 동기화 가능하게 함.
const _lastState = {
  progress: 0,
  models: null,
  ready: null,    // null=미정, true=ok/ready, false=error
}

// mainWindow 가 파괴된 뒤에도 백엔드(detached) 가 살아있어 stdout 이벤트가 계속
// 발생함. 파괴된 webContents 에 send() 호출하면 "Object has been destroyed" 던짐.
function _renderTarget() {
  if (!mainWindow || mainWindow.isDestroyed()) return null
  const wc = mainWindow.webContents
  if (!wc || wc.isDestroyed()) return null
  return wc
}

function sendLog(log) {
  const wc = _renderTarget()
  if (wc) wc.send('backend-log', log)
}
function sendProgress(progress) {
  _lastState.progress = progress
  const wc = _renderTarget()
  if (wc) wc.send('backend-progress', progress)
}
function sendModelStatus(models) {
  _lastState.models = models
  const wc = _renderTarget()
  if (wc) wc.send('backend-model-status', models)
}

// ─── 백엔드 준비 신호 (한 번만 호출) ─────────────────────────────
// stdout(__AUNION_STATUS__) 또는 health 폴링 중 먼저 도착하는 쪽이 호출.
// 타임아웃도 이 함수를 통해 처리.
let _notifyReady = null

function notifyReady(success) {
  _lastState.ready = success
  devLog(`백엔드 준비 신호 수신: success=${success}`)
  if (_notifyReady) {
    const fn = _notifyReady
    _notifyReady = null
    fn(success)
  }
}

// ─── 백엔드 실행 (프로덕션에서만) ──────────────────────────────────
function startBackend() {
  if (isDev) return

  // 이전 세션에서 남은 프로세스가 포트를 점유하는 경우 방지
  try {
    require('child_process').execSync('taskkill /F /IM aunion_backend.exe /T', { stdio: 'ignore' })
  } catch {
    // 기존 프로세스 없음 — 정상
  }

  const resourcesPath = process.resourcesPath || path.join(path.dirname(process.execPath), 'resources')
  const backendExe = path.join(resourcesPath, 'backend', 'aunion_backend.exe')

  // 시스템에 만료/잘못된 HF 토큰이 있으면 공개 모델도 401 에러 발생.
  // 시스템 환경변수에서 토큰을 제거하면 Python의 load_dotenv()가
  // .env 파일의 토큰을 정상적으로 읽을 수 있음.
  const { HF_TOKEN, HUGGINGFACE_HUB_TOKEN, ...spawnEnv } = process.env

  backendProcess = spawn(backendExe, [], {
    env: {
      ...spawnEnv,
      PYTHONUNBUFFERED: '1',       // Python stdout 버퍼링 해제
      PYTHONUTF8: '1',             // stdout 인코딩 UTF-8 강제
      PYTHONIOENCODING: 'utf-8',   // 더 명시적인 UTF-8 강제
      // 백엔드가 Electron 부모 PID 를 감시 — .exe 가 닫히면 백엔드는 5분 더 살아
      // 학생 자막 다운로드 받게 한 후 자살. 재실행 시 startBackend 첫 줄 taskkill 이
      // 이 grace 도중에도 강제 kill (의도된 동작).
      AUNION_PARENT_PID: String(process.pid),
    },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    // detached: 부모 (Electron) 가 죽어도 백엔드는 살아남도록 — Windows 에서 부모-자식 관계
    // 분리. 이렇게 안 하면 Electron 종료 시 OS 가 자식 프로세스도 같이 정리해 5분 grace 가 무력화됨.
    detached: true,
  })
  // detached 와 함께 unref() — 부모의 event loop 에 자식이 영향 안 미치게.
  backendProcess.unref()

  // ── stdout: __AUNION_STATUS__ 파싱 + 일반 로그 전달 ──────────────
  let stdoutBuf = ''
  backendProcess.stdout.on('data', (data) => {
    const raw = data.toString()
    appendLog(`[STDOUT] ${raw.trimEnd()}`)

    stdoutBuf += raw
    const lines = stdoutBuf.split('\n')
    stdoutBuf = lines.pop()  // 마지막 불완전 라인은 버퍼에 보관

    const logLines = []
    for (const line of lines) {
      if (line.startsWith('__AUNION_STATUS__:')) {
        try {
          const s = JSON.parse(line.slice('__AUNION_STATUS__:'.length))
          if (typeof s.progress === 'number') sendProgress(s.progress)
          if (s.models) sendModelStatus(s.models)
          // 완료/실패 신호 → 즉시 화면 전환 (health 폴링 기다릴 필요 없음)
          // "ok": 풀 모드 모델 로드 완료, "ready": 슬라이드 전용 모드 준비 완료
          if (s.status === 'ok' || s.status === 'ready') {
            notifyReady(true)
          } else if (s.status === 'error') {
            if (s.message) sendLog(`[오류] ${s.message}`)
            notifyReady(false)
          }
        } catch {
          // JSON 파싱 실패 — 무시
        }
      } else if (line.trim()) {
        logLines.push(line.trim())
      }
    }

    if (logLines.length > 0) {
      const log = logLines.join('\n')
      console.log(`[Backend] ${log}`)
      sendLog(log)
    }
  })

  // ── stderr: 다운로드 tqdm 등 UI에 표시 ───────────────────────────
  backendProcess.stderr.on('data', (data) => {
    const log = data.toString()
    appendLog(`[STDERR] ${log.trimEnd()}`)
    console.error(`[Backend Error] ${log}`)
    sendLog(log)
  })

  backendProcess.on('close', (code) => {
    appendLog(`[INFO] 백엔드 프로세스 종료 (code: ${code})`)
    console.log(`[Backend] 종료됨 (code: ${code})`)
    if (code !== 0 && code !== null) {
      sendLog(`[오류] 백엔드 프로세스가 예기치 않게 종료됐습니다 (code: ${code})`)
      notifyReady(false)  // 프로세스 크래시 → 실패 처리
    }
  })
}

// ─── 백엔드 준비 대기 ────────────────────────────────────────────
// stdout의 __AUNION_STATUS__ status:"ok" 가 PRIMARY 신호.
// health 폴링은 BACKUP — GIL로 막힐 수 있지만 혹시 응답하면 활용.
// maxAttempts=1800(2s×1800=60분): 다운로드 시간 여유 충분히 확보.
function waitForBackend(callback, maxAttempts = 1800) {
  _notifyReady = callback   // stdout 핸들러와 공유

  let attempts = 0
  // Windows Node.js는 'localhost'를 IPv6(::1)로 먼저 풀 수 있음 — uvicorn은 0.0.0.0(IPv4)만
  // 듣고 있어 ECONNREFUSED 발생. 명시적으로 127.0.0.1로 고정.
  const healthUrl = isDev
    ? `http://127.0.0.1:${BACKEND_PORT}/health`
    : `http://127.0.0.1:${HEALTH_PORT}/`
  devLog(`health 폴링 시작: ${healthUrl} (maxAttempts=${maxAttempts})`)

  const check = () => {
    devLog(`health check #${attempts + 1} → ${healthUrl}`)
    const req = http.get(healthUrl, (res) => {
      if (res.statusCode === 200) {
        let body = ''
        res.on('data', (chunk) => { body += chunk })
        res.on('end', () => {
          try {
            const json = JSON.parse(body)
            if (json.status === 'ok' || json.status === 'ready') {
              devLog(`health 200 → status=${json.status} (성공)`)
              sendProgress(100)
              if (json.models) sendModelStatus(json.models)
              notifyReady(true)
            } else if (json.status === 'error') {
              devLog(`health 200 → status=error msg="${json.message || ''}"`)
              if (json.message) sendLog(`[오류] ${json.message}`)
              notifyReady(false)
            } else {
              // 로딩 중 — 진행률 + 메시지 보조 업데이트 (stdout이 주)
              devLog(`health 200 → status=${json.status} progress=${json.progress}`)
              if (typeof json.progress === 'number') sendProgress(json.progress)
              if (json.models) sendModelStatus(json.models)
              if (json.message) sendLog(json.message)
              retry('loading status')
            }
          } catch (e) {
            devLog(`health 200 but JSON parse 실패: ${e.message}`)
            retry('parse error')
          }
        })
      } else {
        devLog(`health non-200: ${res.statusCode}`)
        retry(`status ${res.statusCode}`)
      }
    })
    req.on('error', (err) => {
      devLog(`health 요청 오류: ${err.code || err.message}`)
      retry(err.code || 'error')
    })
    req.setTimeout(10000, () => {
      devLog('health 요청 timeout (10s)')
      req.destroy()
      retry('timeout')
    })

    function retry(reason) {
      attempts++
      if (attempts <= 3 || attempts % 15 === 0) {
        devLog(`retry #${attempts} (이유: ${reason || '미상'})`)
      }
      if (attempts % 15 === 0) {
        const elapsed = Math.floor(attempts * 2 / 60)
        sendLog(`[대기] 모델 로딩 중... (${elapsed}분 경과, 다운로드 시 최대 60분 소요)`)
      }
      if (_notifyReady && attempts < maxAttempts) {
        setTimeout(check, 2000)
      } else if (_notifyReady) {
        devLog(`maxAttempts(${maxAttempts}) 초과 — 실패 처리`)
        notifyReady(false)
      }
    }
  }

  setTimeout(check, 1000)
}

// ─── 백엔드 HTTP 서버 빠른 헬스 체크 ─────────────────────────────────
// waitForBackend는 모델 로딩 완료까지 기다리지만, 이 함수는 HTTP 서버 응답만 확인.
// 프로덕션 모드에서 frontend를 file:// 대신 http://127.0.0.1:8000으로 로드하기 위함.
// (Chromium은 file://을 secure context로 안 봐서 getUserMedia 차단됨 — http://localhost는 통과.)
function waitForHealth(callback, maxAttempts = 60) {
  let attempts = 0
  const url = `http://127.0.0.1:${BACKEND_PORT}/health`

  const tryConnect = () => {
    const req = http.get(url, (res) => {
      devLog(`waitForHealth: backend HTTP up (status=${res.statusCode})`)
      res.resume()
      callback(true)
    })
    req.on('error', () => {
      attempts++
      if (attempts < maxAttempts) {
        setTimeout(tryConnect, 500)
      } else {
        devLog(`waitForHealth: ${maxAttempts}회 초과 — 실패`)
        callback(false)
      }
    })
    req.setTimeout(2000, () => { req.destroy() })
  }
  tryConnect()
}


// ─── 창 위치/크기 영속화 ────────────────────────────────────────────
// 마지막 normal(=maximize 해제) bounds 추적. maximize 상태에서 저장 시 이 값을 기록해
// 다음 실행 시 unmaximize 했을 때 자연 크기로 복원되도록.
let _lastNormalBounds = null
let _saveStateTimer = null

function loadWindowState() {
  try {
    if (!fs.existsSync(WINDOW_STATE_FILE)) return null
    return JSON.parse(fs.readFileSync(WINDOW_STATE_FILE, 'utf8'))
  } catch (e) {
    devLog(`window state load 실패 (디폴트 사용): ${e.message}`)
    return null
  }
}

function _positionInsideAnyDisplay(x, y) {
  // 멀티모니터 검증 — 보조 모니터 분리/끄기 후 재실행 시 화면 밖으로 가지 않게.
  try {
    return screen.getAllDisplays().some((d) => {
      const r = d.workArea
      return x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height
    })
  } catch {
    return true
  }
}

function _writeWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const isMax = mainWindow.isMaximized()
  // maximize 상태에선 사용자가 X 누르기 직전의 normal bounds 를 저장.
  const bounds = isMax && _lastNormalBounds ? _lastNormalBounds : mainWindow.getBounds()
  try {
    fs.writeFileSync(
      WINDOW_STATE_FILE,
      JSON.stringify({
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
        isMaximized: isMax,
      }),
      'utf8',
    )
  } catch (e) {
    devLog(`window state save 실패: ${e.message}`)
  }
}

function saveWindowState() {
  // resize/move 드래그 중엔 이벤트가 폭주하므로 debounce 로 디스크 thrash 회피.
  if (_saveStateTimer) clearTimeout(_saveStateTimer)
  _saveStateTimer = setTimeout(_writeWindowState, 500)
}

function _trackNormalBounds() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  if (!mainWindow.isMaximized()) {
    _lastNormalBounds = mainWindow.getBounds()
  }
}


function createWindow() {
  devLog('BrowserWindow 생성')

  // 저장된 창 상태 로드 — 없으면 디폴트.
  const saved = loadWindowState()
  const winOpts = {
    width: saved?.width ?? 1280,
    height: saved?.height ?? 800,
    minWidth: 900,
    minHeight: 600,
    icon: path.join(__dirname, 'assets', 'icon.ico'),
    // OS 기본 frame 제거 — renderer 가 자체 타이틀바를 그림 (frontend/src/components/common/TitleBar.tsx).
    // Windows 에선 frame: false 라도 윈도우 가장자리 8px 리사이즈 영역은 그대로 유효.
    frame: false,
    backgroundColor: '#f5f5f4',  // 첫 페인트 전 흰 깜빡임 차단 (stone-100)
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      // 트레이로 hide 시에도 OCR 업로드 등 background fetch/timer 가 throttle 되지
      // 않게. Chromium 의 hidden window throttling 기본값은 활성화돼 있어,
      // 이를 끄지 않으면 창 hide 후 진행 중인 fetch/setInterval 이 지연됨.
      backgroundThrottling: false,
    },
  }
  // 저장된 좌표가 살아있는 디스플레이 안에 있을 때만 적용 — 보조 모니터 분리 후 재실행 시
  // 창이 화면 밖으로 가는 것 방지 (Electron 이 자동으로 중앙 배치).
  if (saved && saved.x != null && saved.y != null &&
      _positionInsideAnyDisplay(saved.x, saved.y)) {
    winOpts.x = saved.x
    winOpts.y = saved.y
  }
  mainWindow = new BrowserWindow(winOpts)

  // 초기 normal bounds 기록 — maximize() 호출 *전* 시점의 실제 적용된 bounds 사용.
  // 멀티모니터 가드로 winOpts 의 x/y 가 빠진 경우 (보조 모니터 분리 후 재실행 등) Electron 이
  // 중앙 배치한 실제 좌표를 반환하므로, saved 값을 직접 쓰는 것보다 안전 (화면 밖 좌표 회피).
  _lastNormalBounds = mainWindow.getBounds()

  // maximize 였으면 복원
  if (saved?.isMaximized) mainWindow.maximize()

  // 상태 변경 이벤트 → 저장 (debounced)
  mainWindow.on('resize', () => { _trackNormalBounds(); saveWindowState() })
  mainWindow.on('move', () => { _trackNormalBounds(); saveWindowState() })
  mainWindow.on('maximize', saveWindowState)
  mainWindow.on('unmaximize', saveWindowState)

  // 마이크/카메라/클립보드/전체화면 권한 자동 허가 (Electron 단독 앱 — 외부 사이트 아님).
  // fullscreen: 강의자 발표 모드 (Lecturer.tsx) 에서 requestFullscreen() 호출용. 없으면 deny.
  const _allowedPermissions = new Set([
    'media',
    'mediaKeySystem',
    'clipboard-read',
    'clipboard-sanitized-write',
    'fullscreen',
  ])
  mainWindow.webContents.session.setPermissionRequestHandler((_wc, permission, callback) => {
    const ok = _allowedPermissions.has(permission)
    devLog(`권한 요청: ${permission} → ${ok ? 'allow' : 'deny'}`)
    callback(ok)
  })
  // navigator.permissions.query() 호출 시도 동기 응답
  mainWindow.webContents.session.setPermissionCheckHandler((_wc, permission) => {
    return _allowedPermissions.has(permission)
  })

  if (isDev) {
    const url = `http://127.0.0.1:${FRONTEND_PORT}/#/install`
    devLog(`loadURL: ${url}`)
    mainWindow.loadURL(url)
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    // 프로덕션: 백엔드 HTTP 서버가 frontend dist를 서빙하므로 거기서 로드.
    // file://은 Chromium secure context 미충족으로 getUserMedia(마이크/카메라) 차단됨.
    // file:// splash 후 swap 방식은 IPC race(file://에서 ready 받고 navigate → swap → http://에서 ready 신호 유실)
    // 가 발생하므로, 백엔드 HTTP 응답까지 대기 후 단일 loadURL.
    devLog('프로덕션: 백엔드 HTTP 응답 대기 후 loadURL — 1~3초 소요 가능')
    waitForHealth((ok) => {
      if (!mainWindow || mainWindow.isDestroyed()) return
      if (!ok) {
        devLog('waitForHealth 실패 — file://로 폴백 (마이크 안 될 수 있음)')
        mainWindow.loadFile(path.join(__dirname, '../dist/index.html'), { hash: '/install' })
        return
      }
      const url = `http://127.0.0.1:${BACKEND_PORT}/#/install`
      devLog(`백엔드 HTTP 준비 완료 → loadURL: ${url}`)
      mainWindow.loadURL(url)
    })
  }

  // 자체 타이틀바 (frame: false) 에서 max/restore 아이콘 토글에 필요한 상태 통지
  mainWindow.on('maximize', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('window-maximized-change', true)
    }
  })
  mainWindow.on('unmaximize', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('window-maximized-change', false)
    }
  })

  mainWindow.webContents.on('did-finish-load', () => {
    devLog('renderer did-finish-load')
  })
  mainWindow.webContents.on('did-fail-load', (_e, code, desc, url) => {
    devLog(`renderer did-fail-load: code=${code} desc="${desc}" url=${url}`)
  })
  mainWindow.webContents.on('render-process-gone', (_e, details) => {
    devLog(`renderer crashed: ${JSON.stringify(details)}`)
  })

  mainWindow.once('ready-to-show', () => {
    devLog('ready-to-show → window.show()')
    mainWindow.show()
  })

  // 창 X 버튼 → 종료 대신 트레이로 hide (백그라운드 OCR/업로드 유지).
  // 실제 종료는 isQuitting=true 일 때만 (트레이 "종료" 메뉴, before-quit, quit-app IPC).
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault()
      mainWindow.hide()
      devLog('창 닫기 가로채기 → 트레이로 hide')
      return
    }
    // 실제 종료 — pending debounce 가 디스크에 못 쓰고 destroy 될 가능성 차단
    if (_saveStateTimer) {
      clearTimeout(_saveStateTimer)
      _saveStateTimer = null
    }
    _writeWindowState()
  })
}

// ─── 트레이 아이콘 + 컨텍스트 메뉴 ────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray-icon-32.png')
  const icon = nativeImage.createFromPath(iconPath)
  if (icon.isEmpty()) {
    devLog(`[경고] 트레이 아이콘 로드 실패: ${iconPath}`)
  }
  tray = new Tray(icon)
  tray.setToolTip('Aunion AI')

  const showWindow = () => {
    if (!mainWindow || mainWindow.isDestroyed()) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    if (!mainWindow.isVisible()) mainWindow.show()
    mainWindow.focus()
  }

  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '열기', click: showWindow },
      { type: 'separator' },
      {
        label: '종료',
        click: () => {
          devLog('트레이 종료 클릭 → app.quit()')
          isQuitting = true
          app.quit()
        },
      },
    ]),
  )
  tray.on('double-click', showWindow)
  devLog('트레이 아이콘 생성 완료')
}

// ─── 두 번째 인스턴스 실행 시도 → 기존 창 활성화 ───────────────────
// 첫 인스턴스에서만 발화. 두 번째 인스턴스는 위쪽 락 체크에서 이미 종료됨.
app.on('second-instance', (_event, commandLine) => {
  devLog(`두 번째 인스턴스 차단 — argv=${JSON.stringify(commandLine)}`)
  appendLog(`[${new Date().toISOString()}] 두 번째 인스턴스 차단 — 기존 창 활성화`)
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    if (!mainWindow.isVisible()) mainWindow.show()
    mainWindow.focus()
  }
})

app.whenReady().then(() => {
  devLog('app.whenReady → createWindow + createTray + startBackend')
  // 기본 Electron 메뉴바 제거 (File/Edit/View/Window/Help). 모든 BrowserWindow 에 적용.
  // dev devtools 는 createWindow 에서 openDevTools 로 직접 열고 있어 단축키 없어도 무방.
  Menu.setApplicationMenu(null)
  createWindow()
  createTray()
  startBackend()

  ipcMain.handle('get-lan-ip', () => getLanIp())
  ipcMain.handle('get-backend-state', () => {
    devLog(`renderer get-backend-state 요청: ${JSON.stringify({ progress: _lastState.progress, ready: _lastState.ready, hasModels: !!_lastState.models })}`)
    return _lastState
  })

  // 앱 종료 — 설치 마법사의 "취소" / "앱 종료" 버튼에서 호출.
  // 트레이 hide 분기를 우회하도록 isQuitting 먼저 set.
  ipcMain.on('quit-app', () => {
    devLog('renderer quit-app 요청 → app.quit()')
    isQuitting = true
    app.quit()
  })

  // ─── 윈도우 컨트롤 (자체 타이틀바용) ────────────────────────────────
  // close 는 mainWindow.close() → close 이벤트 → isQuitting 분기 (트레이 hide 흐름과 일치).
  ipcMain.on('window-minimize', () => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.minimize()
  })
  ipcMain.on('window-toggle-maximize', () => {
    if (!mainWindow || mainWindow.isDestroyed()) return
    if (mainWindow.isMaximized()) mainWindow.unmaximize()
    else mainWindow.maximize()
  })
  ipcMain.on('window-close', () => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.close()
  })
  ipcMain.handle('window-is-maximized', () => {
    return !!(mainWindow && !mainWindow.isDestroyed() && mainWindow.isMaximized())
  })

  // 화면 공유 picker용 — desktopCapturer로 화면/창 목록 + 썸네일 반환.
  // renderer에서 ID 선택 후 getUserMedia(chromeMediaSourceId)로 stream 획득.
  ipcMain.handle('get-screen-sources', async () => {
    const sources = await desktopCapturer.getSources({
      types: ['screen', 'window'],
      thumbnailSize: { width: 320, height: 180 },
      fetchWindowIcons: true,
    })
    return sources.map((s) => ({
      id: s.id,
      name: s.name,
      thumbnail: s.thumbnail.toDataURL(),
      appIcon: s.appIcon && !s.appIcon.isEmpty() ? s.appIcon.toDataURL() : null,
      display_id: s.display_id,
    }))
  })

  // getDisplayMedia 호출 보호 — 등록 안 하면 Electron이 'Permission denied'로 거부.
  // 우리는 자체 picker(getUserMedia + chromeMediaSourceId)로 처리하므로 이 경로는 사용 안 함.
  session.defaultSession.setDisplayMediaRequestHandler((_request, callback) => {
    callback({}) // 빈 응답 → renderer가 자체 picker로 폴백하도록 유도
  })

  const onReady = (ready) => {
    devLog(`renderer로 backend-ready=${ready} 송신`)
    if (mainWindow) mainWindow.webContents.send('backend-ready', ready)
  }

  if (isDev) {
    waitForBackend(onReady, 150)
  } else {
    waitForBackend(onReady)
  }
})

// OS 셧다운/Cmd-Q 등으로 들어오는 진짜 종료 경로 — close 핸들러 우회.
app.on('before-quit', () => {
  isQuitting = true
})

// .exe 종료 시 backend 는 일부러 안 죽임 — backend 가 부모 PID 감시해 자체적으로
// 5분 grace (학생 자막 다운로드 시간) 후 자살. 재실행 시 startBackend() 의 taskkill
// 이 이 grace 중인 backend 도 강제 kill 해 새 인스턴스로 깨끗하게 시작.
//
// 트레이 도입 후엔 X 로 모든 창이 hide 되면 window-all-closed 가 발화하지 않음
// (창은 hide 상태일 뿐 destroy 되지 않음). 따라서 이 핸들러는 거의 발화하지 않고,
// 발화하더라도 isQuitting 기준으로 정상 종료 흐름을 따름.
app.on('window-all-closed', () => {
  if (isQuitting) app.quit()
})
