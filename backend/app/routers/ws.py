"""
WebSocket 라우터
실시간 강의 번역 파이프라인 처리
"""
import asyncio
import base64
import hashlib
import os
import time
import uuid
import io
import re
import wave
from typing import Optional
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.routers import transcripts, slides
from app.services.asr_service import _HALLUCINATION_PATTERNS

# Streaming ASR feature flag — .env 의 ASR_STREAMING=true 일 때만 활성.
# OFF 가 디폴트(안전). ON 시에도 frontend 가 'audio_frame' 메시지를 보낼 때만
# streaming path 가 실제로 사용되며, 'audio'(legacy chunk) 는 항상 동작.
ASR_STREAMING_ENABLED = os.getenv("ASR_STREAMING", "false").lower() == "true"


def _validate_audio(audio_bytes: bytes) -> tuple[bool, str]:
    """WAV 오디오 사전 검증 — ASR 실행 전 노이즈 차단"""
    try:
        with wave.open(io.BytesIO(audio_bytes)) as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            duration = frames / rate
            raw = wav.readframes(frames)

        # 0.3초 미만은 노이즈 버스트
        if duration < 0.3:
            return False, f"발화 너무 짧음 ({duration:.2f}s)"

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples ** 2)))

        # RMS 에너지가 너무 낮으면 빈 구간
        if rms < 0.005:
            return False, f"에너지 너무 낮음 (rms={rms:.4f})"

        return True, ""
    except Exception:
        return True, ""  # 파싱 실패 시 ASR에 넘겨서 판단


def _validate_asr_text(text: str) -> tuple[bool, str]:
    """ASR 결과 텍스트 품질 검증 — 노이즈·환각 탐지.
    영어 비중 가드는 도메인 용어집 (BERT, GPT, API 등) 제외 후 측정 →
    영어 위주 도메인 강의도 false positive 안 나게."""
    text = text.strip()

    if not text:
        return False, "빈 문자열"

    # 공백 제거 후 2자 미만은 의미 없을 가능성 높음
    if len(text.replace(" ", "")) < 2:
        return False, f"너무 짧음: '{text}'"

    # 절대 길이 초과 → 긴 오디오에서 ASR 환각 (실제 발화로 불가능한 길이)
    if len(text) > 200:
        return False, f"텍스트 너무 긺 ({len(text)}자) → ASR 환각 의심"

    # 연속 문자 반복 → ASR 환각 (예: "네네네네", "하하하하")
    if re.search(r"(.{1,3})\1{3,}", text):
        return False, f"반복 패턴 감지: '{text[:30]}...'"

    # 단어 레벨 반복 → 쉼표·공백 구분된 환각 (예: "개그장, 개그장, 개그장, ...")
    words = [w for w in re.split(r"[\s,]+", text) if w]
    if len(words) >= 8:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.3:
            return False, f"단어 반복률 과다 ({unique_ratio:.0%}) → ASR 환각 의심"

    # ASCII (영어/숫자/기호) 비중 가드 — 도메인 용어집 (BERT, API, GPT 등) 은 제외 후 측정.
    # 강사가 영어 도메인 용어를 자주 쓰는 강의 (예: AI/CS) 에서 false positive 방지.
    # 'Thank you' 같은 outro 환각은 용어집에 없으니 그대로 차단됨.
    cleaned = text
    if _nmt_service is not None:
        try:
            ko_terms, en_terms = _nmt_service.get_glossary_terms()
            # 한글/영어 용어 모두 제거 — 한글 용어 (예: "자연어처리") 는 한글 char 빼서
            # 비율 계산에 영향 안 주므로 영어 용어만 빼면 됨. 단순화: 둘 다 제거.
            for term in sorted(en_terms | ko_terms, key=len, reverse=True):
                cleaned = cleaned.replace(term, "")
        except Exception:
            pass
    if len(cleaned) > 0:
        ascii_chars = sum(1 for c in cleaned if ord(c) < 128)
        ascii_ratio = ascii_chars / len(cleaned)
        if ascii_ratio > 0.6:
            return False, f"영어 비중 과다 ({ascii_ratio:.0%}, glossary 제외 후) → ASR 환각 의심"

    # 환각 정형구 sentence-level 재검사 — segment 레벨 (asr_service / streaming_asr_service
    # 의 _transcribe_buffer) 에서 못 잡은 multi-segment 결합 케이스 catch.
    # 예: Whisper 가 "다음 영상에서 만나요." + "만나요" 두 segment 로 쪼개면 두 번째
    # "만나요" 단독은 segment 패턴에 안 걸림. 단어가 buffer 에 누적되어 sentence 로
    # 합쳐진 후에야 전체 정형구가 보임.
    if _HALLUCINATION_PATTERNS.search(text):
        return False, f"환각 정형구 매칭 (sentence-level): {text[:50]!r}"

    return True, ""


try:
    import kss as _kss  # 한국어 문장 분리 (마침표 + 종결어미 기반)
    _kss_available = True
except Exception as _e:
    _kss_available = False
    print(f"[Split] kss 미설치 — 정규식 fallback 사용: {_e}", flush=True)


def _split_korean_sentences(text: str) -> list[str]:
    """ASR 한 덩어리 결과를 문장 단위로 쪼개 NMT/broadcast를 병렬화하기 위한 분할.
    1차: kss (한국어 종결어미 패턴까지 인식 — 마침표 누락 발화도 분할)
    2차: 정규식 fallback (마침표·물음표·느낌표 + 공백)
    분할 결과가 1개면 기존과 동일하게 처리됨 (손해 없음).
    호흡 짧은 화자가 만든 5초+ 한 덩어리에서 첫 자막 latency를 줄이는 게 목적."""
    text = text.strip()
    if not text:
        return []
    if _kss_available:
        try:
            parts = [p.strip() for p in _kss.split_sentences(text) if p.strip()]
            if parts:
                return parts
        except Exception as e:
            print(f"[Split] kss 분할 실패 → fallback: {e}", flush=True)
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    return parts or [text]


router = APIRouter(prefix="/ws", tags=["WebSocket"])

