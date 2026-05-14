/**
 * ISCC (Inno Setup Compiler) 실행 헬퍼
 *
 * 동기: winget 으로 설치하면 per-user 경로 (%LOCALAPPDATA%\Programs\Inno Setup 6\)
 *      라 시스템 PATH 자동 등록 안 됨. 팀원마다 설치 방식이 다를 수 있어 PATH 의존
 *      금지. 흔한 설치 경로 + PATH 를 순회하며 첫 매칭으로 실행.
 *
 * 사용: node scripts/run-iscc.js installer.iss
 *      → npm run build:installer 에서 호출.
 */
const { spawnSync, execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const ARG_ISS = process.argv[2] || 'installer.iss'

// 후보 경로 — 우선순위 순.
const candidates = []

// 1. PATH 에 등록된 ISCC (가장 빠름)
try {
  const cmd = process.platform === 'win32' ? 'where ISCC.exe' : 'which ISCC'
  const found = execSync(cmd, { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim().split(/\r?\n/)[0]
  if (found && fs.existsSync(found)) candidates.push(found)
} catch {
  // PATH 에 없음 — 다음 후보로
}

// 2. winget per-user 설치 (Windows 기본)
if (process.env.LOCALAPPDATA) {
  candidates.push(path.join(process.env.LOCALAPPDATA, 'Programs', 'Inno Setup 6', 'ISCC.exe'))
  candidates.push(path.join(process.env.LOCALAPPDATA, 'Programs', 'Inno Setup 5', 'ISCC.exe'))
}

// 3. winget / 설치파일 system-wide (관리자 권한)
candidates.push('C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe')
candidates.push('C:\\Program Files\\Inno Setup 6\\ISCC.exe')
candidates.push('C:\\Program Files (x86)\\Inno Setup 5\\ISCC.exe')
candidates.push('C:\\Program Files\\Inno Setup 5\\ISCC.exe')

// 첫 존재 경로 선택
const iscc = candidates.find((p) => fs.existsSync(p))

if (!iscc) {
  console.error('\n[run-iscc] ❌ ISCC.exe 를 찾을 수 없습니다.')
  console.error('   다음 위치에서 모두 검색 실패:')
  candidates.forEach((p) => console.error(`     - ${p}`))
  console.error('\n   해결 방법:')
  console.error('     1. winget install JRSoftware.InnoSetup')
  console.error('     2. 또는 https://jrsoftware.org/isdl.php 에서 다운로드 후 설치')
  console.error('     3. 비표준 경로에 설치한 경우 PATH 에 등록:')
  console.error('        setx PATH "%PATH%;<Inno Setup 경로>"')
  process.exit(1)
}

console.log(`[run-iscc] using: ${iscc}`)
console.log(`[run-iscc] script: ${ARG_ISS}`)

const result = spawnSync(iscc, [ARG_ISS], { stdio: 'inherit' })

if (result.error) {
  console.error('[run-iscc] 실행 실패:', result.error.message)
  process.exit(1)
}

process.exit(result.status ?? 1)
