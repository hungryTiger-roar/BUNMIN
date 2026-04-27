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

function step(n, total, label) {
  console.log(`\n[${n}/${total}] ${label}`)
}

console.log('========================================')
console.log('  Aunion AI 환경 설정')
console.log('========================================')

// 1. 루트 npm 패키지
step(1, 6, '루트 npm 패키지 설치...')
run('npm install')
console.log('  완료')

// 2. 프론트엔드 npm 패키지
step(2, 6, '프론트엔드 npm 패키지 설치...')
run('npm install --prefix frontend')
console.log('  완료')

// 3. .env 파일
step(3, 6, '환경 설정 파일 확인...')
const envPath = path.join(ROOT, '.env')
const envExamplePath = path.join(ROOT, '.env.example')
if (fs.existsSync(envPath)) {
  console.log('  .env 이미 존재 → 스킵')
} else if (fs.existsSync(envExamplePath)) {
  fs.copyFileSync(envExamplePath, envPath)
  console.log('  .env 생성 완료 (.env.example 복사)')
  console.log('  ⚠️  .env 파일을 열어 HF_TOKEN과 PYTHON_PATH를 설정해주세요.')
} else {
  console.log('  ⚠️  .env.example 없음 — .env를 수동으로 만들어주세요.')
}

// 4. conda aunion 환경
step(4, 6, 'conda 환경 확인...')
const envList = runSilent('conda env list')
const envExists = runSilent('conda run -n aunion python --version')
if (envExists) {
  console.log('  aunion 환경 이미 존재 → 스킵')
} else {
  console.log('  aunion 환경 생성 중 (Python 3.11)...')
  run('conda create -n aunion python=3.11 -y')
  console.log('  완료')
}

// 5. Python 패키지
step(5, 6, 'Python 패키지 설치...')
run('conda run --no-capture-output -n aunion pip install -r backend/requirements.txt')

// requirements.txt 설치 후 surya-ocr 등이 torch를 CPU 버전으로 교체할 수 있으므로 강제 재설치
console.log('  torch CUDA 버전 재설치 중 (cu126)...')
run('conda run --no-capture-output -n aunion pip install --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126')

run('conda run --no-capture-output -n aunion pip install "numpy>=1.24.0,<2.0.0" "Pillow>=10.2.0,<11.0.0"')
console.log('  완료')

// 6. AI 모델 다운로드
step(6, 6, 'AI 모델 다운로드...')
run('conda run --no-capture-output -n aunion python scripts/download_models.py')

console.log('\n========================================')
console.log('  Setup 완료!')
console.log('  npm run dev 로 서버를 시작하세요.')
console.log('========================================\n')
