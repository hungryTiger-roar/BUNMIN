const { app, BrowserWindow, ipcMain } = require('electron')
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

function sendLog(log) {
  if (mainWindow) mainWindow.webContents.send('backend-log', log)
}
function sendProgress(progress) {
  _lastState.progress = progress
  if (mainWindow) mainWindow.webContents.send('backend-progress', progress)
}
function sendModelStatus(models) {
  _lastState.models = models
  if (mainWindow) mainWindow.webContents.send('backend-model-status', models)
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
    },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

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

function createWindow() {
  devLog('BrowserWindow 생성')
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    show: false,
  })

  if (isDev) {
    const url = `http://127.0.0.1:${FRONTEND_PORT}/#/loading`
    devLog(`loadURL: ${url}`)
    mainWindow.loadURL(url)
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'), {
      hash: '/loading',
    })
  }

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
}

app.whenReady().then(() => {
  devLog('app.whenReady → createWindow + startBackend')
  createWindow()
  startBackend()

  ipcMain.handle('get-lan-ip', () => getLanIp())
  ipcMain.handle('get-backend-state', () => {
    devLog(`renderer get-backend-state 요청: ${JSON.stringify({ progress: _lastState.progress, ready: _lastState.ready, hasModels: !!_lastState.models })}`)
    return _lastState
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

function killBackend() {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
  try {
    require('child_process').execSync('taskkill /F /IM aunion_backend.exe /T', { stdio: 'ignore' })
  } catch {}
}

app.on('before-quit', killBackend)

app.on('window-all-closed', () => {
  killBackend()
  app.quit()
})
