// dev / electron:dev 실행 전에 자동 호출되는 환경 점검 스크립트.
// conda env "aunion"이 없으면 npm run setup을 자동 실행한다.
const { execSync, spawnSync } = require('child_process')

function hasCommand(cmd) {
  const r = spawnSync(cmd, ['--version'], { stdio: 'pipe', shell: true })
  return r.status === 0
}

function envExists() {
  const r = spawnSync('conda', ['run', '-n', 'aunion', 'python', '--version'], {
    stdio: 'pipe',
    shell: true,
  })
  return r.status === 0
}

if (!hasCommand('conda')) {
  console.error('\n[ensure-env] conda를 찾을 수 없습니다.')
  console.error('  Miniconda 또는 Anaconda를 먼저 설치해주세요:')
  console.error('  https://docs.conda.io/en/latest/miniconda.html\n')
  process.exit(1)
}

if (envExists()) {
  console.log('[ensure-env] conda env "aunion" 확인 완료')
  process.exit(0)
}

console.log('[ensure-env] conda env "aunion" 없음 — npm run setup 자동 실행')
console.log('  (최초 실행 시 모델 다운로드 포함하여 10~30분 소요)')
try {
  execSync('npm run setup', { stdio: 'inherit' })
} catch (e) {
  console.error('\n[ensure-env] setup 실패. 위 오류를 확인하세요.')
  process.exit(1)
}