# 서비스 인스턴스 (main.py에서 주입)
_asr_service = None
_nmt_service = None
_ocr_service = None
_streaming_asr_service = None  # ASR_STREAMING=true 시에만 주입됨


def set_asr_service(service):
    global _asr_service
    _asr_service = service


def set_nmt_service(service):
    global _nmt_service
    _nmt_service = service


def set_ocr_service(service):
    global _ocr_service
    _ocr_service = service


def set_streaming_asr_service(service):
    global _streaming_asr_service
    _streaming_asr_service = service


def init_streaming_asr_service(whisper_model):
    """chunk path 의 _asr_semaphore 를 공유하는 ASRStreamingService 생성/주입.
    main.py 가 ASR 모델 초기화 후 호출. 두 path 가 동일 GPU 자원을 직렬화하도록.
    """
    from app.services.streaming_asr_service import ASRStreamingService
    global _streaming_asr_service
    _streaming_asr_service = ASRStreamingService(whisper_model, gpu_lock=_asr_semaphore)


class ConnectionManager:
    """WebSocket 연결 관리자"""

    def __init__(self):
        self.lecturer: Optional[WebSocket] = None
        self.lecturer_name: str = "professor"
        self.students: list[WebSocket] = []
        self.student_info: dict[WebSocket, dict] = {}  # ws -> {id, name}
        self.current_slide_id: Optional[str] = None
        self.current_page: int = 1
        self.is_lecture_started: bool = False
        self.is_paused: bool = False
        self.presentation_mode: str = "slide"  # 'slide' or 'screen'
        self.current_session_id: Optional[str] = None  # 자막 저장 세션
        self.lecture_title: str = ""  # 강사가 설정한 강의 제목
        self._lock = asyncio.Lock()  # students 리스트 동시 접근 방지
        self._tasks: set[asyncio.Task] = set()  # 실행 중인 태스크 추적

        # 페이지별 시각 event 영속 저장소 — 신규 입장 학생 / 페이지 복귀 시 재생용.
        # key: (slide_id, page) 1-based, value: 그 페이지에서 일어난 모든 draw event 메시지.
        # draw_clear 가 도착하면 그 페이지 list 비움 (강사 "전체 지우기" 버튼 의도 보존).
        # lecture_end 시점에 비우지 않음 — 다음 강의 시작 시 reset.
        self.page_draw_events: dict[tuple[str, int], list[dict]] = {}

    def track_task(self, task: asyncio.Task):
        """태스크 등록 — 완료 시 자동 제거"""
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def disconnect_lecturer(self):
        self.lecturer = None
        self.lecturer_name = "professor"
        self.lecture_title = ""
        # 강의 중 비정상 종료 — 자막 저장 마무리
        if self.is_lecture_started and self.current_session_id:
            ended_id = transcripts.end_session(self.current_session_id)
            print(f"[WS] 강의자 비정상 종료, 자막 세션 자동 저장: {ended_id}")
            # NMT 용어집도 해제 (잔존 매핑 방지)
            if _nmt_service:
                try:
                    _nmt_service.set_glossary(None)
                except Exception:
                    pass
            self.current_session_id = None
            self.is_lecture_started = False
        # 슬라이드/페이지/발표모드 상태 리셋 — 다음 강의자 재연결 시 stale state 방지
        self.current_slide_id = None
        self.current_page = 1
        self.presentation_mode = "slide"
        self.is_paused = False
        print("[WS] 강의자 연결 해제")

    def disconnect_student(self, websocket: WebSocket):
        if websocket in self.students:
            self.students.remove(websocket)
        self.student_info.pop(websocket, None)
        print(f"[WS] 수강자 연결 해제 (남은 인원: {len(self.students)}명)")

    def participants_payload(self) -> dict:
        """참여자 목록 스냅샷"""
        return {
            "type": "participants",
            "lecturer": {
                "name": self.lecturer_name,
                "connected": self.lecturer is not None,
            },
            "students": [
                {
                    "id": info["id"],
                    "name": info["name"],
                }
                for ws, info in self.student_info.items()
                if ws in self.students
            ],
        }

    async def broadcast_to_students(self, message: dict):
        """모든 수강자에게 메시지 전송 (Lock으로 동시 접근 보호)"""
        async with self._lock:
            students_snapshot = list(self.students)

        results = await asyncio.gather(
            *[student.send_json(message) for student in students_snapshot],
            return_exceptions=True,
        )

        disconnected = [
            ws for ws, result in zip(students_snapshot, results)
            if isinstance(result, Exception)
        ]
        if disconnected:
            async with self._lock:
                for ws in disconnected:
                    if ws in self.students:
                        self.students.remove(ws)
                        print(f"[WS] 수강자 연결 해제 (남은 인원: {len(self.students)}명)")

    async def broadcast_all(self, message: dict):
        """강의자 + 모든 수강자에게 전송 (채팅용)"""
        await self.broadcast_to_students(message)
        if self.lecturer is not None:
            try:
                await self.lecturer.send_json(message)
            except Exception:
                self.disconnect_lecturer()

    async def broadcast_student_count(self):
        """현재 접속 중인 수강자 수를 모든 수강자에게 전송"""
        await self.broadcast_to_students({
            "type": "student_count",
            "count": len(self.students),
        })

    async def broadcast_participants(self):
        """참여자 목록을 강의자 + 모든 수강자에게 전송"""
        await self.broadcast_all(self.participants_payload())


manager = ConnectionManager()

# ASR: GPU 직렬화 (단일 모델 인스턴스, 동시 호출 방지)
_asr_semaphore = asyncio.Semaphore(1)
# NMT: GPU 모델 인스턴스 보호 (CT2 Translator 비thread-safe + ASR 와 GPU 자원 분리 위해 직렬화)
_nmt_semaphore = asyncio.Semaphore(1)
_MAX_QUEUED_AUDIO = 2   # chunk path: ASR 대기 큐 최대 발화 수 — 초과 시 신규 발화 스킵
_queued_audio_count = 0  # 현재 ASR 세마포어 대기 중인 발화 수
_utterance_seq = 0       # 발화 순서 번호 (프론트 순서 보장용)

