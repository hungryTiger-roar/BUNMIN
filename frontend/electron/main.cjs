const { app, BrowserWindow, ipcMain } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const http = require('http')

let mainWindow = null
let backendProcess = null
let rendererReady = false
const logBuffer = []  // renderer가 준비되기 전 로그 버퍼

const isDev = process.env.NODE_ENV === 'development'
const BACKEND_PORT = 8000
const FRONTEND_PORT = 3000

// renderer로 로그 전송 (준비 전이면 버퍼에 저장)
function sendLog(log) {
  if (rendererReady && mainWindow) {
    mainWindow.webContents.send('backend-log', log)
  } else {
    logBuffer.push(log)
  }
}

// 백엔드 실행 (프로덕션에서만)
function startBackend() {
  if (isDev) return

  // process.resourcesPath는 exe 위치 기준 상대경로 → 폴더 어디로 이동해도 동작
  const resourcesPath = process.resourcesPath || path.join(path.dirname(process.execPath), 'resources')
  const backendExe = path.join(resourcesPath, 'backend', 'aunion_backend.exe')

  backendProcess = spawn(backendExe, [], {
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  })

  backendProcess.stdout.on('data', (data) => {
    const log = data.toString()
    console.log(`[Backend] ${log}`)
    sendLog(log)
  })

  backendProcess.stderr.on('data', (data) => {
    console.error(`[Backend Error] ${data}`)
  })

  backendProcess.on('close', (code) => {
    console.log(`[Backend] 종료됨 (code: ${code})`)
  })
}

// 백엔드 준비 대기 (/health 폴링, status: "ok" 될 때까지 대기)
function waitForBackend(callback, maxAttempts = 600) {
  let attempts = 0

  const check = () => {
    const req = http.get(`http://localhost:${BACKEND_PORT}/health`, (res) => {
      if (res.statusCode === 200) {
        let body = ''
        res.on('data', (chunk) => { body += chunk })
        res.on('end', () => {
          try {
            const json = JSON.parse(body)
            if (json.status === 'ok') {
              callback(true)
            } else if (json.status === 'error') {
              // 모델 로딩 실패 — 즉시 종료
              if (json.message) {
                sendLog(`[오류] ${json.message}`)
              }
              callback(false)
            } else {
              // 아직 로딩 중 — 로그 전달 후 재시도
              if (json.message) {
                sendLog(`[모델 로딩] ${json.message}`)
              }
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
    req.setTimeout(2000, () => { req.destroy(); retry() })

    function retry() {
      attempts++
      if (attempts < maxAttempts) {
        setTimeout(check, 2000)
      } else {
        callback(false)
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

  // 로딩 화면으로 시작
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

  // renderer가 준비됐다고 신호를 보내면 버퍼 flush
  ipcMain.once('renderer-ready', () => {
    rendererReady = true
    logBuffer.forEach((log) => mainWindow.webContents.send('backend-log', log))
    logBuffer.length = 0
  })

  // 개발 모드에서는 이미 백엔드가 실행 중이라고 가정
  if (isDev) {
    waitForBackend((ready) => {
      if (mainWindow) {
        mainWindow.webContents.send('backend-ready', ready)
      }
    }, 150)
  } else {
    waitForBackend((ready) => {
      if (mainWindow) {
        mainWindow.webContents.send('backend-ready', ready)
      }
    })
  }
})

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
})

app.on('window-all-closed', () => {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
  app.quit()
})
