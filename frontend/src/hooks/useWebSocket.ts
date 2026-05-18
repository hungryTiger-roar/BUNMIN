import { useCallback, useEffect, useRef, useState } from 'react'
import { useLectureStore } from '@/stores/lectureStore'
import { usePreferencesStore } from '@/stores/preferencesStore'
import { API_BASE } from '@/lib/api'
import type { UnitPlayer } from './useDelayBufferPlayer'

interface WebSocketMessage {
  type: string
  [key: string]: unknown
}

type Role = 'lecturer' | 'student'

/** 커서 메시지 타입 (ref 기반 DOM 업데이트용) */
export interface CursorMessage {
  x: number
  y: number
  visible: boolean
  color: string
}

export type DrawTool = 'pencil' | 'highlighter' | 'rect'

/** 강의자 필기 이벤트 (수강자 측에서 캔버스에 즉시 반영) */
export type DrawMessage =
  | { type: 'draw_begin'; id: string; tool: DrawTool; color: string; page: number }
  | { type: 'draw_point'; id: string; x: number; y: number }
  | { type: 'draw_end'; id: string }
  | { type: 'draw_erase'; x: number; y: number; radius: number; page: number }
  | { type: 'draw_clear'; page: number }

interface UseWebSocketOptions {
  /** 커서 메시지 수신 시 콜백 (React 상태 대신 DOM 직접 업데이트용) */
  onCursor?: (cursor: CursorMessage) => void
  /** 강의자 필기 이벤트 수신 (수강자 전용) — DOM 직접 업데이트용, 리렌더 없음 */
  onDraw?: (draw: DrawMessage) => void
  /** WebRTC offer 수신 (수강자 전용) */
  onWebRtcOffer?: (sdp: RTCSessionDescriptionInit) => void
  /** WebRTC answer 수신 (강의자 전용) — sender = student id */
  onWebRtcAnswer?: (sender: string, sdp: RTCSessionDescriptionInit) => void
  /** WebRTC ICE candidate 수신 — 강의자는 sender(학생id), 수강자는 sender=null */
  onWebRtcIce?: (sender: string | null, candidate: RTCIceCandidateInit) => void
  /** 학생측 unit player — Queue + TTS-end gating 모델. 제공 시 cursor / draw /
   *  page_change / slide_select / presentation_mode 가 pending visual buffer 에 적재,
   *  transcription 도착 시 sentence unit 으로 묶임 → 한 unit 의 audio 끝나야 다음 unit. */
  unitPlayer?: UnitPlayer
  /** transcription 도착 시 — Student.tsx 가 unitPlayer.enqueueSentence 호출용.
   *  commitSubtitle 은 TTS 가 실제 시작되는 시점에 player 가 호출 → store 에
   *  subtitle 추가. 이 콜백을 부르기 전엔 자막이 화면에 안 보임 → 자막↔TTS 동기화. */
  onTranscription?: (params: {
    text: string
    commitSubtitle: (ttsMs?: number) => void
    speechStartAt: number
    sentAt: number
  }) => void
  /** lifecycle event (lecture_end / pause / resume) 도착 시 — Student.tsx 가
   *  unitPlayer.enqueueLifecycle 호출용. apply 가 실제 UI 적용 함수.
   *  resume 의 경우 apply 가 async — 강사 pause 시간 만큼 sleep 후 setPaused(false). */
  onLifecycle?: (apply: () => void | Promise<void>, label: string) => void
  /** 강사 전용 — 발화가 환각 가드에 차단되면 호출 (UI toast 등). */
  onAsrBlocked?: (reason: string, preview: string) => void
  /** 강사 전용 — ASR 큐 포화로 발화 스킵되면 호출 (UI toast 등). */
  onAsrOverloaded?: (queued: number) => void
}

