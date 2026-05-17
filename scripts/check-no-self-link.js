#!/usr/bin/env node
/**
 * preinstall 가드 — frontend/package.json 의존성에서 자기 자신(부모 디렉토리)을
 * 가리키는 file:.. 패턴을 감지해 차단.
 *
 * 배경: 과거 누군가 frontend/ 안에서 `npm install ..` 류의 명령을 실수로 실행하면
 *   "aunion-ai": "file:.." 가 추가되며 frontend/node_modules/aunion-ai 가
 *   루트로 가는 심볼릭 링크가 생김. 루트에 다시 frontend/ 가 있으므로
 *   `frontend/node_modules/aunion-ai/frontend/node_modules/aunion-ai/...` 식으로
 *   무한 재귀 구조가 발생. git/glob/grep 등 모든 도구가 "Filename too long"
 *   오류를 토함. 한 번 더 동일 사고가 나는 걸 막기 위한 정적 검증.
 */
const fs = require('fs')
const path = require('path')

const pkgPath = path.join(__dirname, '..', 'frontend', 'package.json')
let pkg
try {
  pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'))
} catch (err) {
  // package.json 파싱 실패 — 다른 검증 도구가 잡을 문제이므로 통과
  process.exit(0)
}

const allDeps = { ...(pkg.dependencies ?? {}), ...(pkg.devDependencies ?? {}) }
const offenders = Object.entries(allDeps).filter(([, spec]) => {
  if (typeof spec !== 'string') return false
  // file:.., file:../.., link:.. 등 부모 디렉토리 자기 참조 차단
  return /^(file:|link:)\.{2}(\/|\\|$)/.test(spec)
})

if (offenders.length) {
  console.error('\n[preinstall] frontend/package.json 의존성에 자기 참조 항목 감지 — 설치 중단:')
  for (const [name, spec] of offenders) {
    console.error(`    "${name}": "${spec}"`)
  }
  console.error('\n  부모 디렉토리(`file:..`)를 자기 의존성으로 등록하면')
  console.error('  node_modules 안에 루트로 가는 심볼릭 링크가 생기고')
  console.error('  무한 재귀 디렉토리 구조가 만들어집니다.')
  console.error('  해당 항목을 제거한 뒤 다시 npm install 을 실행하세요.\n')
  process.exit(1)
}
