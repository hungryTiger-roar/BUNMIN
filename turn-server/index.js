// Aunion AI 로컬 TURN 서버
//
// 목적: SSAFY 강의실 같은 보안 환경에서 client-to-client(P2P) 차단으로
//       원본 음성(WebRTC) 이 끊기는 문제 해결. client → 같은 LAN 의 이 TURN 서버 →
//       다른 client 로 relay 하므로 P2P 차단 정책에 안 걸림.
//
// 사용:
//   node turn-server/index.js
//
// iceServers 설정 (Lecturer.tsx / Student.tsx 에서):
//   { urls: `turn:${hostname}:47878`, username: 'aunion', credential: 'aunion-secret' }
//   { urls: `turn:${hostname}:47878?transport=tcp`, ... }   // UDP 차단 시 fallback
//
// 포트 47878: TURN 표준 3478 은 Teams/Zoom 등이 자주 점유 → 충돌 회피용 임의 포트.

const Turn = require('node-turn')

const server = new Turn({
  listeningPort: 47878,
  listeningIps: ['0.0.0.0'],          // 모든 인터페이스 바인드 — LAN 의 모든 단말 도달 가능
  authMech: 'long-term',
  credentials: {
    aunion: 'aunion-secret',          // 강의자/수강자 양쪽이 사용
  },
  realm: 'aunion.local',
  debugLevel: 'INFO',                 // ERROR/WARN/INFO/DEBUG/TRACE
})

server.start()

const os = require('os')
const ifaces = os.networkInterfaces()
const lanIps = []
for (const name of Object.keys(ifaces)) {
  for (const iface of ifaces[name]) {
    if (iface.family === 'IPv4' && !iface.internal) {
      lanIps.push(iface.address)
    }
  }
}

console.log('========================================')
console.log('  Aunion AI 로컬 TURN 서버')
console.log('========================================')
console.log(`  포트: 47878 (UDP + TCP)`)
console.log(`  인증: long-term (user: aunion)`)
console.log(`  LAN IP: ${lanIps.join(', ')}`)
console.log(`  → 수강자들은 위 IP 중 하나로 접속`)
console.log('========================================')