# Streaming path 의 발화 시작 시각 — 첫 audio_frame 수신 시 set 되고, 첫 finalize
# 직후 / flush / reset 시 None 으로 복귀. [STREAM-FIRST] latency 로깅용.
# 의미: backend 가 인지한 발화 시작 (frame 첫 도착) → 첫 문장 broadcast 직전.
# chunk path 의 [FIRST seq=N] 와 직접 비교는 안 됨 (chunk 는 발화 종료 후부터,
# streaming 은 발화 중간부터 측정) — 두 path 의 절대 lat 값을 같이 보고 판단.
_streaming_speech_start_at: Optional[float] = None
# 발화 시작 wall time (강사 PC Date.now() 기준 ms) — 첫 frame 의 sentAt.
# 학생측 useTTS 가 audio.start = speechStartAt + offset 으로 sync 맞추는 데 사용.
# 학생 시각 정보 (그림/커서) 와 정확히 동일 시간선 정렬 위해.
_streaming_speech_start_wall_at: Optional[int] = None
# 발화 시작 시점의 강사 현재 페이지 — 학생측 page-anchor 용.
# transcription 도착 시 학생이 강제로 그 페이지로 set 한 후 자막/오디오 재생.
# 시계 미스매치가 있어도 발화가 강사 페이지 위에서 재생되는 강한 보장.
_streaming_speech_start_page: Optional[int] = None


def _ts(message: dict) -> dict:
    """incoming 메시지의 lecturerTimestamp 를 outgoing payload spread 용으로 추출.
    sync 작업 (학생측 useTimelineSync) 가 visual event 와 TTS 진도 매칭하는 데 사용.
    None 이면 빈 dict 반환 — payload 에 노이즈 추가 안 함."""
    ts = message.get("lecturerTimestamp")
    return {"lecturerTimestamp": ts} if ts is not None else {}


async def _reset_streaming_state():
    """streaming path 의 buffer + speech_start_at 동시 초기화.
    lecture_end / lecture_pause / lecturer disconnect 등 발화 boundary 가 끊기는
    시점에서 호출. service 가 None 이면 timestamp 만 리셋.
    """
    global _streaming_speech_start_at, _streaming_speech_start_wall_at, _streaming_speech_start_page
    if _streaming_asr_service is not None:
        await _streaming_asr_service.reset()
    _streaming_speech_start_at = None
    _streaming_speech_start_wall_at = None
    _streaming_speech_start_page = None

PING_INTERVAL = 20  # 서버 → 클라이언트 ping 주기 (초)
PING_TIMEOUT  = 10  # pong 미응답 허용 시간 (초)


async def heartbeat(websocket: WebSocket, pong_event: asyncio.Event | None = None):
    """서버 → 클라이언트 주기적 ping 전송, pong_event 제공 시 타임아웃 감지"""
    while websocket.client_state == WebSocketState.CONNECTED:
        await asyncio.sleep(PING_INTERVAL)
        try:
            if pong_event:
                pong_event.clear()
            await websocket.send_json({"type": "ping"})
            if pong_event:
                try:
                    await asyncio.wait_for(pong_event.wait(), timeout=PING_TIMEOUT)
                except asyncio.TimeoutError:
                    print(f"[WS] pong 미응답 → 좀비 연결 강제 종료")
                    await websocket.close()
                    break
        except Exception:
            break


