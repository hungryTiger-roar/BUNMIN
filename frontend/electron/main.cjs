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

// ─── renderer 메시지 전송 ───────────────────────────────────────
function sendLog(log) {
  if (mainWindow) mainWindow.webContents.send('backend-log', log)
}
function sendProgress(progress) {
  if (mainWindow) mainWindow.webContents.send('backend-progress', progress)
}
function sendModelStatus(models) {
  if (mainWindow) mainWindow.webContents.send('backend-model-status', models)
}

// ─── 백엔드 준비 신호 (한 번만 호출) ─────────────────────────────
// stdout(__AUNION_STATUS__) 또는 health 폴링 중 먼저 도착하는 쪽이 호출.
// 타임아웃도 이 함수를 통해 처리.
let _notifyReady = null

function notifyReady(success) {
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
          if (s.status === 'ok') {
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
  const healthUrl = isDev
    ? `http://localhost:${BACKEND_PORT}/health`
    : `http://localhost:${HEALTH_PORT}/`

  const check = () => {
    const req = http.get(healthUrl, (res) => {
      if (res.statusCode === 200) {
        let body = ''
        res.on('data', (chunk) => { body += chunk })
        res.on('end', () => {
          try {
            const json = JSON.parse(body)
            if (json.status === 'ok') {
              sendProgress(100)
              if (json.models) sendModelStatus(json.models)
              notifyReady(true)
            } else if (json.status === 'error') {
              if (json.message) sendLog(`[오류] ${json.message}`)
              notifyReady(false)
            } else {
              // 로딩 중 — 진행률만 보조 업데이트 (stdout이 주)
              if (typeof json.progress === 'number') sendProgress(json.progress)
              if (json.models) sendModelStatus(json.models)
              retry()
            }
          } catch {
            retry()
          }
        })
      } else {
        retry()
      }
    })
    req.on('error', retry)
    req.setTimeout(10000, () => { req.destroy(); retry() })

    function retry() {
      attempts++
      if (attempts % 15 === 0) {
        const elapsed = Math.floor(attempts * 2 / 60)
        sendLog(`[대기] 모델 로딩 중... (${elapsed}분 경과, 다운로드 시 최대 60분 소요)`)
      }
      if (_notifyReady && attempts < maxAttempts) {
        setTimeout(check, 2000)
      } else if (_notifyReady) {
        // 60분 초과 — 최후의 수단으로 실패 처리
        notifyReady(false)
      }
    }
  }

  setTimeout(check, 1000)
}

function createWindow() {
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
    mainWindow.loadURL(`http://localhost:${FRONTEND_PORT}/#/loading`)
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'), {
      hash: '/loading',
    })
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
  })
}

app.whenReady().then(() => {
  createWindow()
  startBackend()

  ipcMain.handle('get-lan-ip', () => getLanIp())

  if (isDev) {
    waitForBackend((ready) => {
      if (mainWindow) mainWindow.webContents.send('backend-ready', ready)
    }, 150)
  } else {
    waitForBackend((ready) => {
      if (mainWindow) mainWindow.webContents.send('backend-ready', ready)
    })
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