export function useWebSocket(url: string, role: Role = 'student', options: UseWebSocketOptions = {}) {
  const { onCursor, onDraw, onWebRtcOffer, onWebRtcAnswer, onWebRtcIce, unitPlayer, onTranscription, onLifecycle, onAsrBlocked, onAsrOverloaded } = options
  const socketRef = useRef<WebSocket | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()
  // disconnect()로 의도적으로 닫힌 소켓의 onclose가 자동 재연결을 트리거하지 않게 하는 플래그.
  // socket.close()가 비동기여서 disconnect()에서 clearTimeout을 해도 그 직후 onclose가 새 setTimeout을 설치 → 무한 재연결 루프.
  // 부수 효과: React 18 StrictMode dev 의 합성 unmount → cleanup → disconnect → onclose 경로에서
  // ghost reconnect 타이머가 잡혀 같은 audio 가 두 번 송출되던 race 도 함께 차단.
  const intentionallyClosedRef = useRef(false)

  // pause ↔ resume 시간 동등 반영용.
  //   pauseLectureTsRef: 강사 시계 기준 pause ts (resume 도착 시 duration 계산).
  //   pauseAppliedAtRef: 학생측에서 setPaused(true) 가 실제로 적용된 시각 — resume sleep
  //     의 elapsed 계산 기준. delay-buffer 모드에서 scheduled timer 가 fire 한 시점.
  const pauseLectureTsRef = useRef<number | null>(null)
  const pauseAppliedAtRef = useRef<number | null>(null)

  // 각 setter를 개별 selector로 구독 — Zustand action은 stable 이므로 재렌더 트리거하지 않음
  // (전체 destructure 시 store 어떤 필드가 바뀌어도 useWebSocket 재렌더 → send/connect ref 흔들림)
  const addSubtitle = useLectureStore((s) => s.addSubtitle)
  const clearSubtitles = useLectureStore((s) => s.clearSubtitles)
  const setConnected = useLectureStore((s) => s.setConnected)
  const setSlideId = useLectureStore((s) => s.setSlideId)
  const setSlideStatus = useLectureStore((s) => s.setSlideStatus)
  const setSlidePages = useLectureStore((s) => s.setSlidePages)
  const setCurrentPage = useLectureStore((s) => s.setCurrentPage)
  const setLectureStarted = useLectureStore((s) => s.setLectureStarted)
  const setPaused = useLectureStore((s) => s.setPaused)
  const setPresentationMode = useLectureStore((s) => s.setPresentationMode)
  const setCurrentScreen = useLectureStore((s) => s.setCurrentScreen)
  const setStudentCount = useLectureStore((s) => s.setStudentCount)
  const addChatMessage = useLectureStore((s) => s.addChatMessage)
  const setParticipants = useLectureStore((s) => s.setParticipants)
  const setLectureTitle = useLectureStore((s) => s.setLectureTitle)
  const setSlideFilename = useLectureStore((s) => s.setSlideFilename)
  const setSessionId = useLectureStore((s) => s.setSessionId)
  const setModelMode = useLectureStore((s) => s.setModelMode)
  const setModelsReady = useLectureStore((s) => s.setModelsReady)
  const setToastMessage = useLectureStore((s) => s.setToastMessage)
  const bumpSlideLibraryRefreshKey = useLectureStore((s) => s.bumpSlideLibraryRefreshKey)
  const studentName = useLectureStore((s) => s.studentName)

  const lecturerName = usePreferencesStore((s) => s.lecturerName)

  const registerNameRef = useRef(role === 'lecturer' ? lecturerName : studentName)
  useEffect(() => {
    registerNameRef.current = role === 'lecturer' ? lecturerName : studentName
  }, [role, lecturerName, studentName])

  // onCursor / onDraw callback refs (stale closure 방지)
  const onCursorRef = useRef(onCursor)
  useEffect(() => { onCursorRef.current = onCursor }, [onCursor])

  const onDrawRef = useRef(onDraw)
  useEffect(() => { onDrawRef.current = onDraw }, [onDraw])

  const onWebRtcOfferRef = useRef(onWebRtcOffer)
  useEffect(() => { onWebRtcOfferRef.current = onWebRtcOffer }, [onWebRtcOffer])
  const onWebRtcAnswerRef = useRef(onWebRtcAnswer)
  useEffect(() => { onWebRtcAnswerRef.current = onWebRtcAnswer }, [onWebRtcAnswer])
  const onWebRtcIceRef = useRef(onWebRtcIce)
  useEffect(() => { onWebRtcIceRef.current = onWebRtcIce }, [onWebRtcIce])

  const onAsrBlockedRef = useRef(onAsrBlocked)
  useEffect(() => { onAsrBlockedRef.current = onAsrBlocked }, [onAsrBlocked])
  const onAsrOverloadedRef = useRef(onAsrOverloaded)
  useEffect(() => { onAsrOverloadedRef.current = onAsrOverloaded }, [onAsrOverloaded])

  // timeline 도 ref 로 — 객체 자체는 매 렌더마다 새로 만들어지지만 안의 enqueue/flush
  // 메서드는 stable (useCallback). ref 통해 latest 메서드 접근.
  const unitPlayerRef = useRef(unitPlayer)
  useEffect(() => { unitPlayerRef.current = unitPlayer }, [unitPlayer])
  const onTranscriptionRef = useRef(onTranscription)
  useEffect(() => { onTranscriptionRef.current = onTranscription }, [onTranscription])
  const onLifecycleRef = useRef(onLifecycle)
  useEffect(() => { onLifecycleRef.current = onLifecycle }, [onLifecycle])

  // 슬라이드 페이지 로드
  const loadSlidePages = useCallback(async (slideId: string) => {
    try {
      const response = await fetch(`${API_BASE}/slides/pages/${slideId}`)
      if (!response.ok) throw new Error('Failed to load slides')

      const data = await response.json()
      setSlidePages(data.pages)
      if (typeof data.filename === 'string') {
        setSlideFilename(data.filename)
      }
      setSlideStatus('ready')
    } catch (err) {
      console.error('[WebSocket] 슬라이드 로드 실패:', err)
    }
  }, [setSlidePages, setSlideStatus, setSlideFilename])

  const handleMessage = useCallback((data: WebSocketMessage) => {
    // [Diag] 학생측 receive 로그 — sync 진단용. cursor / draw_point 는 매 10번째.
    // 기본 활성 (main.tsx 에서 window.__SYNC_DEBUG=true). 끄려면 콘솔에서 false.
    // 강사 보낸 시각 (lecturerTimestamp) 과 학생 도착 시각 차이로 네트워크+서버 지연 측정.
    if (role === 'student' && (window as unknown as { __SYNC_DEBUG?: boolean }).__SYNC_DEBUG) {
      const t = data.type
      const lecTs = data.lecturerTimestamp as number | undefined
      const lag = typeof lecTs === 'number' ? Date.now() - lecTs : null
      const lagStr = lag !== null ? `lag=${lag}ms` : 'lag=N/A'
      if (t === 'cursor' || t === 'draw_point') {
        const counter = ((window as unknown as { __SYNC_RECV_COUNTER?: Record<string, number> }).__SYNC_RECV_COUNTER ??= {})
        counter[t] = (counter[t] ?? 0) + 1
        if (counter[t] % 10 === 0) {
          console.log(`[S←L] ${t} #${counter[t]} ${lagStr} lecTs=${lecTs}`)
        }
      } else if (t !== 'pong' && t !== 'ping' && t !== 'student_count' && t !== 'participants') {
        const extra = t === 'transcription' ? ` text="${(data.translated as string ?? '').slice(0, 30)}..."` : ''
        console.log(`[S←L] ${t} ${lagStr} lecTs=${lecTs}${extra}`)
      }
    }
    switch (data.type) {
      case 'transcription': {
        // 강의 시작 전엔 강의자 마이크 테스트 자막을 수강자에게 표시/재생 안 함
        if (role === 'student' && !useLectureStore.getState().isLectureStarted) {
          break
        }
        // 번역 결과 수신
        const outputTime = Date.now()
        const inputTime = data.sentAt as number | undefined            // sentence END
        const speechStartAt = data.speechStartAt as number | undefined  // sentence START
        const original = data.original as string
        const translated = data.translated as string
        const asrMs = data.asrMs as number | undefined
        const nmtMs = data.nmtMs as number | undefined
        // [ASR/NMT] 로그 — 강사: 원문만 / 학생: 원문 + 번역.
        // 콘솔(F12)에서 어떤 발화가 어떻게 인식됐는지 한눈에 확인용.
        if (role === 'lecturer') {
          console.log(`[ASR] 한: ${original}`)
        } else {
          console.log(`[ASR→NMT] 한: ${original}  →  영: ${translated}`)
        }

        if (role === 'lecturer') {
          // 강사는 unit player 가 없으므로 즉시 자막 표시.
          addSubtitle({
            original,
            translated,
            timestamp: outputTime,
            inputTime,
            asrMs,
            nmtMs,
          })
        } else if (data.translated && onTranscriptionRef.current) {
          // 학생측 — 자막 표시는 TTS 시작 시점까지 지연 (commitSubtitle 콜백).
          // 이전엔 transcription 도착 즉시 addSubtitle 했으나 큐 대기 + TTS 합성으로
          // 자막이 audio 보다 수 초 일찍 떠 답답함. 이제 player 가 audio 시작 시점에
          // commitSubtitle 호출 → 자막↔TTS 동시 등장.
          onTranscriptionRef.current({
            text: translated,
            commitSubtitle: (ttsMs?: number) => {
              addSubtitle({
                original,
                translated,
                timestamp: outputTime,
                inputTime,
                asrMs,
                nmtMs,
                ttsMs,
              })
            },
            speechStartAt: speechStartAt ?? inputTime ?? Date.now(),
            sentAt: inputTime ?? Date.now(),
          })
        } else {
          // 학생측이지만 translated 가 비어 있음 (NMT 빈 결과) — 자막을 동기화할
          // TTS 가 없으므로 한국어 원문만 즉시 표시 (구버전 호환).
          addSubtitle({
            original,
            translated,
            timestamp: outputTime,
            inputTime,
            asrMs,
            nmtMs,
          })
        }
        break
      }

      case 'slide_select':
        // 강의자가 슬라이드 선택
        if (role === 'student') {
          const slideId = data.slide_id as string
          const ts = data.lecturerTimestamp as number | undefined
          const apply = () => {
            setSlideId(slideId)
            setSlideStatus('processing')
            loadSlidePages(slideId)
          }
          if (unitPlayerRef.current && typeof ts === 'number') {
            unitPlayerRef.current.enqueueVisual(ts, apply, 'slide_select')
          } else {
            apply()
          }
        }
        break

      case 'page_change':
        // 페이지 변경 동기화
        if (role === 'student') {
          const page = data.page as number
          const ts = data.lecturerTimestamp as number | undefined
          if (unitPlayerRef.current && typeof ts === 'number') {
            unitPlayerRef.current.enqueueVisual(ts, () => setCurrentPage(page), 'page_change')
          } else {
            setCurrentPage(page)
          }
        }
        break

      case 'lecture_start':
        // 강의 시작 — 양측 모두 즉시. 데모/발표 시 강사 클릭과 동시에 학생
        // 화면이 시작 상태가 돼야 컨트롤 가능. 다른 시각 events 와 달리 delay
        // 안 함 (시작은 boundary 자체).
        setLectureStarted(true)
        if (role === 'student' && data.slide_id) {
          const slideId = data.slide_id as string
          setSlideId(slideId)
          setSlideStatus('processing')
          loadSlidePages(slideId)
          // 강사 시작 시점 페이지를 즉시 반영 — page_change 가 다음 sentence 까지
          // 큐에 묶여 늦게 적용되는 동안 학생이 page 1 로 보이는 문제 차단.
          if (typeof data.page === 'number' && data.page > 0) {
            setCurrentPage(data.page)
          }
        }
        // 학생 측 — 이전 강의의 미적용 visual events 폐기 + offset 초기화.
        if (role === 'student') unitPlayerRef.current?.reset()
        console.log('[WebSocket] 강의 시작')
        break

      case 'session_started':
        // 강의자: 강의 시작 시 자막 세션 ID 수신
        if (data.session_id) setSessionId(data.session_id as string)
        break

      case 'lecture_start_rejected':
        // 옵션 C 가드: backend 가 슬라이드 처리 중 강의 시작 거부.
        // 옵션 D 의 modelsReady 가드가 버튼을 비활성으로 만들기 때문에 정상 흐름에선 여기 도달 안 함.
        // 도달했다면 race — 로그만 남기고 store 에러 상태로 표시 (alert 는 Electron UX 부적합으로 미사용).
        if (role === 'lecturer') {
          const msg = (data.message as string) || '강의를 시작할 수 없습니다.'
          console.warn('[WebSocket] 강의 시작 거부:', data.reason, msg)
          setToastMessage(msg)
        }
        break

      case 'mode_change':
        // 옵션 D: backend 가 모드 전환 시 push. 강의자만 받음 (manager.lecturer 로 전송).
        // modelsReady 기준으로 강의 시작 버튼 / SlideUpload 의 선제 활성/비활성 가드.
        if (role === 'lecturer') {
          const m = (data.mode as string) || 'idle'
          setModelMode(
            (m === 'slide' || m === 'realtime' || m === 'switching' ? m : 'idle') as
              'idle' | 'slide' | 'switching' | 'realtime'
          )
          setModelsReady(!!data.realtime_ready)
        }
        break

      case 'toast':
        // backend 가 글로벌 토스트 메시지 push (VLM 다운 안내 등).
        // App.tsx 의 GlobalToast 가 자동 4초 dismiss.
        if (role === 'lecturer' && data.message) {
          setToastMessage(data.message as string)
        }
        break

      case 'slide_status_update':
        // backend process_slide / process_slide_pdf_layer 완료/실패 시 강의자에게 push.
        // polling 끊긴 경우에도 즉시 UI 복구 — 현재 선택된 슬라이드면 slideStatus 갱신,
        // 항상 라이브러리 refresh 트리거해서 라이브러리 안 자료 상태도 갱신.
        if (role === 'lecturer') {
          const sid = data.slide_id as string | undefined
          const newStatus = data.status as string | undefined
          if (sid && newStatus) {
            const currentSlideId = useLectureStore.getState().slideId
            if (currentSlideId === sid) {
              if (newStatus === 'completed') setSlideStatus('ready')
              // failed 는 slideStatus enum 에 없어 — 'none' 으로 reset 해서 dropzone 다시 보이게
              else if (newStatus === 'failed') setSlideStatus('none')
            }
            bumpSlideLibraryRefreshKey()
          }
        }
        break

      case 'lecture_end':
        // 강의 종료 — 강사 측은 즉시, 학생 측은 lifecycle queue 통해 큐 잔여
        // sentence 다 재생된 뒤 적용. sessionId 도 lifecycle apply 시점에 세팅 —
        // 다운로드 모달이 강의 중 (잔여 발화 재생 중) 에 떠서 "강의 중에 종료
        // 됐다" 는 인상을 주지 않게 마지막 자막/음성 끝난 후에 모달 노출.
        if (role === 'lecturer') {
          setLectureStarted(false)
          setPaused(false)
          setCurrentScreen(null)
          if (data.session_id) setSessionId(data.session_id as string)
          console.log('[WebSocket] 강의 종료')
        } else {
          const sessionIdToSet = data.session_id as string | undefined
          const apply = () => {
            if (sessionIdToSet) setSessionId(sessionIdToSet)
            setLectureStarted(false)
            setPaused(false)
            setCurrentScreen(null)
            console.log('[WebSocket] 강의 종료')
          }
          if (unitPlayerRef.current && onLifecycleRef.current) {
            onLifecycleRef.current(apply, 'lecture_end')
          } else {
            apply()
          }
        }
        break

      case 'lecture_pause':
        if (role === 'lecturer') {
          setPaused(true)
          console.log('[WebSocket] 강의 일시정지')
        } else {
          // 강사 시계 ts 저장 — resume 도착 시 정확한 pause duration 계산.
          const pauseTs = (data.lecturerTimestamp as number | undefined) ?? Date.now()
          pauseLectureTsRef.current = pauseTs
          const apply = () => {
            setPaused(true)
            // 잔여 자막 제거 — pause 적용 직전 commit 된 자막이 일시정지 오버레이 위에
            // 남는 현상 방지. resume 후엔 새 sentence commit 이 들어와 자연히 다시 표시됨.
            clearSubtitles()
            // pause 가 학생측에서 실제 적용된 wall time — resume sleep elapsed 기준.
            pauseAppliedAtRef.current = Date.now()
            console.log('[WebSocket] 강의 일시정지')
          }
          if (unitPlayerRef.current && onLifecycleRef.current) {
            onLifecycleRef.current(apply, 'lecture_pause')
          } else {
            apply()
            pauseAppliedAtRef.current = Date.now()
          }
        }
        break

      case 'lecture_resume':
        if (role === 'lecturer') {
          setPaused(false)
          console.log('[WebSocket] 강의 재개')
        } else {
          // 강사 pause 시간 = resume.ts - pause.ts. 학생측 pause UI 도 같은 시간 유지.
          const resumeTs = (data.lecturerTimestamp as number | undefined) ?? Date.now()
          const pauseTs = pauseLectureTsRef.current
          const lecturerPauseDuration = pauseTs !== null ? Math.max(0, resumeTs - pauseTs) : 0
          const apply = async () => {
            // 학생측에서 이미 elapsed 만큼 paused 였으면 그만큼 빼고 sleep.
            // delay-buffer: scheduled timer 로 pause/resume 둘 다 +delayMs 후 fire →
            //               elapsed ≈ lecturerPauseDuration → remaining ≈ 0 (자연스레 일치).
            const pauseAppliedAt = pauseAppliedAtRef.current
            if (pauseAppliedAt !== null && lecturerPauseDuration > 0) {
              const elapsed = Date.now() - pauseAppliedAt
              const remaining = Math.max(0, lecturerPauseDuration - elapsed)
              if (remaining > 0) {
                console.log(
                  `[WebSocket] 강사 pause ${lecturerPauseDuration}ms — 학생측 ${remaining}ms 추가 대기`,
                )
                await new Promise<void>((r) => setTimeout(r, remaining))
              }
            }
            setPaused(false)
            pauseAppliedAtRef.current = null
            pauseLectureTsRef.current = null
            console.log('[WebSocket] 강의 재개')
          }
          if (unitPlayerRef.current && onLifecycleRef.current) {
            onLifecycleRef.current(apply, 'lecture_resume')
          } else {
            // unit player 없는 비정상 경로 — 일단 즉시 unpause.
            apply()
          }
        }
        break

      case 'presentation_mode':
        // 발표 모드 변경
        if (role === 'student') {
          const mode = data.mode as 'slide' | 'screen'
          const ts = data.lecturerTimestamp as number | undefined
          const apply = () => {
            setPresentationMode(mode)
            if (mode === 'slide') {
              setCurrentScreen(null)
            }
            console.log('[WebSocket] 발표 모드 변경:', mode)
          }
          if (unitPlayerRef.current && typeof ts === 'number') {
            unitPlayerRef.current.enqueueVisual(ts, apply, 'presentation_mode')
          } else {
            apply()
          }
        }
        break

      case 'screen':
        // 구버전 호환 (사용 안 함 — WebRTC로 대체)
        break

      case 'webrtc_offer':
        if (role === 'student') {
          onWebRtcOfferRef.current?.(data.sdp as RTCSessionDescriptionInit)
        }
        break

      case 'webrtc_answer':
        if (role === 'lecturer') {
          onWebRtcAnswerRef.current?.(
            data.sender as string,
            data.sdp as RTCSessionDescriptionInit,
          )
        }
        break

      case 'webrtc_ice':
        if (role === 'student') {
          onWebRtcIceRef.current?.(null, data.candidate as RTCIceCandidateInit)
        } else if (role === 'lecturer') {
          onWebRtcIceRef.current?.(
            data.sender as string,
            data.candidate as RTCIceCandidateInit,
          )
        }
        break

      case 'ping':
        // 서버 핑 → 퐁 응답
        if (socketRef.current?.readyState === WebSocket.OPEN) {
          socketRef.current.send(JSON.stringify({ type: 'pong' }))
        }
        break

      case 'pong':
        // 핑퐁 응답
        break

      case 'student_count':
        // 현재 접속 중인 수강자 수
        setStudentCount(data.count as number)
        break

      case 'chat_message':
        // 채팅 메시지 수신
        addChatMessage({
          id: (data.id as string) || crypto.randomUUID(),
          sender: data.sender as 'lecturer' | 'student',
          name: data.name as string,
          text: data.text as string,
          timestamp: (data.timestamp as number) || Date.now(),
          studentId: data.student_id as string | undefined,
        })
        break

      case 'participants':
        // 참여자 목록 (audio_lang 은 강의자 참여자 패널에서 '원본/번역' 라벨로 사용)
        setParticipants({
          lecturer: data.lecturer as { name: string; connected: boolean } | null,
          students: ((data.students as { id: string; name: string; audio_lang?: string }[]) || []).map((s) => ({
            id: s.id,
            name: s.name,
            audioLang: s.audio_lang ?? 'en',
          })),
        })
        break

      case 'lecture_title':
        // 강의 제목 (강사가 설정)
        setLectureTitle((data.title as string) || '')
        break

      case 'registered':
        // 역할 등록 확인.
        console.log('[WebSocket] 역할 등록 완료:', data.role)
        break

      case 'cursor':
        // 강의자 커서 상태 수신 (수강자 전용, callback으로 DOM 직접 업데이트)
        // page 가드: cursor 의 page 와 학생 currentPage 가 다르면 hide.
        // 페이지 전환 직후 잔여 cursor 가 새 페이지에 잘못 표시되는 것 방지.
        if (role === 'student') {
          const cursorPage = data.page as number | undefined
          const cursor: CursorMessage = {
            x: data.x as number,
            y: data.y as number,
            visible: data.visible as boolean,
            color: data.color as string,
          }
          const ts = data.lecturerTimestamp as number | undefined
          const apply = () => {
            const currentPage = useLectureStore.getState().currentPage
            if (typeof cursorPage === 'number' && cursorPage !== currentPage) {
              // 다른 페이지의 cursor — visible=false 로 숨김
              onCursorRef.current?.({ ...cursor, visible: false })
              return
            }
            onCursorRef.current?.(cursor)
          }
          if (unitPlayerRef.current && typeof ts === 'number') {
            unitPlayerRef.current.enqueueVisual(ts, apply, 'cursor')
          } else {
            apply()
          }
        }
        break

      case 'draw_begin':
      case 'draw_point':
      case 'draw_end':
      case 'draw_erase':
      case 'draw_clear':
        // 강의자 필기 이벤트 수신 (수강자 전용, callback으로 캔버스 직접 업데이트)
        if (role === 'student') {
          const draw = data as unknown as DrawMessage
          const ts = data.lecturerTimestamp as number | undefined
          if (unitPlayerRef.current && typeof ts === 'number') {
            unitPlayerRef.current.enqueueVisual(ts, () => onDrawRef.current?.(draw), data.type as string)
          } else {
            onDrawRef.current?.(draw)
          }
        }
        break

      case 'drawings_replay':
        // 신규 입장 학생 — backend 가 보낸 페이지별 누적 필기 일괄 적용.
        // timeline 우회 (즉시 apply) — 과거 events 라 sync 시간선 의미 없음.
        // DrawingCanvas 의 receiveDraw 가 page 필드 보고 알맞은 페이지 buffer 에 적재.
        // → 페이지 전환 시 그 페이지 그림이 자동으로 재현됨.
        if (role === 'student') {
          const events = data.events as unknown as DrawMessage[] | undefined
          if (Array.isArray(events)) {
            console.log(`[WebSocket] 신규 입장 — 누적 필기 ${events.length}건 replay`)
            for (const ev of events) {
              try {
                onDrawRef.current?.(ev)
              } catch (err) {
                console.error('[WebSocket] drawings_replay 적용 오류:', err)
              }
            }
          }
        }
        break

      case 'asr_blocked':
        // 환각 가드 차단 — 강사 측에 알림. 정상 발화가 잘못 차단됐을 수 있어
        // 사용자가 인지하고 다시 말할 수 있게.
        if (role === 'lecturer') {
          const reason = (data.reason as string) || '알 수 없음'
          const preview = (data.preview as string) || ''
          onAsrBlockedRef.current?.(reason, preview)
          console.warn('[WebSocket] ASR 차단:', reason, preview)
        }
        break

      case 'asr_overloaded':
        // ASR 큐 포화 — 강사 측에 알림. 발화가 시스템에 도달 못 했음.
        if (role === 'lecturer') {
          const queued = (data.queued as number) || 0
          onAsrOverloadedRef.current?.(queued)
          console.warn('[WebSocket] ASR 큐 포화:', queued)
        }
        break

      default:
        console.log('[WebSocket] 알 수 없는 메시지:', data.type)
    }
  }, [role, addSubtitle, setSlideId, setSlideStatus, setCurrentPage, setLectureStarted, setPaused, setPresentationMode, setCurrentScreen, setStudentCount, addChatMessage, setParticipants, setLectureTitle, setSessionId, loadSlidePages])

  // handleMessage를 ref로 분리 → connect의 deps에서 제거해 어떤 selector 흔들림에도 socket이 재생성되지 않게 한다.
  const handleMessageRef = useRef(handleMessage)
  useEffect(() => { handleMessageRef.current = handleMessage }, [handleMessage])

  const send = useCallback((data: object) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      // 강사측 outgoing 에 lecturerTimestamp 자동 부착 — 학생측 timeline scheduler 가
      // visual event 와 TTS 진도 매칭하는 데 사용. 학생이 보내는 메시지 (chat / rename
      // / pong 등) 는 sync 와 무관해 부착 안 함.
      const enriched = role === 'lecturer'
        ? { ...data, lecturerTimestamp: Date.now() }
        : data
      // [Diag] 강사측 send 로그 — sync 진단용. cursor / draw_point 는 고빈도라 매 10번째.
      // 기본 활성 (main.tsx 에서 window.__SYNC_DEBUG=true). 끄려면 콘솔에서 false.
      if (role === 'lecturer' && (window as unknown as { __SYNC_DEBUG?: boolean }).__SYNC_DEBUG) {
        const t = (data as { type?: string }).type
        if (t === 'cursor' || t === 'draw_point') {
          const counter = ((window as unknown as { __SYNC_COUNTER?: Record<string, number> }).__SYNC_COUNTER ??= {})
          counter[t] = (counter[t] ?? 0) + 1
          if (counter[t] % 10 === 0) {
            console.log(`[L→S] ${t} #${counter[t]} ts=${(enriched as { lecturerTimestamp: number }).lecturerTimestamp}`, data)
          }
        } else {
          console.log(`[L→S] ${t} ts=${(enriched as { lecturerTimestamp: number }).lecturerTimestamp}`, data)
        }
      }
      socketRef.current.send(JSON.stringify(enriched))
    } else {
      console.warn('[WebSocket] 연결되지 않음')
    }
  }, [role])

  // 화면 공유 등 대용량 송신 시 백프레셔 판단용
  const getBufferedAmount = useCallback(() => {
    return socketRef.current?.bufferedAmount ?? 0
  }, [])

  const sendChat = useCallback((text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'chat_message', text: trimmed }))
    }
  }, [])

  const sendLectureTitle = useCallback((title: string) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'lecture_title', title }))
    }
  }, [])

  const sendLecturerName = useCallback((name: string) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'lecturer_name', name }))
    }
  }, [])

  const sendStudentRename = useCallback((name: string) => {
    const trimmed = name.trim()
    if (!trimmed) return
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'student_rename', name: trimmed }))
    }
  }, [])

  const sendStudentAudioLang = useCallback((audioLang: string) => {
    const trimmed = audioLang.trim()
    if (!trimmed) return
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'student_audio_lang', audio_lang: trimmed }))
    }
  }, [])

  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN ||
        socketRef.current?.readyState === WebSocket.CONNECTING) {
      return
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = undefined
    }

    console.log('[WebSocket] 재연결 시도...')
    intentionallyClosedRef.current = false
    const socket = new WebSocket(url)

    socket.onopen = () => {
      console.log('[WebSocket] 연결됨')
      socket.send(JSON.stringify({ type: 'register', role, name: registerNameRef.current }))
      // 참여자 목록 최신화 요청 (register broadcast를 혹시라도 놓친 경우 대비)
      socket.send(JSON.stringify({ type: 'participants_request' }))
      console.log(`[WebSocket] 역할 등록: ${role} (이름: ${registerNameRef.current || '(기본값)'})`)
      setIsConnected(true)
      setConnected(true)
    }

    socket.onclose = (e) => {
      console.log(`[WebSocket] 연결 종료 (code=${e.code}, reason=${e.reason || '(none)'}, intentional=${intentionallyClosedRef.current})`)
      setIsConnected(false)
      setConnected(false)
      // 의도적 close (disconnect 호출, 컴포넌트 언마운트)는 자동 재연결하지 않음
      if (intentionallyClosedRef.current) return
      reconnectTimeoutRef.current = setTimeout(() => {
        connect()
      }, 3000)
    }

    socket.onerror = (error) => {
      console.error('[WebSocket] 에러:', error)
    }

    socket.onmessage = (event) => {
      try {
        const data: WebSocketMessage = JSON.parse(event.data)
        handleMessageRef.current(data)
      } catch (err) {
        console.error('[WebSocket] 메시지 파싱 실패:', err)
      }
    }

    socketRef.current = socket
  }, [url, role, setConnected])

  // connectGenerationRef — disconnect / forceReconnect 가 호출될 때마다 증가.
  // forceReconnect 의 100ms 지연 setTimeout 이 fire 할 시점에 그 사이 disconnect 가
  // 호출됐는지 비교 → unmount 중 leak (좀비 소켓 생성) 차단.
  const connectGenerationRef = useRef(0)

  const disconnect = useCallback(() => {
    connectGenerationRef.current++
    intentionallyClosedRef.current = true
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = undefined
    }
    socketRef.current?.close()
    socketRef.current = null
    setIsConnected(false)
    setConnected(false)
  }, [setConnected])

  // forceReconnect — WebRTC PC 가 failed 등으로 죽었을 때 강사측이 새 offer 를 보내도록
  // WS 를 닫았다 다시 열어 재등록 흐름을 트리거. 자동 reconnect 의 3초 지연을 우회.
  const forceReconnect = useCallback(() => {
    const myGen = ++connectGenerationRef.current
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = undefined
    }
    intentionallyClosedRef.current = true   // onclose 의 자동 reconnect 차단 — 우리가 직접 다시 connect.
    socketRef.current?.close()
    socketRef.current = null
    setIsConnected(false)
    setConnected(false)
    // 100ms 지연으로 close 가 서버에 전파되고 cleanup 마무리 후 새 연결 시도.
    // 단, 그 사이 disconnect (unmount) 또는 또 다른 forceReconnect 가 발생했으면 skip.
    setTimeout(() => {
      if (myGen !== connectGenerationRef.current) return
      intentionallyClosedRef.current = false
      connect()
    }, 100)
  }, [connect, setConnected])

  // 마운트/언마운트 시에만 cleanup이 호출되도록 ref 패턴 + 빈 deps.
  // disconnect를 직접 deps에 넣으면 reference가 흔들릴 때마다 cleanup → disconnect → onclose 자동재연결 무한 루프 위험.
  const disconnectRef = useRef(disconnect)
  useEffect(() => { disconnectRef.current = disconnect }, [disconnect])
  useEffect(() => {
    return () => {
      disconnectRef.current()
    }
  }, [])

  return {
    isConnected,
    connect,
    disconnect,
    forceReconnect,
    send,
    sendChat,
    sendLectureTitle,
    sendLecturerName,
    sendStudentRename,
    sendStudentAudioLang,
    getBufferedAmount,
  }
}
