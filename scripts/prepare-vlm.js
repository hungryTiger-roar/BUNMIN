/**
 * VLM (Qwen3-VL-4B) 평탄 디렉토리를 빌드 입력으로 준비.
 *
 * 인스톨러 빌드 직전(`build:installer` 단계) 실행 → electron-builder.json 의
 * extraResources from: "models/qwen3-vl-4b-instruct" 가 가져갈 소스를 만들어 둠.
 *
 * 우선순위:
 *   1) <repo>/models/qwen3-vl-4b-instruct 가 이미 평탄(가중치 포함) → 스킵
 *   2) %LOCALAPPDATA%/Aunion AI/cache/huggingface/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/<hash>/
 *      에서 가져옴 (이미 설치본이 받아둔 ~8GB) — junction 시도 후 실패 시 복사
 *   3) 둘 다 없으면 명확한 에러 메시지 (사용자가 설치본 실행으로 받게 안내)
 *
 * idempotent: 이미 준비돼 있으면 아무것도 안 함.
 * 디스크: junction 성공 시 +0GB, 복사 fallback 시 +8GB.
 */
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')
const os = require('os')

const ROOT = path.resolve(__dirname, '..')
const TARGET_DIR = path.join(ROOT, 'models', 'qwen3-vl-4b-instruct')
const HF_CACHE = path.join(
  process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'),
  'Aunion AI', 'cache', 'huggingface', 'hub', 'models--Qwen--Qwen3-VL-4B-Instruct'
)

const C = process.stdout.isTTY ? {
  green:'\x1b[32m', red:'\x1b[31m', yellow:'\x1b[33m', cyan:'\x1b[36m', reset:'\x1b[0m',
} : { green:'', red:'', yellow:'', cyan:'', reset:'' }

function hasWeights(dir) {
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return false
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
    return entries.some(e => e.isFile() && /\.(safetensors|bin|onnx|pt|pth)$/.test(e.name))
  } catch { return false }
}

function findLatestSnapshot(hfCacheDir) {
  const snapDir = path.join(hfCacheDir, 'snapshots')
  if (!fs.existsSync(snapDir)) return null
  const candidates = fs.readdirSync(snapDir, { withFileTypes: true })
    .filter(e => e.isDirectory())
    .map(e => path.join(snapDir, e.name))
    .filter(hasWeights)
  if (candidates.length === 0) return null
  // 가장 최근 mtime
  return candidates
    .map(p => ({ p, mtime: fs.statSync(p).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime)[0].p
}

function tryJunction(src, dst) {
  try {
    execSync(`mklink /J "${dst}" "${src}"`, { stdio: 'pipe', shell: 'cmd.exe' })
    return true
  } catch (e) {
    return false
  }
}

function copyRecursive(src, dst) {
  fs.mkdirSync(dst, { recursive: true })
  fs.cpSync(src, dst, { recursive: true })
}

console.log(`${C.cyan}[prepare-vlm] VLM 평탄 디렉토리 준비 중...${C.reset}`)

// 1) 이미 준비됨 (가중치 파일이 직접 있음 — junction 이든 복사든 OK)
if (hasWeights(TARGET_DIR)) {
  console.log(`  ${C.green}✓${C.reset} 이미 준비됨: ${TARGET_DIR}`)
  process.exit(0)
}

// 디렉토리는 있는데 가중치 없음 → 비어있다고 보고 진행 (junction 이 dst 디렉토리 없어야 됨)
if (fs.existsSync(TARGET_DIR)) {
  const entries = fs.readdirSync(TARGET_DIR)
  if (entries.length === 0) {
    fs.rmdirSync(TARGET_DIR)  // 빈 디렉토리 제거
  } else {
    console.error(`  ${C.red}✗${C.reset} ${TARGET_DIR} 에 가중치는 없는데 다른 파일이 있음.`)
    console.error('     수동 정리 필요 (안전을 위해 자동 삭제 안 함).')
    process.exit(1)
  }
}

// 2) HF 캐시에서 snapshot 찾기
const snap = findLatestSnapshot(HF_CACHE)
if (!snap) {
  console.error(`  ${C.red}✗${C.reset} VLM 캐시를 찾지 못했습니다.`)
  console.error(`     기대 경로: ${HF_CACHE}/snapshots/<hash>/`)
  console.error('     → 설치본 Aunion AI 를 한 번 실행해 첫 다운로드를 받거나,')
  console.error('     → HF 에서 직접 받아 models/qwen3-vl-4b-instruct/ 에 평탄 배치하세요.')
  process.exit(1)
}

console.log(`  ${C.cyan}소스:${C.reset} ${snap}`)
console.log(`  ${C.cyan}대상:${C.reset} ${TARGET_DIR}`)

// 부모 디렉토리 보장
fs.mkdirSync(path.dirname(TARGET_DIR), { recursive: true })

// 3) Junction 시도 (디스크 절약). Windows 한정. 실패 시 복사.
if (process.platform === 'win32' && tryJunction(snap, TARGET_DIR)) {
  console.log(`  ${C.green}✓${C.reset} junction 생성 완료 (디스크 추가 사용 없음)`)
  process.exit(0)
}

// 4) Junction 실패 → 복사 fallback (~8GB)
console.log(`  ${C.yellow}junction 실패 → 복사 fallback (~8GB, 수 분 소요)${C.reset}`)
const start = Date.now()
copyRecursive(snap, TARGET_DIR)
const elapsed = ((Date.now() - start) / 1000).toFixed(1)
console.log(`  ${C.green}✓${C.reset} 복사 완료 (${elapsed}초)`)
