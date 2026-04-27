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

// VAD(음성 감지) onnx 모델 파일 복사
console.log('  VAD 모델 파일 복사 중...')
const vadSrc = path.join(ROOT, 'frontend/node_modules/@ricky0123/vad-web/dist')
const vadDest = path.join(ROOT, 'frontend/public')
const vadFiles = ['silero_vad_legacy.onnx', 'silero_vad_v5.onnx']
vadFiles.forEach(file => {
  const src = path.join(vadSrc, file)
  const dest = path.join(vadDest, file)
  if (fs.existsSync(src)) {
    fs.copyFileSync(src, dest)
  }
})
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

// numpy/Pillow 버전 고정 (surya-ocr, unbabel-comet 호환)
// CMD에서 <, > 문자가 리다이렉션으로 해석되므로 특정 버전 지정
console.log('  numpy/Pillow 버전 고정 중...')
run('conda run --no-capture-output -n aunion pip install --force-reinstall numpy==1.26.4 Pillow==10.4.0')

// torch CUDA 버전 설치 (--no-deps로 numpy/Pillow 덮어쓰기 방지)
console.log('  torch CUDA 버전 설치 중 (cu126)...')
run('conda run --no-capture-output -n aunion pip install --no-deps --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126')
console.log('  완료')

// 6. AI 모델 다운로드
step(6, 6, 'AI 모델 다운로드...')
run('conda run --no-capture-output -n aunion python scripts/download_models.py')

console.log('\n========================================')
console.log('  Setup 완료!')
console.log('  npm run dev 로 서버를 시작하세요.')
console.log('========================================\n')
