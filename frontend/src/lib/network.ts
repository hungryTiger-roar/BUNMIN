// LAN IP 조회 — backend /network/info 에서 받아옴. 캐시 후 재사용.
//
// 사용처: WebRTC iceServers 의 TURN URL 구성.
// 강사가 Electron 운영판에서 http://127.0.0.1:48000 으로 로드될 때 hostname 이 127.0.0.1 이라
// 단순히 window.location.hostname 을 쓰면 학생이 다른 머신에서 도달 불가.
// /network/info 의 lan_ip 를 쓰면 강사·학생 양쪽 머신에서 동일한 TURN host 가 보장됨.
//
// fallback: /network/info 호출 실패 시 window.location.hostname (dev 환경 호환).
import { API_BASE } from './api'

let lanIpPromise: Promise<string> | null = null

function fetchLanIp(): Promise<string> {
  return fetch(`${API_BASE}/network/info`)
    .then((r) => {
      if (!r.ok) throw new Error(`status ${r.status}`)
      return r.json()
    })
    .then((d: { lan_ip?: string }) => {
      if (!d.lan_ip) throw new Error('lan_ip missing')
      return d.lan_ip
    })
    .catch((err) => {
      console.warn('[Network] LAN IP 조회 실패 → window.location.hostname 폴백:', err)
      return window.location.hostname
    })
}

/** LAN IP 를 미리 받아둠 (App mount 시 호출). 결과는 메모리 캐시. */
export function preloadLanIp(): Promise<string> {
  if (!lanIpPromise) lanIpPromise = fetchLanIp()
  return lanIpPromise
}

/** LAN IP 조회. 캐시 hit 시 즉시 반환, miss 시 fetch. */
export async function getLanIp(): Promise<string> {
  return preloadLanIp()
}
