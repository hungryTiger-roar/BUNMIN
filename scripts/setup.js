const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

function run(cmd, opts = {}) {
  execSync(cmd, { stdio: 'inherit', cwd: ROOT, ...opts })
}

function runSilent(cmd) {
  try {
    execSync(cmd, { cwd: ROOT, stdio: 'pipe' })
    return true
  } catch {
    return false
  }
}

function runOutput(cmd) {
  try {
    return execSync(cmd, { cwd: ROOT, stdio: 'pipe' }).toString().trim()
  } catch {
    return ''
  }
}

function step(n, total, label) {
  console.log(`\n[${n}/${total}] ${label}`)
}

console.log('========================================')
console.log('  Aunion AI 환경 설정')
console.log('========================================')

// ── 사전 확인: conda ───────────────────────────────────────────────────────
const condaVersion = runOutput('conda --version')
if (!condaVersion) {
  console.error('\n[오류] conda를 찾을 수 없습니다.')
  console.error('  Miniconda 또는 Anaconda를 먼저 설치해주세요:')
  console.error('  https://docs.conda.io/en/latest/miniconda.html')
  process.exit(1)
}
console.log(`\n  conda 확인: ${condaVersion}`)

// ── 사전 확인: node / npm ─────────────────────────────────────────────────
const nodeVersion = runOutput('node --version')
const npmVersion  = runOutput('npm --version')
console.log(`  node: ${nodeVersion}  /  npm: ${npmVersion}`)

const TOTAL = 7

// 1. 루트 npm 패키지
step(1, TOTAL, '루트 npm 패키지 설치...')
run('npm install')
console.log('  완료')

// 2. 프론트엔드 npm 패키지
step(2, TOTAL, '프론트엔드 npm 패키지 설치...')
run('npm install --prefix frontend')

// 2-a. VAD ONNX 모델 복사 (*.onnx는 .gitignore에 포함 → clone 후 없음)
//      node_modules/@ricky0123/vad-web/dist/ → frontend/public/
{
  const vadDist  = path.join(ROOT, 'frontend', 'node_modules', '@ricky0123', 'vad-web', 'dist')
  const publicDir = path.join(ROOT, 'frontend', 'public')
  const vadFiles  = ['silero_vad_legacy.onnx', 'silero_vad_v5.onnx']

  let anyMissing = false
  for (const f of vadFiles) {
    const dst = path.join(publicDir, f)
    if (fs.existsSync(dst)) {
      console.log(`  ${f} 이미 존재 → 스킵`)
      continue
    }
    const src = path.join(vadDist, f)
    if (fs.existsSync(src)) {
      fs.mkdirSync(publicDir, { recursive: true })
      fs.copyFileSync(src, dst)
      console.log(`  ✓ ${f} 복사 완료`)
    } else {
      console.warn(`  ⚠️  ${f} 소스 없음 (node_modules가 설치됐는지 확인)`)
      anyMissing = true
    }
  }
  if (!anyMissing) console.log('  VAD 모델 파일 준비 완료')
}

// 3. .env 파일
step(3, TOTAL, '환경 설정 파일 확인...')
const envPath        = path.join(ROOT, '.env')
const envExamplePath = path.join(ROOT, '.env.example')
if (fs.existsSync(envPath)) {
  console.log('  .env 이미 존재 → 스킵')
} else if (fs.existsSync(envExamplePath)) {
  fs.copyFileSync(envExamplePath, envPath)
  console.log('  .env 생성 완료 (.env.example 복사)')
  console.log('  ※ HF_TOKEN은 선택사항 (공개 모델은 토큰 없이 다운로드 가능)')
  console.log('    빠른 다운로드 원하면: https://huggingface.co/settings/tokens')
} else {
  console.log('  ⚠️  .env.example 없음 — .env를 수동으로 만들어주세요.')
}

// 4. conda aunion 환경
step(4, TOTAL, 'conda 환경 확인...')
const envExists = runSilent('conda run -n aunion python --version')
if (envExists) {
  console.log('  aunion 환경 이미 존재 → 스킵')
} else {
  console.log('  aunion 환경 생성 중 (Python 3.11)...')
  run('conda create -n aunion python=3.11 -y')
  console.log('  완료')
}

// 5. Python 패키지
step(5, TOTAL, 'Python 패키지 설치...')

// 5-a. requirements.txt (faster-whisper, ctranslate2 등 포함)
console.log('  requirements.txt 설치 중...')
run('conda run --no-capture-output -n aunion pip install -r backend/requirements.txt')

// 5-b. numpy / Pillow 정확 버전 고정 — torch 설치 전에 먼저 고정해야 덮어쓰기를 막을 수 있음
// Windows CMD에서 >=, < 가 리다이렉션 연산자로 해석되므로 == 사용
console.log('  numpy / Pillow 버전 고정 중...')
run('conda run --no-capture-output -n aunion pip install --force-reinstall numpy==1.26.4 Pillow==10.4.0')

// 5-c. torch CUDA — CUDA 버전이 이미 있으면 스킵, 없으면 --no-deps 로 설치
// --no-deps: 설치 중 numpy/Pillow가 다시 덮어써지는 것을 방지
const hasCudaTorch = runSilent(
  "conda run --no-capture-output -n aunion python -c \"import torch; assert 'cu' in torch.__version__\""
)
if (hasCudaTorch) {
  console.log('  torch CUDA 버전 이미 설치됨 → 스킵')
} else {
  console.log('  torch CUDA 버전 설치 중 (cu126)...')
  run(
    'conda run --no-capture-output -n aunion pip install --no-deps' +
    ' torch torchvision torchaudio' +
    ' --index-url https://download.pytorch.org/whl/cu126'
  )
  console.log('  torch 설치 완료')
}
console.log('  완료')

// 6. AI 모델 다운로드
step(6, TOTAL, 'AI 모델 다운로드...')
run('conda run --no-capture-output -n aunion python scripts/download_models.py')

// 7. 최종 검증
step(7, TOTAL, '설치 검증...')
{
  let ok = true

  // VAD ONNX 파일 확인
  const publicDir = path.join(ROOT, 'frontend', 'public')
  for (const f of ['silero_vad_legacy.onnx', 'silero_vad_v5.onnx']) {
    if (!fs.existsSync(path.join(publicDir, f))) {
      console.error(`  ✗ 누락: frontend/public/${f}`)
      ok = false
    }
  }

  // TTS 모델 파일 확인
  const ttsDir = path.join(ROOT, 'backend', 'app', 'services', 'models')
  for (const f of ['en_US-lessac-medium.onnx', 'en_US-lessac-medium.onnx.json']) {
    if (!fs.existsSync(path.join(ttsDir, f))) {
      console.error(`  ✗ 누락: backend/app/services/models/${f}`)
      ok = false
    }
  }

  // NMT CTranslate2 모델 확인
  const nmtDir = path.join(ROOT, 'models', 'opus-mt-ct2')
  if (!fs.existsSync(nmtDir)) {
    console.error('  ✗ 누락: models/opus-mt-ct2/ (NMT CTranslate2 변환 실패)')
    ok = false
  }

  // .env 확인
  if (!fs.existsSync(path.join(ROOT, '.env'))) {
    console.error('  ✗ 누락: .env')
    ok = false
  }

  if (ok) {
    console.log('  모든 파일 확인 완료 ✓')
  } else {
    console.error('\n  ⚠️  일부 파일이 누락됐습니다. 위 오류를 확인하세요.')
  }
}

console.log('\n========================================')
console.log('  Setup 완료!')
console.log('  npm run dev 로 서버를 시작하세요.')
console.log('========================================\n')
