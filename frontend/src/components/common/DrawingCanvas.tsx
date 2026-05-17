/**
 * DrawingCanvas — 강의자 필기 + 수강자 수신 공용 캔버스 오버레이
 *
 * 레이어 구조:
 *   visibleCanvas  — DOM. 사용자가 보는 캔버스
 *   stableBuffer   — offscreen. 확정된 액션들이 알파 합성 완료된 비트맵
 *   inflightBuffer — offscreen. 진행 중 stroke을 alpha=1로 그리는 스크래치
 *
 * 렌더 파이프라인:
 *   visible = drawImage(stable) + drawImage(inflight, alpha=tool별)
 *   - 한 stroke 내 alpha 누적이 일어나지 않도록 inflight는 매 move마다 처음부터 다시 그림
 *   - 형광펜 alpha 0.35는 inflight → stable 합성 시점에 단 한 번만 적용
 *
 * 좌표계: 슬라이드 이미지 영역 기준 0~1 정규화 (커서 메시지와 동일)
 *
 * 부드러운 곡선:
 *   - 점들 사이를 quadratic Bezier (midpoint smoothing)로 연결
 *   - 송신 throttle 16ms (60Hz) — 듬성한 점도 곡선 보간으로 부드럽게 보임
 */
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'
import type { DrawMessage, DrawTool } from '@/hooks/useWebSocket'

export type DrawingTool = DrawTool | 'eraser'

const PENCIL_WIDTH_NORM = 0.0035    // 이미지 영역 너비 대비
const HIGHLIGHTER_WIDTH_NORM = 0.030
const HIGHLIGHTER_ALPHA = 0.35
const RECT_WIDTH_NORM = 0.004
const ERASER_RADIUS_NORM = 0.022

const SEND_THROTTLE_MS = 16            // 강의자 → 서버 송신 주기 (~60fps)
const LONGPRESS_MS = 500               // 지우개 꾹눌러 전체 클리어 임계
const LONGPRESS_MOVE_TOL_NORM = 0.025  // 그 사이 움직였다고 볼 임계 — 한 번이라도 초과하면 long-press 취소

type Action =
  | { kind: 'stroke'; tool: 'pencil' | 'highlighter'; color: string; points: number[] }
  | { kind: 'rect'; color: string; x1: number; y1: number; x2: number; y2: number }
  | { kind: 'erase'; x: number; y: number; radius: number }
  | { kind: 'clear' }

interface InflightStroke {
  id: string
  tool: DrawTool
  color: string
  page: number
  points: number[]
}

export interface DrawingCanvasHandle {
  receiveDraw: (msg: DrawMessage) => void
  /** 특정 페이지의 필기 전체 삭제 (강의자 측 "전체 지우기" 버튼용) */
  clearPage: (page: number) => void
  /** 모든 페이지의 필기 삭제 */
  clearAllPages: () => void
}

interface DrawingCanvasProps {
  mode: 'lecturer' | 'student'
  containerRef: React.RefObject<HTMLDivElement | null>
  /** 1-based 현재 페이지 */
  page: number
  /** 강의자 전용 — 필기 모드 활성화 (false면 pointer 이벤트 무시) */
  active?: boolean
  /** 강의자 전용 — 현재 도구 */
  tool?: DrawingTool
  /** 강의자 전용 — 현재 색 */
  color?: string
  /** 강의자 전용 — WS 송신 함수 */
  send?: (msg: object) => void
}

interface ImageBox {
  left: number
  top: number
  width: number
  height: number
}

function measureImageBox(container: HTMLDivElement): ImageBox {
  const rect = container.getBoundingClientRect()
  const media = container.querySelector('img, video') as
    | HTMLImageElement
    | HTMLVideoElement
    | null

  let imgOffsetX = 0
  let imgOffsetY = 0
  let imgW = rect.width
  let imgH = rect.height

  const naturalW =
    media instanceof HTMLImageElement
      ? media.naturalWidth
      : media instanceof HTMLVideoElement
      ? media.videoWidth
      : 0
  const naturalH =
    media instanceof HTMLImageElement
      ? media.naturalHeight
      : media instanceof HTMLVideoElement
      ? media.videoHeight
      : 0

  if (naturalW && naturalH && rect.width > 0 && rect.height > 0) {
    const ratio = naturalW / naturalH
    const cRatio = rect.width / rect.height
    if (ratio > cRatio) {
      imgW = rect.width
      imgH = rect.width / ratio
    } else {
      imgH = rect.height
      imgW = rect.height * ratio
    }
    imgOffsetX = (rect.width - imgW) / 2
    imgOffsetY = (rect.height - imgH) / 2
  }
  return { left: imgOffsetX, top: imgOffsetY, width: imgW, height: imgH }
}