async def run_with_heartbeat(handler, websocket: WebSocket, pong_event: asyncio.Event | None = None):
    """핸들러 종료 시 heartbeat도 함께 취소"""
    handler_task   = asyncio.ensure_future(handler)
    heartbeat_task = asyncio.ensure_future(heartbeat(websocket, pong_event))

    done, pending = await asyncio.wait(
        [handler_task, heartbeat_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@router.websocket("/pipeline")
async def websocket_pipeline(websocket: WebSocket):
    """
    강의자/수강자 WebSocket 연결

    메시지 타입:
    - register: 역할 등록 (lecturer/student)
    - audio: 오디오 데이터 (강의자 → 서버)
    - screen: 화면 캡처 데이터 (강의자 → 서버)
    - slide_select: 슬라이드 선택 (강의자 → 서버)
    """
    role = None

    try:
        # 첫 메시지로 역할 확인
        await websocket.accept()
        init_msg = await websocket.receive_json()

        if init_msg.get("type") != "register":
            await websocket.close(code=4000, reason="첫 메시지는 register여야 합니다")
            return

        role = init_msg.get("role")
        name = (init_msg.get("name") or "").strip()

        if role == "lecturer":
            client_host = websocket.client.host if websocket.client else ""
            # 강의자는 강의자 PC 자체(loopback)에서만 허용 — LAN 접속 수강자가 역할 가로채기 방지
            if client_host not in ("127.0.0.1", "::1"):
                print(f"[WS] 강의자 역할 거부 (외부 호스트): {client_host}")
                await websocket.close(code=4403, reason="lecturer role requires localhost")
                return
            # 이미 강의자가 연결되어 있으면 중복 연결 거부
            if manager.lecturer is not None:
                print("[WS] 강의자 역할 거부 (중복 연결)")
                await websocket.close(code=4409, reason="lecturer already connected")
                return
            manager.lecturer = websocket
            manager.lecturer_name = name or "professor"
            print(f"[WS] 강의자 연결됨 (이름: {manager.lecturer_name})")
            await websocket.send_json({
                "type": "registered",
                "role": "lecturer",
                "asr_streaming": ASR_STREAMING_ENABLED,
            })
            if manager.lecture_title:
                await websocket.send_json({
                    "type": "lecture_title",
                    "title": manager.lecture_title,
                })
            await manager.broadcast_participants()
            await run_with_heartbeat(handle_lecturer(websocket), websocket)

        elif role == "student":
            student_id = str(uuid.uuid4())
            student_name = name or f"Guest{len(manager.students) + 1}"
            manager.students.append(websocket)
            manager.student_info[websocket] = {"id": student_id, "name": student_name}
            print(f"[WS] 수강자 연결됨 (이름: {student_name}, 총 {len(manager.students)}명)")
            await websocket.send_json({
                "type": "registered",
                "role": "student",
                "id": student_id,
                "name": student_name,
            })
            if manager.lecture_title:
                await websocket.send_json({
                    "type": "lecture_title",
                    "title": manager.lecture_title,
                })
            await manager.broadcast_student_count()
            await manager.broadcast_participants()
            # 현재 강의 상태 즉시 전송
            if manager.is_lecture_started:
                await websocket.send_json({
                    "type": "lecture_start",
                    "slide_id": manager.current_slide_id,
                })
                await websocket.send_json({
                    "type": "presentation_mode",
                    "mode": manager.presentation_mode,
                })
                if manager.current_slide_id:
                    await websocket.send_json({
                        "type": "page_change",
                        "slide_id": manager.current_slide_id,
                        "page": manager.current_page,
                    })
                if manager.is_paused:
                    await websocket.send_json({
                        "type": "lecture_pause",
                    })
            elif manager.current_slide_id:
                # 강의 시작 전이라도 슬라이드가 선택된 상태면 수강자에게 전달
                await websocket.send_json({
                    "type": "slide_select",
                    "slide_id": manager.current_slide_id,
                })

            # 신규 입장 학생 — 현재 강의의 모든 페이지 누적 필기 replay 전송.
            # 학생측 DrawingCanvas 가 페이지별 actions Map 에 채워 페이지 전환/복귀
            # 시 그 페이지 그림이 그대로 재현됨. 강의 도중 입장이든, 페이지 왔다갔다
            # 든 모두 보호.
            if manager.page_draw_events:
                replay_events = []
                for (sid, page), events in manager.page_draw_events.items():
                    if sid == manager.current_slide_id:
                        replay_events.extend(events)
                if replay_events:
                    await websocket.send_json({
                        "type": "drawings_replay",
                        "events": replay_events,
                    })
                    print(f"[WS] 신규 학생에게 누적 필기 {len(replay_events)}건 replay 전송")

            pong_event = asyncio.Event()
            await run_with_heartbeat(handle_student(websocket, pong_event), websocket, pong_event)

        else:
            await websocket.close(code=4001, reason="올바른 역할이 아닙니다")

    except WebSocketDisconnect:
        if role == "lecturer":
            manager.disconnect_lecturer()
            # streaming buffer 비움 — 다음 강의자 연결 시 stale 잔재 방지
            await _reset_streaming_state()
            await manager.broadcast_participants()
        elif role == "student":
            manager.disconnect_student(websocket)
            await manager.broadcast_student_count()
            await manager.broadcast_participants()


async def handle_lecturer(websocket: WebSocket):
    """강의자 메시지 처리"""
    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "pong":
                pass  # heartbeat 응답 확인

            elif msg_type == "audio":
                audio_size = len(message.get("audio", "")) * 3 // 4 // 1024
                task = asyncio.create_task(process_audio(message))
                manager.track_task(task)

            elif msg_type == "audio_frame" and ASR_STREAMING_ENABLED:
                # streaming PCM frame — 발화 중 200ms 단위로 도착, 종결어미 시점에 finalize
                task = asyncio.create_task(process_audio_frame(message))
                manager.track_task(task)

            elif msg_type == "audio_frame_flush" and ASR_STREAMING_ENABLED:
                # frontend VAD onSpeechEnd — buffer 잔여분 강제 finalize
                task = asyncio.create_task(process_audio_frame_flush(message))
                manager.track_task(task)

            # WebRTC 시그널링 — 강의자가 특정 수강자에게 offer/ICE 전달
            elif msg_type == "webrtc_offer" or msg_type == "webrtc_ice":
                target_id = message.get("target")
                if not target_id:
                    continue
                payload = {"type": msg_type}
                if msg_type == "webrtc_offer":
                    payload["sdp"] = message.get("sdp")
                else:
                    payload["candidate"] = message.get("candidate")
                # target student 찾아 forwarding
                for ws, info in list(manager.student_info.items()):
                    if info.get("id") == target_id and ws in manager.students:
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            pass
                        break

            elif msg_type == "slide_select":
                manager.current_slide_id = message.get("slide_id")
                manager.current_page = 1
                print(f"[WS] 슬라이드 선택: {manager.current_slide_id}")
                await manager.broadcast_to_students({
                    "type": "slide_select",
                    "slide_id": manager.current_slide_id,
                    **_ts(message),
                })

            elif msg_type == "page_change":
                manager.current_page = message.get("page", 1)
                print(f"[WS] 페이지 변경: {manager.current_page}")
                # 마지막 본 페이지를 메타에 저장 — 다음 /load 시 그 페이지부터 시작
                if manager.current_slide_id:
                    slides.update_last_page(manager.current_slide_id, manager.current_page)
                await manager.broadcast_to_students({
                    "type": "page_change",
                    "slide_id": manager.current_slide_id,
                    "page": manager.current_page,
                    **_ts(message),
                })

            elif msg_type == "lecture_start":
                manager.is_lecture_started = True
                manager.current_slide_id = message.get("slide_id")
                manager.presentation_mode = message.get("mode", "slide")
                # 새 강의 — 이전 강의의 누적 필기 폐기 (replay 시 stale 방지)
                manager.page_draw_events.clear()
                # 자막 세션 시작 — session_id 발급
                manager.current_session_id = transcripts.start_session(
                    manager.current_slide_id
                )
                # 슬라이드 도메인 용어집 → 실시간 NMT 에 주입 (도메인 용어 환각 억제)
                if _nmt_service and manager.current_slide_id:
                    try:
                        from app.routers.slides import get_slide_glossary
                        glossary = get_slide_glossary(manager.current_slide_id)
                        _nmt_service.set_glossary(glossary)
                    except Exception as e:
                        print(f"[WS] 용어집 주입 실패 (무시): {e}")
                print(f"[WS] 강의 시작: {manager.current_slide_id}, 모드: {manager.presentation_mode}, 세션: {manager.current_session_id}")
                # 강의자에게 session_id 회신 (다운로드 시 필요)
                await websocket.send_json({
                    "type": "session_started",
                    "session_id": manager.current_session_id,
                })
                await manager.broadcast_to_students({
                    "type": "lecture_start",
                    "slide_id": manager.current_slide_id,
                    "session_id": manager.current_session_id,
                    **_ts(message),
                })
                # 발표 모드도 함께 전송
                await manager.broadcast_to_students({
                    "type": "presentation_mode",
                    "mode": manager.presentation_mode,
                    **_ts(message),
                })

            elif msg_type == "lecture_end":
                manager.is_lecture_started = False
                manager.is_paused = False
                # NMT 용어집 해제 — 다음 강의에서 잔존 용어가 오작용하지 않도록
                if _nmt_service:
                    try:
                        _nmt_service.set_glossary(None)
                    except Exception:
                        pass
                # 강의 종료 직전 — streaming buffer 안의 미완료 audio 를 강제 finalize 해
                # 마지막 발화가 손실되지 않도록. flush 후 reset 순서.
                # (reset 만 하면 마지막 1~2 sentence 가 buffer 째 폐기됨)
                if _streaming_asr_service is not None:
                    try:
                        # speech_start_wall 정확히 모르므로 마지막 알려진 값 사용.
                        last_speech_start = _streaming_speech_start_wall_at
                        sentences = await _streaming_asr_service.flush()
                        for s in sentences or []:
                            print(f"[ASR-STREAM lecture_end flush] {s}", flush=True)
                            await _broadcast_streaming_sentence(s, None, last_speech_start)
                    except Exception as e:
                        print(f"[WS] lecture_end 마지막 flush 오류 (무시): {e}", flush=True)
                # 그 후 streaming buffer 비움 — 다음 강의에서 stale 잔재 합성 방지
                await _reset_streaming_state()
                # 자막 세션 종료 — jsonl → 최종 json 병합
                ended_id = transcripts.end_session(manager.current_session_id)
                print(f"[WS] 강의 종료 (세션: {ended_id})")
                await manager.broadcast_to_students({
                    "type": "lecture_end",
                    "session_id": ended_id,
                    **_ts(message),
                })
                manager.current_session_id = None
                # 슬라이드/페이지/발표모드 상태 리셋 — 다음 강의 시작 시 stale state 방지
                manager.current_slide_id = None
                manager.current_page = 1
                manager.presentation_mode = "slide"

            elif msg_type == "lecture_pause":
                manager.is_paused = True
                print("[WS] 강의 일시정지")
                # streaming buffer 비움 — 재개 시 stale audio 가 새 문장과 합쳐지지 않도록
                await _reset_streaming_state()
                await manager.broadcast_to_students({
                    "type": "lecture_pause",
                    **_ts(message),
                })

            elif msg_type == "lecture_resume":
                manager.is_paused = False
                print("[WS] 강의 재개")
                await manager.broadcast_to_students({
                    "type": "lecture_resume",
                    **_ts(message),
                })

            elif msg_type == "presentation_mode":
                manager.presentation_mode = message.get("mode", "slide")
                print(f"[WS] 발표 모드 변경: {manager.presentation_mode}")
                await manager.broadcast_to_students({
                    "type": "presentation_mode",
                    "mode": manager.presentation_mode,
                    **_ts(message),
                })

            elif msg_type == "chat_message":
                text = (message.get("text") or "").strip()
                if not text:
                    continue
                await manager.broadcast_all({
                    "type": "chat_message",
                    "id": str(uuid.uuid4()),
                    "sender": "lecturer",
                    "name": manager.lecturer_name,
                    "text": text,
                    "timestamp": int(time.time() * 1000),
                })

            elif msg_type == "lecture_title":
                title = (message.get("title") or "").strip()
                manager.lecture_title = title
                print(f"[WS] 강의 제목 설정: {title!r}")
                await manager.broadcast_all({
                    "type": "lecture_title",
                    "title": title,
                })

            elif msg_type == "lecturer_name":
                new_name = (message.get("name") or "").strip() or "professor"
                manager.lecturer_name = new_name
                print(f"[WS] 강사 이름 변경: {new_name}")
                await manager.broadcast_participants()

            elif msg_type == "cursor":
                # 강의자 커서 상태 → 수강자에게만 브로드캐스트 (강의자에게 재전송 X)
                await manager.broadcast_to_students({
                    "type": "cursor",
                    "x": message.get("x", 0),
                    "y": message.get("y", 0),
                    "visible": message.get("visible", False),
                    "color": message.get("color", "#60A5FA"),
                    **_ts(message),
                })

            elif msg_type in ("draw_begin", "draw_point", "draw_end", "draw_erase", "draw_clear"):
                # 강의자 필기 이벤트 → 수강자 forward + 페이지별 store 영속화.
                # 좌표는 슬라이드 이미지 영역 기준 0~1 정규화 (커서와 동일 좌표계).
                # store 에 누적해 신규 입장 학생 / 페이지 복귀 시 재생.
                payload = {"type": msg_type, **_ts(message)}
                for key in ("id", "tool", "color", "page", "x", "y", "radius"):
                    if key in message:
                        payload[key] = message[key]
                await manager.broadcast_to_students(payload)

                # 페이지별 영속화 — slide_id + page 키. slide_id 없으면 skip
                # (강의 시작 전 마이크 테스트 단계 등).
                slide_id = manager.current_slide_id
                page = message.get("page")
                if slide_id and isinstance(page, int):
                    key = (slide_id, page)
                    if msg_type == "draw_clear":
                        # 그 페이지의 누적 그림 모두 삭제
                        manager.page_draw_events.pop(key, None)
                    else:
                        manager.page_draw_events.setdefault(key, []).append(payload)

            elif msg_type == "participants_request":
                await websocket.send_json(manager.participants_payload())

    except WebSocketDisconnect:
        manager.disconnect_lecturer()
        await _reset_streaming_state()
        await manager.broadcast_participants()


async def handle_student(websocket: WebSocket, pong_event: asyncio.Event | None = None):
    """수강자 메시지 처리 (주로 수신만 함)"""
    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "pong":
                if pong_event:
                    pong_event.set()

            elif msg_type == "chat_message":
                text = (message.get("text") or "").strip()
                if not text:
                    continue
                info = manager.student_info.get(websocket, {})
                await manager.broadcast_all({
                    "type": "chat_message",
                    "id": str(uuid.uuid4()),
                    "sender": "student",
                    "name": info.get("name", "익명"),
                    "student_id": info.get("id"),
                    "text": text,
                    "timestamp": int(time.time() * 1000),
                })

            elif msg_type == "participants_request":
                await websocket.send_json(manager.participants_payload())

            elif msg_type == "student_rename":
                new_name = (message.get("name") or "").strip()
                if not new_name:
                    continue
                info = manager.student_info.get(websocket)
                if info is None:
                    continue
                info["name"] = new_name
                print(f"[WS] 수강자 이름 변경: {info.get('id')} → {new_name}")
                await manager.broadcast_participants()

            # WebRTC 시그널링 — 수강자가 강의자에게 answer/ICE 전달
            elif msg_type == "webrtc_answer" or msg_type == "webrtc_ice":
                if manager.lecturer is None:
                    continue
                info = manager.student_info.get(websocket, {})
                payload = {"type": msg_type, "sender": info.get("id")}
                if msg_type == "webrtc_answer":
                    payload["sdp"] = message.get("sdp")
                else:
                    payload["candidate"] = message.get("candidate")
                try:
                    await manager.lecturer.send_json(payload)
                except Exception:
                    pass

    except WebSocketDisconnect:
        manager.disconnect_student(websocket)
        await manager.broadcast_student_count()
        await manager.broadcast_participants()


async def process_audio(message: dict):
    """
    오디오 처리 파이프라인: 오디오 → ASR(GPU) → NMT(GPU) → 수강자 전송
    TTS는 수강자 브라우저에서 WASM(piper-tts-web)으로 처리

    - _asr_semaphore: ASR 직렬화 (한 번에 하나의 발화만 ASR 모델 사용)
    - _nmt_semaphore: NMT 직렬화 (ASR 해제 직후 다음 발화 ASR 시작 가능 — pipeline parallelism)
    - seq: 발화 순서 번호 (NMT 처리 시간 편차로 인한 순서 역전 대응)
    - 큐 포화 방지: _MAX_QUEUED_AUDIO 초과 또는 6s 이상 대기 시 스킵
    """
    global _queued_audio_count, _utterance_seq

    if not all([_asr_service, _nmt_service]):
        print("[WS] 서비스가 초기화되지 않았습니다")
        return

    try:
        t_start = time.perf_counter()

        # 일시정지 race 차단 — 강의자가 발화 중간에 [일시정지] 누른 직후
        # 이미 in-flight 상태였던 audio chunk 가 backend 에 도착하는 케이스 대응.
        # frontend handleAudioData 의 isPaused 가드는 "다음" chunk 부터 차단하므로
        # 호흡 시점에 떠있던 마지막 chunk 1개가 그대로 도착함 → ASR/NMT 거쳐 학생에게
        # 자막 1줄 + TTS 음성 1번 흘러나가 일시정지 의도와 어긋남.
        # 여기서 backend state(is_paused) 기준으로 한 번 더 차단해 UI/동작 일관성 보장.
        if manager.is_paused:
            return

        sent_at = message.get("sentAt")

        audio_b64 = message.get("audio", "") or message.get("data", "")
        if not audio_b64:
            return
        audio_bytes = base64.b64decode(audio_b64)

        ok, reason = _validate_audio(audio_bytes)
        if not ok:
            return

        # speech_start_wall 근사 — chunk path 는 sentAt 이 chunk 송출 시점 (≈speech 끝)
        # 이라 chunk audio 길이 만큼 빼서 speech 시작 시점 추정.
        # 16kHz × int16 = 32 bytes/ms. sample_rate 가 다르면 sample_rate*2/1000 으로 보정.
        sample_rate = int(message.get("sample_rate", 16000))
        bytes_per_ms = (sample_rate * 2) / 1000
        audio_duration_ms = int(len(audio_bytes) / bytes_per_ms) if bytes_per_ms > 0 else 0
        speech_start_wall = (sent_at - audio_duration_ms) if isinstance(sent_at, int) else None
        # page-anchor — chunk 도착 즉시 강사 현재 페이지 캡처. ASR/NMT 처리 동안 강사가
        # 페이지 넘기더라도 이 발화가 시작될 때의 페이지로 학생측이 강제 set 하도록.
        speech_start_page = manager.current_page

        # ASR 큐 포화 방지: 이미 충분한 발화가 대기 중이면 신규 발화 스킵.
        # 동시에 강사에게 알림 — 발화가 시스템에 도달 못 했음을 알려 다시 말할 기회.
        if _queued_audio_count >= _MAX_QUEUED_AUDIO:
            print(f"[QUEUE] ASR 대기 포화 ({_queued_audio_count}개) → 스킵", flush=True)
            if manager.lecturer:
                try:
                    await manager.lecturer.send_json({
                        "type": "asr_overloaded",
                        "queued": _queued_audio_count,
                    })
                except Exception:
                    pass
            return

        _queued_audio_count += 1
        _utterance_seq += 1
        seq = _utterance_seq
        t_enqueue = time.perf_counter()

        # Phase 1: ASR — GPU 직렬화
        async with _asr_semaphore:
            _queued_audio_count -= 1

            wait_s = time.perf_counter() - t_enqueue
            if wait_s > 6.0:
                print(f"[QUEUE] seq={seq} 대기 {wait_s:.1f}s → stale 스킵", flush=True)
                return

            t_asr = time.perf_counter()
            korean_text = await asyncio.to_thread(
                _asr_service.transcribe, audio_bytes
            )
            t_asr_done = time.perf_counter()

            ok, reason = _validate_asr_text(korean_text)
            if not ok:
                # 차단된 발화 — 강사에게 알림 보내 "방금 발화가 차단됐다" 안내.
                # 강사가 의도한 발화가 환각 가드에 걸렸을 수 있어 다시 말할 기회 제공.
                if manager.lecturer:
                    try:
                        await manager.lecturer.send_json({
                            "type": "asr_blocked",
                            "reason": reason,
                            "preview": korean_text[:80],
                        })
                    except Exception:
                        pass
                print(f"[ASR  seq={seq}] 차단 — {reason}", flush=True)
                return

            print(f"[ASR  seq={seq}] {korean_text}", flush=True)

        # _asr_semaphore 해제 → 다음 발화 ASR이 즉시 시작 가능 (pipeline parallelism)
        # Phase 2: NMT — 문장 단위 분할 처리. ASR이 한 덩어리(5초+)로 보내도 NMT/broadcast는
        # 문장별로 순차 송출 → 첫 자막이 빨리 뜸. 분할 결과 1개면 기존과 동일.
        sentences = _split_korean_sentences(korean_text)

        t_nmt = time.perf_counter()
        # ASR duration — chunk 발화 전체 한 번만 측정. 같은 seq 의 모든 문장이 공유.
        asr_ms = int((t_asr_done - t_asr) * 1000)

        async def _process_sentence(sub_seq: int, sentence: str) -> None:
            """한 문장을 NMT → broadcast. NMT 완료 즉시 송출되어 첫 자막 latency 단축."""
            t_nmt_call = time.perf_counter()
            async with _nmt_semaphore:
                english = await asyncio.to_thread(
                    _nmt_service.translate, sentence, "ko", "en", 512
                )
            nmt_ms = int((time.perf_counter() - t_nmt_call) * 1000)
            # NMT 실패/빈 결과 fallback — 한국어 원문이라도 학생에게 자막으로 전달.
            # 음성 재생은 어차피 영어 voice 없이 안 됨 (translated 비면 useTTS skip),
            # 그러나 자막은 학생이 한국어로라도 볼 수 있어야 손실 없음.
            if not english.strip():
                english = ""
                print(f"[NMT 실패] seq={seq}.{sub_seq} → 한국어 자막 fallback", flush=True)
            else:
                print(f"[NMT  seq={seq}.{sub_seq}] {english}", flush=True)
            # 첫 자막 latency — 분할 효과 측정용 (마지막 자막은 LATENCY 로그의 '전체')
            if sub_seq == 0:
                print(
                    f"[FIRST seq={seq}] 첫 자막 {time.perf_counter() - t_start:.2f}s",
                    flush=True,
                )

            if manager.current_session_id:
                transcripts.append_segment(
                    manager.current_session_id, sentence, english
                )

            # TTS는 수강자 브라우저(WASM)에서 처리 — audio 필드 없이 텍스트만 전송
            # asrMs / nmtMs: 서버 단일 시계로 측정한 처리 시간 (시계 동기화 무관).
            # frontend 가 ttsMs / 전체 latency 와 합쳐 단계별 표시.
            payload = {
                "type": "transcription",
                "seq": seq,
                "sub_seq": sub_seq,           # 같은 seq 안 문장 순서 (frontend 정렬용)
                "total_sub": len(sentences),  # 한 발화의 총 문장 수
                "original": sentence,
                "translated": english,
                "sentAt": sent_at,
                "speechStartAt": speech_start_wall,
                "pageAtSpeechStart": speech_start_page,
                "asrMs": asr_ms,
                "nmtMs": nmt_ms,
            }
            await manager.broadcast_to_students(payload)
            if manager.lecturer:
                try:
                    await manager.lecturer.send_json(payload)
                except Exception:
                    pass

        # gather로 launch — _nmt_semaphore(=1)가 직렬화하지만, 각 task는 NMT 완료되는 즉시
        # broadcast → 첫 문장이 가장 먼저 뜸. NMT 시간 합은 단일 호출과 거의 동일.
        await asyncio.gather(*[
            _process_sentence(i, s) for i, s in enumerate(sentences)
        ])
        t_nmt_done = time.perf_counter()

        print(
            f"[LATENCY] seq={seq} ({len(sentences)}문장) | 대기={t_asr - t_start:.2f}s | "
            f"ASR={t_asr_done - t_asr:.2f}s | "
            f"NMT={t_nmt_done - t_nmt:.2f}s | "
            f"전체={t_nmt_done - t_start:.2f}s",
            flush=True,
        )

    except Exception as e:
        print(f"[WS] 오디오 처리 오류: {e}")


async def _broadcast_streaming_sentence(
    sentence: str,
    sent_at: Optional[int],
    speech_start_wall: Optional[int] = None,
    speech_start_page: Optional[int] = None,
) -> None:
    """streaming path: finalize 된 한국어 문장 1개를 NMT → broadcast.
    seq 는 전역 카운터에서 1 sentence = 1 seq 로 발급. sub_seq/total_sub 는
    chunk path 와 호환 위해 (0, 1) 고정.
    asrMs: 발화 시작 (첫 frame 도착) → 이 sentence finalize 직전 시간.
           streaming 의 ASR 단독 시간을 정확히 분리해 내는 건 어려워
           (transcribe 가 매 cycle 마다 호출되므로) — 발화 시작부터 누적된 시간으로 근사.
    speech_start_wall: 강사 PC 시계 기준 이 utterance 가 시작된 시점 (첫 frame sentAt).
                       학생측 useTTS 가 audio.start = speechStartAt + offset 으로
                       시각 정보 (그림/커서) 와 정확히 동일 시간선 정렬용.
    """
    global _utterance_seq, _streaming_speech_start_at

    ok, reason = _validate_asr_text(sentence)
    if not ok:
        # 차단 — 강사에게 알림. 정상 발화가 환각 가드에 걸린 케이스 catch.
        if manager.lecturer:
            try:
                await manager.lecturer.send_json({
                    "type": "asr_blocked",
                    "reason": reason,
                    "preview": sentence[:80],
                })
            except Exception:
                pass
        print(f"[STREAM] sentence 차단 — {reason}", flush=True)
        return

    _utterance_seq += 1
    seq = _utterance_seq

    # ASR duration 근사 — 발화 시작 → finalize 직전. streaming 모델 특성상 정확한
    # ASR-only 시간 분리는 어렵고, 첫 frame ~ finalize 까지가 사용자가 체감하는 ASR 시간.
    asr_ms = 0
    if _streaming_speech_start_at is not None:
        asr_ms = int((time.perf_counter() - _streaming_speech_start_at) * 1000)

    t_nmt = time.perf_counter()
    async with _nmt_semaphore:
        english = await asyncio.to_thread(
            _nmt_service.translate, sentence, "ko", "en", 512
        )
    nmt_ms = int((time.perf_counter() - t_nmt) * 1000)
    # NMT 실패/빈 결과 fallback — 한국어 원문이라도 자막으로 전달.
    if not english.strip():
        english = ""
        print(f"[NMT 실패] seq={seq} → 한국어 자막 fallback", flush=True)
    else:
        print(f"[NMT  seq={seq}] {english}", flush=True)

    if manager.current_session_id:
        transcripts.append_segment(manager.current_session_id, sentence, english)

    payload = {
        "type": "transcription",
        "seq": seq,
        "sub_seq": 0,
        "total_sub": 1,
        "original": sentence,
        "translated": english,
        "sentAt": sent_at,
        "speechStartAt": speech_start_wall,
        "pageAtSpeechStart": speech_start_page,
        "asrMs": asr_ms,
        "nmtMs": nmt_ms,
    }
    await manager.broadcast_to_students(payload)
    if manager.lecturer:
        try:
            await manager.lecturer.send_json(payload)
        except Exception:
            pass

    print(
        f"[STREAM seq={seq}] ASR={asr_ms}ms NMT={nmt_ms}ms",
        flush=True,
    )


async def process_audio_frame(message: dict):
    """streaming path: 200ms PCM frame 1개를 ASRStreamingService 에 push 후
    finalize 된 문장이 있으면 NMT → broadcast.
    """
    global _streaming_speech_start_at, _streaming_speech_start_wall_at, _streaming_speech_start_page
    if _streaming_asr_service is None or _nmt_service is None:
        return
    if manager.is_paused:
        return

    pcm_b64 = message.get("pcm") or message.get("data") or ""
    if not pcm_b64:
        return
    sent_at = message.get("sentAt")
    sample_rate = int(message.get("sample_rate", 16000))

    # 발화 시작 시각 마킹 — 첫 frame 에서만 (이후 frame 은 그대로 유지).
    # perf_counter: ASR latency 측정용 (단조). wall_at: 학생측 sync 용 (강사 wall 시계).
    # page: 학생측 page-anchor — 이 발화가 강사 어느 페이지에서 시작됐는지 기록.
    if _streaming_speech_start_at is None:
        _streaming_speech_start_at = time.perf_counter()
        _streaming_speech_start_wall_at = sent_at
        _streaming_speech_start_page = manager.current_page

    # 이 sentence broadcast 에 사용할 speech_start_wall + page (이번 utterance 시작점).
    speech_start_wall = _streaming_speech_start_wall_at
    speech_start_page = _streaming_speech_start_page

    try:
        pcm_bytes = base64.b64decode(pcm_b64)
        pcm_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        sentences = await _streaming_asr_service.push_frame(pcm_int16, sample_rate)
        if not sentences:
            return
        for i, s in enumerate(sentences):
            print(f"[ASR-STREAM] {s}", flush=True)
            # 첫 문장만 [STREAM-FIRST] 로깅, 이후는 새 boundary 의 시작점으로 갱신
            if i == 0 and _streaming_speech_start_at is not None:
                lat = time.perf_counter() - _streaming_speech_start_at
                print(f"[STREAM-FIRST] 첫 자막 {lat:.2f}s", flush=True)
            await _broadcast_streaming_sentence(s, sent_at, speech_start_wall, speech_start_page)
        # finalize 된 문장 이후의 audio 는 새 boundary — 다음 sentence 의 시작점으로 갱신.
        # speech_start_wall_at 은 sent_at 으로 (현재 frame = 다음 발화 시작 근사).
        # page 도 현재 페이지로 — 다음 발화가 새 페이지에서 시작될 수 있으므로.
        _streaming_speech_start_at = time.perf_counter()
        _streaming_speech_start_wall_at = sent_at
        _streaming_speech_start_page = manager.current_page
    except Exception as e:
        print(f"[WS] streaming frame 처리 오류: {e}", flush=True)


async def process_audio_frame_flush(message: dict):
    """streaming path: VAD onSpeechEnd 시 호출 — buffer 잔여분 강제 finalize."""
    global _streaming_speech_start_at, _streaming_speech_start_wall_at, _streaming_speech_start_page
    if _streaming_asr_service is None or _nmt_service is None:
        _streaming_speech_start_at = None
        _streaming_speech_start_wall_at = None
        _streaming_speech_start_page = None
        return
    if manager.is_paused:
        # paused 중에도 buffer 는 비워야 다음 발화가 깨끗하게 시작
        await _reset_streaming_state()
        return

    sent_at = message.get("sentAt")
    speech_start_wall = _streaming_speech_start_wall_at
    speech_start_page = _streaming_speech_start_page
    try:
        sentences = await _streaming_asr_service.flush()
        if not sentences:
            return
        for i, s in enumerate(sentences):
            print(f"[ASR-STREAM flush] {s}", flush=True)
            if i == 0 and _streaming_speech_start_at is not None:
                lat = time.perf_counter() - _streaming_speech_start_at
                print(f"[STREAM-FIRST flush] 첫 자막 {lat:.2f}s", flush=True)
            await _broadcast_streaming_sentence(s, sent_at, speech_start_wall, speech_start_page)
    except Exception as e:
        print(f"[WS] streaming flush 처리 오류: {e}", flush=True)
    finally:
        # speech end 도달 → 다음 발화의 시작점은 새 frame 도착 시 mark
        _streaming_speech_start_at = None
        _streaming_speech_start_wall_at = None
        _streaming_speech_start_page = None


