const { execSync, execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

function run(cmd, opts = {}) {
  execSync(cmd, { stdio: 'inherit', cwd: ROOT, ...opts })
}

// 출력을 콘솔과 로그 파일에 동시에 저장. 실패 시 ERROR 줄만 모아 다시 출력
// → 긴 pip install 도중 진짜 에러가 스크롤백을 넘어가는 문제 방지
function runWithLog(cmd, logName) {
  const logPath = path.join(ROOT, logName)
  console.log(`  (전체 로그: ${logPath})`)
  try {
    if (process.platform === 'win32') {
      // PowerShell Tee-Object: 콘솔 + 파일 동시 출력, 내부 명령 종료 코드 보존
      const psCmd =
        `$ErrorActionPreference='Continue'; ` +
        `& { ${cmd} } 2>&1 | Tee-Object -FilePath '${logPath.replace(/'/g, "''")}'; ` +
        `exit $LASTEXITCODE`
      execFileSync('powershell', ['-NoProfile', '-NonInteractive', '-Command', psCmd], {
        cwd: ROOT, stdio: 'inherit',
      })
    } else {
      // bash: pipefail로 파이프 내부 종료 코드 보존
      execSync(`set -o pipefail; ${cmd} 2>&1 | tee "${logPath}"`, {
        cwd: ROOT, stdio: 'inherit', shell: '/bin/bash',
      })
    }
  } catch (err) {
    if (fs.existsSync(logPath)) {
      const lines = fs.readFileSync(logPath, 'utf-8').split(/\r?\n/)
      const errorLines = lines.filter(l =>
        /^\s*ERROR/i.test(l) || /\berror: /i.test(l) || /^\s*fatal:/i.test(l)
      )
      if (errorLines.length) {
        console.error('\n  ▼ 에러 요약 (전체 로그는 위 경로 참조) ▼')
        errorLines.slice(-30).forEach(l => console.error('    ' + l.trim()))
      } else {
        console.error(`\n  ✗ 실패. 전체 로그: ${logPath}`)
      }
    }
    throw err
  }
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
  // 4-a. Anaconda 기본 채널 TOS 자동 수락 (최신 conda에서 필수, 멱등)
  //      구버전 conda에는 `tos` 서브커맨드가 없으므로 실패해도 무시
  const tosChannels = [
    'https://repo.anaconda.com/pkgs/main',
    'https://repo.anaconda.com/pkgs/r',
    'https://repo.anaconda.com/pkgs/msys2',
  ]
  for (const ch of tosChannels) {
    runSilent(`conda tos accept --override-channels --channel ${ch}`)
  }

  console.log('  aunion 환경 생성 중 (Python 3.11)...')
  // 기본 채널 시도 → 실패 시 conda-forge 로 폴백 (TOS 불필요)
  const created = runSilent('conda create -n aunion python=3.11 -y')
  if (!created) {
    console.log('  기본 채널 실패 → conda-forge 채널로 재시도...')
    run('conda create -n aunion python=3.11 -y -c conda-forge --override-channels')
  }
  console.log('  완료')
}

// 5. Python 패키지
step(5, TOTAL, 'Python 패키지 설치...')

// 5-a. requirements.txt (faster-whisper, ctranslate2 등 포함)
console.log('  requirements.txt 설치 중...')
runWithLog(
  'conda run --no-capture-output -n aunion pip install -r backend/requirements.txt',
  'setup-pip.log'
)

// 5-b. numpy / Pillow 정확 버전 고정 — torch 설치 전에 먼저 고정해야 덮어쓰기를 막을 수 있음
// Windows CMD에서 >=, < 가 리다이렉션 연산자로 해석되므로 == 사용
console.log('  numpy / Pillow 버전 고정 중...')
run('conda run --no-capture-output -n aunion pip install --force-reinstall numpy==1.26.4 Pillow==10.4.0')

// 5-c. torch CUDA — NVIDIA GPU가 있을 때만 cu126 휠로 교체
//      requirements.txt 설치 중 surya-ocr 등이 PyPI의 CPU torch를 끌어올 수 있으므로,
//      이미 CPU 버전이 설치돼 있어도 --force-reinstall 로 강제 교체해야 함
//      (그냥 pip install 하면 "이미 설치됨"으로 판단해 no-op 됨)
//      --no-deps: 위에서 pin한 numpy/Pillow가 덮어써지지 않도록 유지
const hasNvidiaGpu = runSilent('nvidia-smi')
const hasCudaTorch = runSilent(
  "conda run --no-capture-output -n aunion python -c \"import torch; assert 'cu' in torch.__version__\""
)
if (hasCudaTorch) {
  console.log('  torch CUDA 버전 이미 설치됨 → 스킵')
} else if (hasNvidiaGpu) {
  console.log('  NVIDIA GPU 감지 → torch CUDA 버전 설치 중 (cu126)...')
  run(
    'conda run --no-capture-output -n aunion pip install --force-reinstall --no-deps' +
    ' torch torchvision torchaudio' +
    ' --index-url https://download.pytorch.org/whl/cu126'
  )
  console.log('  torch 설치 완료')
} else {
  console.log('  ⚠️ NVIDIA GPU 미감지(nvidia-smi 실패) → CPU 버전 torch 유지')
  console.log('     VLM 번역 등 GPU 필요 기능은 동작하지 않습니다.')
  console.log('     GPU가 있는데도 이 메시지가 보이면 NVIDIA 드라이버를 확인하세요.')
}
console.log('  완료')

// 6. AI 모델 다운로드
step(6, TOTAL, 'AI 모델 다운로드...')
runWithLog(
  'conda run --no-capture-output -n aunion python scripts/download_models.py',
  'setup-models.log'
)

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

  // NMT CTranslate2 모델 확인 — 필수 파일 5개 모두 존재해야 함
  // (sentencepiece spm 파일 누락 시 nmt_service가 HF 폴백으로 떨어져 성능 저하)
  const nmtDir = path.join(ROOT, 'models', 'opus-mt-ct2')
  for (const f of ['model.bin', 'config.json', 'shared_vocabulary.json', 'source.spm', 'target.spm']) {
    if (!fs.existsSync(path.join(nmtDir, f))) {
      console.error(`  ✗ 누락: models/opus-mt-ct2/${f} (NMT CTranslate2 부분 변환)`)
      ok = false
    }
  }

  // VLM LoRA 어댑터 확인
  const loraDir = path.join(ROOT, 'models', 'qwen3', 'qwen3-vl-8b-lora-r64-e3-final')
  if (!fs.existsSync(loraDir)) {
    console.error('  ✗ 누락: models/qwen3/qwen3-vl-8b-lora-r64-e3-final/ (VLM LoRA)')
    ok = false
  }

  // VLM Base 모델 확인 — 로컬 디렉토리 + safetensors 4 shards 존재
  // HF 캐시 대신 평탄 디렉토리 사용으로 Windows 심볼릭 이슈 우회
  const vlmBaseDir = path.join(ROOT, 'models', 'qwen3-vl-8b-instruct')
  if (!fs.existsSync(vlmBaseDir)) {
    console.error('  ✗ 누락: models/qwen3-vl-8b-instruct/ (VLM Base)')
    ok = false
  } else {
    const shards = fs.readdirSync(vlmBaseDir).filter(f => f.endsWith('.safetensors'))
    const totalBytes = shards.reduce(
      (sum, f) => sum + fs.statSync(path.join(vlmBaseDir, f)).size, 0
    )
    const sizeGb = totalBytes / (1024 ** 3)
    if (shards.length < 4 || sizeGb < 5) {
      console.error(
        `  ✗ VLM Base 부분 다운로드 (shards ${shards.length}/4, ${sizeGb.toFixed(2)}GB / 16GB 기대)`
      )
      console.error('     conda run -n aunion python scripts/download_models.py 로 재실행')
      ok = false
    }
  }

  // ASR 모델 (faster-whisper) — 로컬 디렉토리 + model.bin
  const asrDir = path.join(ROOT, 'models', 'asr-faster-whisper-large-v3-turbo-ko')
  if (!fs.existsSync(path.join(asrDir, 'model.bin'))) {
    console.error('  ✗ 누락: models/asr-faster-whisper-large-v3-turbo-ko/model.bin (ASR)')
    ok = false
  }

  // RapidOCR Korean 모델 — 로컬 디렉토리 + 핵심 파일 2개
  const rapidocrDir = path.join(ROOT, 'models', 'rapidocr-korean')
  for (const f of ['model.onnx', 'korean_dict.txt']) {
    if (!fs.existsSync(path.join(rapidocrDir, f))) {
      console.error(`  ✗ 누락: models/rapidocr-korean/${f}`)
      ok = false
    }
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