/** quadratic Bezier midpoint smoothing — 듬성한 점도 부드러운 곡선이 되게.
 *  points: 정규화 좌표 [x1,y1, x2,y2, ...] */
function strokeSmoothPath(
  ctx: CanvasRenderingContext2D,
  color: string,
  points: number[],
  lineWidthPx: number,
  lineCap: CanvasLineCap,
) {
  if (points.length < 2) return
  const W = ctx.canvas.width
  const H = ctx.canvas.height
  ctx.save()
  ctx.strokeStyle = color
  ctx.lineCap = lineCap
  ctx.lineJoin = 'round'
  ctx.lineWidth = Math.max(1, lineWidthPx)

  if (points.length === 2) {
    // 단일 점 — 작은 원 채우기
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(points[0] * W, points[1] * H, ctx.lineWidth / 2, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
    return
  }

  ctx.beginPath()
  ctx.moveTo(points[0] * W, points[1] * H)
  if (points.length === 4) {
    ctx.lineTo(points[2] * W, points[3] * H)
  } else {
    let i = 2
    while (i + 3 < points.length) {
      const mx = ((points[i] + points[i + 2]) / 2) * W
      const my = ((points[i + 1] + points[i + 3]) / 2) * H
      ctx.quadraticCurveTo(points[i] * W, points[i + 1] * H, mx, my)
      i += 2
    }
    // 마지막 midpoint → 마지막 실제 점
    ctx.lineTo(points[points.length - 2] * W, points[points.length - 1] * H)
  }
  ctx.stroke()
  ctx.restore()
}

function drawRectShape(
  ctx: CanvasRenderingContext2D,
  color: string,
  x1n: number,
  y1n: number,
  x2n: number,
  y2n: number,
) {
  const W = ctx.canvas.width
  const H = ctx.canvas.height
  ctx.save()
  ctx.strokeStyle = color
  ctx.lineWidth = Math.max(1, RECT_WIDTH_NORM * W)
  ctx.lineJoin = 'round'
  ctx.globalAlpha = 1
  const x = Math.min(x1n, x2n) * W
  const y = Math.min(y1n, y2n) * H
  const w = Math.abs(x2n - x1n) * W
  const h = Math.abs(y2n - y1n) * H
  ctx.strokeRect(x, y, w, h)
  ctx.restore()
}

function eraseAt(
  ctx: CanvasRenderingContext2D,
  xn: number,
  yn: number,
  radiusN: number,
) {
  const W = ctx.canvas.width
  const H = ctx.canvas.height
  ctx.save()
  ctx.globalCompositeOperation = 'destination-out'
  ctx.beginPath()
  ctx.arc(xn * W, yn * H, Math.max(1, radiusN * W), 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
}

function lineWidthForTool(tool: 'pencil' | 'highlighter', canvasW: number): number {
  if (tool === 'pencil') return Math.max(1, PENCIL_WIDTH_NORM * canvasW)
  return Math.max(1, HIGHLIGHTER_WIDTH_NORM * canvasW)
}

export const DrawingCanvas = forwardRef<DrawingCanvasHandle, DrawingCanvasProps>(
  function DrawingCanvas(
    { mode, containerRef, page, active = false, tool = 'pencil', color = '#000000', send },
    ref,
  ) {
    const visibleCanvasRef = useRef<HTMLCanvasElement>(null)
    // offscreen 버퍼들 — 첫 마운트 후 lazy init
    const stableBufferRef = useRef<HTMLCanvasElement | null>(null)
    const inflightBufferRef = useRef<HTMLCanvasElement | null>(null)

    // 페이지별 벡터 액션
    const pageActionsRef = useRef<Map<number, Action[]>>(new Map())
    // 단일 진행 중 stroke (lecturer는 자기 마우스 1개, student는 1명 강의자만 받음)
    const inflightRef = useRef<InflightStroke | null>(null)

    const pageRef = useRef(page)
    useEffect(() => {
      pageRef.current = page
    }, [page])

    // 캔버스 표시 영역
    const [imgBox, setImgBox] = useState<ImageBox | null>(null)
    const imgBoxRef = useRef<ImageBox | null>(null)
    useEffect(() => {
      imgBoxRef.current = imgBox
    }, [imgBox])

    // ===== 사이즈 측정 =====
    useEffect(() => {
      const container = containerRef.current
      if (!container) return

      const update = () => {
        const cont = containerRef.current
        if (!cont) return
        const next = measureImageBox(cont)
        setImgBox((prev) => {
          if (
            prev &&
            Math.abs(prev.left - next.left) < 0.5 &&
            Math.abs(prev.top - next.top) < 0.5 &&
            Math.abs(prev.width - next.width) < 0.5 &&
            Math.abs(prev.height - next.height) < 0.5
          ) {
            return prev
          }
          return next
        })
      }

      update()
      const ro = new ResizeObserver(update)
      ro.observe(container)
      const onMutated = () => {
        update()
        const img = container.querySelector('img')
        if (img && !img.complete) {
          img.addEventListener('load', update, { once: true })
        }
      }
      const mo = new MutationObserver(onMutated)
      mo.observe(container, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['src'],
      })
      onMutated()
      window.addEventListener('resize', update)

      return () => {
        ro.disconnect()
        mo.disconnect()
        window.removeEventListener('resize', update)
      }
    }, [containerRef])

    // ===== 캔버스 픽셀 사이즈 동기화 + 페이지/리사이즈 시 stable 재구성 =====
    useEffect(() => {
      const visible = visibleCanvasRef.current
      if (!visible || !imgBox) return
      const dpr = Math.max(1, window.devicePixelRatio || 1)
      const wantW = Math.max(1, Math.round(imgBox.width * dpr))
      const wantH = Math.max(1, Math.round(imgBox.height * dpr))

      // offscreen 버퍼 lazy 생성
      if (!stableBufferRef.current) stableBufferRef.current = document.createElement('canvas')
      if (!inflightBufferRef.current) inflightBufferRef.current = document.createElement('canvas')

      const stable = stableBufferRef.current!
      const inflight = inflightBufferRef.current!

      ;[visible, stable, inflight].forEach((c) => {
        if (c.width !== wantW) c.width = wantW
        if (c.height !== wantH) c.height = wantH
      })

      rebuildStableForCurrentPage()
      renderVisible()
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [imgBox, page])

    // ===== 핵심 헬퍼 =====
    function rebuildStableForCurrentPage() {
      const stable = stableBufferRef.current
      if (!stable) return
      const sCtx = stable.getContext('2d')
      if (!sCtx) return
      sCtx.setTransform(1, 0, 0, 1, 0, 0)
      sCtx.clearRect(0, 0, stable.width, stable.height)
      const actions = pageActionsRef.current.get(pageRef.current)
      if (!actions) return
      for (const a of actions) commitActionToStable(a)
    }

    function commitActionToStable(action: Action) {
      const stable = stableBufferRef.current
      if (!stable) return
      const sCtx = stable.getContext('2d')
      if (!sCtx) return

      if (action.kind === 'clear') {
        sCtx.clearRect(0, 0, stable.width, stable.height)
        return
      }
      if (action.kind === 'erase') {
        eraseAt(sCtx, action.x, action.y, action.radius)
        return
      }
      if (action.kind === 'rect') {
        drawRectShape(sCtx, action.color, action.x1, action.y1, action.x2, action.y2)
        return
      }
      if (action.kind === 'stroke') {
        const lw = lineWidthForTool(action.tool, stable.width)
        if (action.tool === 'pencil') {
          // 연필은 alpha=1 — stable에 직접 그려도 됨
          strokeSmoothPath(sCtx, action.color, action.points, lw, 'round')
        } else {
          // 형광펜은 alpha 누적 회피를 위해 inflightBuffer에 alpha=1로 그린 뒤 alpha=0.35로 한 번만 합성
          const infl = inflightBufferRef.current
          if (!infl) return
          const iCtx = infl.getContext('2d')
          if (!iCtx) return
          iCtx.setTransform(1, 0, 0, 1, 0, 0)
          iCtx.clearRect(0, 0, infl.width, infl.height)
          strokeSmoothPath(iCtx, action.color, action.points, lw, 'butt')
          sCtx.save()
          sCtx.globalAlpha = HIGHLIGHTER_ALPHA
          sCtx.drawImage(infl, 0, 0)
          sCtx.restore()
          // inflight 버퍼는 진행 중 stroke 렌더용으로도 쓰이므로 reset
          iCtx.clearRect(0, 0, infl.width, infl.height)
        }
      }
    }

    function renderInflightToBuffer() {
      const infl = inflightBufferRef.current
      if (!infl) return
      const iCtx = infl.getContext('2d')
      if (!iCtx) return
      iCtx.setTransform(1, 0, 0, 1, 0, 0)
      iCtx.clearRect(0, 0, infl.width, infl.height)
      const s = inflightRef.current
      if (!s || s.points.length === 0) return
      if (s.tool === 'rect') {
        if (s.points.length >= 4) {
          drawRectShape(
            iCtx,
            s.color,
            s.points[0],
            s.points[1],
            s.points[s.points.length - 2],
            s.points[s.points.length - 1],
          )
        }
      } else if (s.tool === 'pencil' || s.tool === 'highlighter') {
        const lw = lineWidthForTool(s.tool, infl.width)
        const cap: CanvasLineCap = s.tool === 'highlighter' ? 'butt' : 'round'
        strokeSmoothPath(iCtx, s.color, s.points, lw, cap)
      }
    }

    function renderVisible() {
      const visible = visibleCanvasRef.current
      const stable = stableBufferRef.current
      const infl = inflightBufferRef.current
      if (!visible || !stable || !infl) return
      const vCtx = visible.getContext('2d')
      if (!vCtx) return
      vCtx.setTransform(1, 0, 0, 1, 0, 0)
      vCtx.clearRect(0, 0, visible.width, visible.height)
      vCtx.drawImage(stable, 0, 0)

      const s = inflightRef.current
      if (s && s.page === pageRef.current && s.points.length > 0) {
        const alpha = s.tool === 'highlighter' ? HIGHLIGHTER_ALPHA : 1
        vCtx.save()
        vCtx.globalAlpha = alpha
        vCtx.drawImage(infl, 0, 0)
        vCtx.restore()
      }
    }

    function appendAction(p: number, action: Action) {
      let list = pageActionsRef.current.get(p)
      if (!list) {
        list = []
        pageActionsRef.current.set(p, list)
      }
      list.push(action)
    }

    // ===== Apply incoming or local draw events =====
    function applyBegin(id: string, t: DrawTool, c: string, p: number) {
      // 기존 진행 중 stroke이 있으면 폐기 (정상적으로는 안 일어남)
      inflightRef.current = { id, tool: t, color: c, page: p, points: [] }
      // inflight 버퍼 초기화
      const infl = inflightBufferRef.current
      const iCtx = infl?.getContext('2d')
      iCtx?.clearRect(0, 0, infl!.width, infl!.height)
    }

    function applyPoint(id: string, xn: number, yn: number) {
      const s = inflightRef.current
      if (!s || s.id !== id) return
      // rect는 마지막 점만 갱신, pencil/highlighter는 누적
      if (s.tool === 'rect') {
        if (s.points.length === 0) {
          s.points.push(xn, yn, xn, yn)
        } else {
          s.points[s.points.length - 2] = xn
          s.points[s.points.length - 1] = yn
        }
      } else {
        s.points.push(xn, yn)
      }
      if (s.page === pageRef.current) {
        renderInflightToBuffer()
        renderVisible()
      }
    }

    function applyEnd(id: string) {
      const s = inflightRef.current
      if (!s || s.id !== id) return
      let action: Action | null = null
      if (s.tool === 'rect') {
        if (s.points.length >= 4) {
          action = {
            kind: 'rect',
            color: s.color,
            x1: s.points[0],
            y1: s.points[1],
            x2: s.points[s.points.length - 2],
            y2: s.points[s.points.length - 1],
          }
        }
      } else if (s.tool === 'pencil' || s.tool === 'highlighter') {
        if (s.points.length >= 2) {
          action = {
            kind: 'stroke',
            tool: s.tool,
            color: s.color,
            points: s.points.slice(),
          }
        }
      }
      if (action) {
        appendAction(s.page, action)
        if (s.page === pageRef.current) commitActionToStable(action)
      }
      inflightRef.current = null
      if (s.page === pageRef.current) renderVisible()
    }

    function applyErase(xn: number, yn: number, radiusN: number, p: number) {
      appendAction(p, { kind: 'erase', x: xn, y: yn, radius: radiusN })
      if (p === pageRef.current) {
        commitActionToStable({ kind: 'erase', x: xn, y: yn, radius: radiusN })
        renderVisible()
      }
    }

    function applyClear(p: number) {
      pageActionsRef.current.set(p, [])
      if (inflightRef.current && inflightRef.current.page === p) {
        inflightRef.current = null
      }
      if (p === pageRef.current) {
        const stable = stableBufferRef.current
        const sCtx = stable?.getContext('2d')
        sCtx?.clearRect(0, 0, stable!.width, stable!.height)
        renderVisible()
      }
    }

    // ===== Imperative API (학생 측 수신) =====
    useImperativeHandle(
      ref,
      () => ({
        receiveDraw(msg: DrawMessage) {
          if (msg.type === 'draw_begin') applyBegin(msg.id, msg.tool, msg.color, msg.page)
          else if (msg.type === 'draw_point') applyPoint(msg.id, msg.x, msg.y)
          else if (msg.type === 'draw_end') applyEnd(msg.id)
          else if (msg.type === 'draw_erase') applyErase(msg.x, msg.y, msg.radius, msg.page)
          else if (msg.type === 'draw_clear') applyClear(msg.page)
        },
        clearPage(p: number) {
          applyClear(p)
        },
        clearAllPages() {
          pageActionsRef.current.clear()
          inflightRef.current = null
          const stable = stableBufferRef.current
          const sCtx = stable?.getContext('2d')
          sCtx?.clearRect(0, 0, stable!.width, stable!.height)
          renderVisible()
        },
      }),
      [],
    )

    // ===== Lecturer pointer handling =====
    const pointerActiveRef = useRef(false)
    const localStrokeIdRef = useRef<string | null>(null)
    const lastSendRef = useRef(0)
    // eraser long-press
    const longpressTimerRef = useRef<number | null>(null)
    const longpressTriggeredRef = useRef(false)
    const eraserDownNormRef = useRef<{ x: number; y: number } | null>(null)
    const eraserMovedBeyondRef = useRef(false)

    // 강의자 도구 ref — pointer event closure에서 최신값
    const toolRef = useRef(tool)
    const colorRef = useRef(color)
    const activeRef = useRef(active)
    useEffect(() => {
      toolRef.current = tool
    }, [tool])
    useEffect(() => {
      colorRef.current = color
    }, [color])
    useEffect(() => {
      activeRef.current = active
    }, [active])

    function clientToNorm(clientX: number, clientY: number): { x: number; y: number } | null {
      const cont = containerRef.current
      const ib = imgBoxRef.current
      if (!cont || !ib || ib.width <= 0 || ib.height <= 0) return null
      const rect = cont.getBoundingClientRect()
      const xn = (clientX - rect.left - ib.left) / ib.width
      const yn = (clientY - rect.top - ib.top) / ib.height
      return { x: xn, y: yn }
    }

    function makeId(): string {
      return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
    }

    const onPointerDown = useCallback(
      (e: React.PointerEvent<HTMLCanvasElement>) => {
        if (mode !== 'lecturer' || !activeRef.current) return
        const norm = clientToNorm(e.clientX, e.clientY)
        if (!norm) return
        if (norm.x < 0 || norm.x > 1 || norm.y < 0 || norm.y > 1) return
        e.preventDefault()
        ;(e.currentTarget as HTMLCanvasElement).setPointerCapture?.(e.pointerId)
        pointerActiveRef.current = true

        const t = toolRef.current
        const c = colorRef.current
        const p = pageRef.current

        if (t === 'eraser') {
          longpressTriggeredRef.current = false
          eraserMovedBeyondRef.current = false
          eraserDownNormRef.current = norm
          if (longpressTimerRef.current !== null) {
            window.clearTimeout(longpressTimerRef.current)
          }
          longpressTimerRef.current = window.setTimeout(() => {
            longpressTimerRef.current = null
            if (!pointerActiveRef.current) return
            if (eraserMovedBeyondRef.current) return
            longpressTriggeredRef.current = true
            applyClear(p)
            send?.({ type: 'draw_clear', page: p })
          }, LONGPRESS_MS)
          // 첫 erase 적용 + 송신
          applyErase(norm.x, norm.y, ERASER_RADIUS_NORM, p)
          send?.({ type: 'draw_erase', x: norm.x, y: norm.y, radius: ERASER_RADIUS_NORM, page: p })
          lastSendRef.current = Date.now()
          return
        }

        // pencil / highlighter / rect
        const id = makeId()
        localStrokeIdRef.current = id
        applyBegin(id, t as DrawTool, c, p)
        applyPoint(id, norm.x, norm.y)
        send?.({ type: 'draw_begin', id, tool: t, color: c, page: p })
        send?.({ type: 'draw_point', id, x: norm.x, y: norm.y })
        lastSendRef.current = Date.now()
      },
      [mode, send],
    )

    const onPointerMove = useCallback(
      (e: React.PointerEvent<HTMLCanvasElement>) => {
        if (mode !== 'lecturer' || !pointerActiveRef.current) return
        const norm = clientToNorm(e.clientX, e.clientY)
        if (!norm) return
        const cx = Math.max(0, Math.min(1, norm.x))
        const cy = Math.max(0, Math.min(1, norm.y))
        const t = toolRef.current
        const p = pageRef.current

        if (t === 'eraser') {
          if (longpressTriggeredRef.current) return
          // long-press 감지: 임계 한 번이라도 초과 시 → drag 모드 확정 + timer 취소
          const start = eraserDownNormRef.current
          if (start && !eraserMovedBeyondRef.current) {
            const dx = cx - start.x
            const dy = cy - start.y
            if (Math.hypot(dx, dy) > LONGPRESS_MOVE_TOL_NORM) {
              eraserMovedBeyondRef.current = true
              if (longpressTimerRef.current !== null) {
                window.clearTimeout(longpressTimerRef.current)
                longpressTimerRef.current = null
              }
            }
          }
          applyErase(cx, cy, ERASER_RADIUS_NORM, p)
          const now = Date.now()
          if (now - lastSendRef.current >= SEND_THROTTLE_MS) {
            lastSendRef.current = now
            send?.({ type: 'draw_erase', x: cx, y: cy, radius: ERASER_RADIUS_NORM, page: p })
          }
          return
        }

        const id = localStrokeIdRef.current
        if (!id) return
        applyPoint(id, cx, cy)
        const now = Date.now()
        // rect는 매 move마다 송신 (drag preview 동기화)
        if (t === 'rect' || now - lastSendRef.current >= SEND_THROTTLE_MS) {
          lastSendRef.current = now
          send?.({ type: 'draw_point', id, x: cx, y: cy })
        }
      },
      [mode, send],
    )

    const finishPointer = useCallback(
      (e: React.PointerEvent<HTMLCanvasElement>) => {
        if (mode !== 'lecturer' || !pointerActiveRef.current) return
        pointerActiveRef.current = false
        if (longpressTimerRef.current !== null) {
          window.clearTimeout(longpressTimerRef.current)
          longpressTimerRef.current = null
        }
        const t = toolRef.current
        const p = pageRef.current
        const norm = clientToNorm(e.clientX, e.clientY)
        const cx = norm ? Math.max(0, Math.min(1, norm.x)) : null
        const cy = norm ? Math.max(0, Math.min(1, norm.y)) : null

        if (t === 'eraser') {
          if (!longpressTriggeredRef.current && cx !== null && cy !== null) {
            applyErase(cx, cy, ERASER_RADIUS_NORM, p)
            send?.({ type: 'draw_erase', x: cx, y: cy, radius: ERASER_RADIUS_NORM, page: p })
          }
          eraserDownNormRef.current = null
          return
        }

        const id = localStrokeIdRef.current
        if (id) {
          if (cx !== null && cy !== null) {
            applyPoint(id, cx, cy)
            send?.({ type: 'draw_point', id, x: cx, y: cy })
          }
          applyEnd(id)
          send?.({ type: 'draw_end', id })
          localStrokeIdRef.current = null
        }
      },
      [mode, send],
    )

    // ===== render =====
    const interactive = mode === 'lecturer' && active
    const cursorStyle =
      interactive ? (tool === 'eraser' ? 'cell' : 'crosshair') : 'default'

    return (
      <canvas
        ref={visibleCanvasRef}
        className="absolute z-30"
        style={{
          left: imgBox ? imgBox.left : 0,
          top: imgBox ? imgBox.top : 0,
          width: imgBox ? imgBox.width : '100%',
          height: imgBox ? imgBox.height : '100%',
          pointerEvents: interactive ? 'auto' : 'none',
          touchAction: interactive ? 'none' : 'auto',
          cursor: cursorStyle,
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finishPointer}
        onPointerCancel={finishPointer}
      />
    )
  },
)
