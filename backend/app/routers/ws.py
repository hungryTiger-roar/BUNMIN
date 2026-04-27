"""
WebSocket 라우터
실시간 강의 번역 파이프라인 처리
"""
import asyncio
import base64
import hashlib
import time
import uuid
import io
import re
import wave
from typing import Optional
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.routers import transcripts


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
    """ASR 결과 텍스트 품질 검증 — 노이즈·환각 탐지"""
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

    return True, ""

router = APIRouter(prefix="/ws", tags=["WebSocket"])

# 서비스 인스턴스 (main.py에서 주입)
_asr_service = None
_nmt_service = None
_tts_service = None
_ocr_service = None


def set_asr_service(service):
    global _asr_service
    _asr_service = service


def set_nmt_service(service):
    global _nmt_service
    _nmt_service = service


def set_tts_service(service):
    global _tts_service
    _tts_service = service


def set_ocr_service(service):
    global _ocr_service
    _ocr_service = service


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
        self.last_screen_hash: Optional[str] = None
        self.current_session_id: Optional[str] = None  # 자막 저장 세션
        self.lecture_title: str = ""  # 강사가 설정한 강의 제목
        self._lock = asyncio.Lock()  # students 리스트 동시 접근 방지
        self._tasks: set[asyncio.Task] = set()  # 실행 중인 태스크 추적

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
            self.current_session_id = None
            self.is_lecture_started = False
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

        disconnected = []
        for student in students_snapshot:
            try:
                await student.send_json(message)
            except Exception:
                disconnected.append(student)

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

PING_INTERVAL = 20  # 서버 → 클라이언트 ping 주기 (초)
PING_TIMEOUT  = 10  # pong 미응답 허용 시간 (초)


async def heartbeat(websocket: WebSocket):
    """서버 → 클라이언트 주기적 ping 전송"""
    while websocket.client_state == WebSocketState.CONNECTED:
        await asyncio.sleep(PING_INTERVAL)
        try:
            await websocket.send_json({"type": "ping"})
        except Exception:
            break


async def run_with_heartbeat(handler, websocket: WebSocket):
    """핸들러 종료 시 heartbeat도 함께 취소"""
    handler_task   = asyncio.ensure_future(handler)
    heartbeat_task = asyncio.ensure_future(heartbeat(websocket))

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
            await websocket.send_json({"type": "registered", "role": "lecturer"})
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
            await run_with_heartbeat(handle_student(websocket), websocket)

        else:
            await websocket.close(code=4001, reason="올바른 역할이 아닙니다")

    except WebSocketDisconnect:
        if role == "lecturer":
            manager.disconnect_lecturer()
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
                print(f"[WS] 오디오 수신 ({audio_size}KB) → 처리 태스크 시작", flush=True)
                task = asyncio.create_task(process_audio(message))
                manager.track_task(task)

            elif msg_type == "screen":
                print(f"[WS] 화면 데이터 수신, 수강자 수: {len(manager.students)}")
                await process_screen(message)

            elif msg_type == "slide_select":
                manager.current_slide_id = message.get("slide_id")
                manager.current_page = 1
                print(f"[WS] 슬라이드 선택: {manager.current_slide_id}")
                await manager.broadcast_to_students({
                    "type": "slide_select",
                    "slide_id": manager.current_slide_id,
                })

            elif msg_type == "page_change":
                manager.current_page = message.get("page", 1)
                print(f"[WS] 페이지 변경: {manager.current_page}")
                await manager.broadcast_to_students({
                    "type": "page_change",
                    "slide_id": manager.current_slide_id,
                    "page": manager.current_page,
                })

            elif msg_type == "lecture_start":
                manager.is_lecture_started = True
                manager.current_slide_id = message.get("slide_id")
                manager.presentation_mode = message.get("mode", "slide")
                # 자막 세션 시작 — session_id 발급
                manager.current_session_id = transcripts.start_session(
                    manager.current_slide_id
                )
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
                })
                # 발표 모드도 함께 전송
                await manager.broadcast_to_students({
                    "type": "presentation_mode",
                    "mode": manager.presentation_mode,
                })

            elif msg_type == "lecture_end":
                manager.is_lecture_started = False
                manager.is_paused = False
                # 자막 세션 종료 — jsonl → 최종 json 병합
                ended_id = transcripts.end_session(manager.current_session_id)
                print(f"[WS] 강의 종료 (세션: {ended_id})")
                await manager.broadcast_to_students({
                    "type": "lecture_end",
                    "session_id": ended_id,
                })
                manager.current_session_id = None

            elif msg_type == "lecture_pause":
                manager.is_paused = True
                print("[WS] 강의 일시정지")
                await manager.broadcast_to_students({
                    "type": "lecture_pause",
                })

            elif msg_type == "lecture_resume":
                manager.is_paused = False
                print("[WS] 강의 재개")
                await manager.broadcast_to_students({
                    "type": "lecture_resume",
                })

            elif msg_type == "presentation_mode":
                manager.presentation_mode = message.get("mode", "slide")
                print(f"[WS] 발표 모드 변경: {manager.presentation_mode}")
                await manager.broadcast_to_students({
                    "type": "presentation_mode",
                    "mode": manager.presentation_mode,
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

            elif msg_type == "participants_request":
                await websocket.send_json(manager.participants_payload())

    except WebSocketDisconnect:
        manager.disconnect_lecturer()
        await manager.broadcast_participants()


async def handle_student(websocket: WebSocket):
    """수강자 메시지 처리 (주로 수신만 함)"""
    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "pong":
                pass  # heartbeat 응답 확인

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

    except WebSocketDisconnect:
        manager.disconnect_student(websocket)
        await manager.broadcast_student_count()
        await manager.broadcast_participants()


async def process_audio(message: dict):
    """
    오디오 처리 파이프라인
    오디오 → ASR → NMT → TTS → 수강자 전송
    """
    if not all([_asr_service, _nmt_service, _tts_service]):
        print("[WS] 서비스가 초기화되지 않았습니다")
        return

    import time
    try:
        t_start = time.perf_counter()

        # 프론트엔드 전송 타임스탬프 (ms, echo back용)
        sent_at = message.get("sentAt")

        # Base64 디코딩 (프론트엔드는 'audio' 키 사용)
        audio_b64 = message.get("audio", "") or message.get("data", "")
        if not audio_b64:
            print("[WS] 오디오 데이터 없음")
            return
        audio_bytes = base64.b64decode(audio_b64)

        # Layer 2-A: ASR 실행 전 오디오 품질 검증
        ok, reason = _validate_audio(audio_bytes)
        if not ok:
            print(f"[필터-오디오] {reason} → 스킵")
            return

        try:
            with wave.open(io.BytesIO(audio_bytes)) as _w:
                _dur = _w.getnframes() / _w.getframerate()
            print(f"[INPUT] 오디오 수신: {len(audio_bytes) / 1024:.1f}KB, {_dur:.2f}s → ASR 시작", flush=True)
        except Exception:
            print(f"[INPUT] 오디오 수신: {len(audio_bytes) / 1024:.1f}KB → ASR 시작", flush=True)

        # ASR: 음성 → 한국어 텍스트
        t_asr = time.perf_counter()
        korean_text = await asyncio.to_thread(
            _asr_service.transcribe, audio_bytes
        )
        t_asr_done = time.perf_counter()

        # Layer 2-B: ASR 결과 텍스트 품질 검증
        ok, reason = _validate_asr_text(korean_text)
        if not ok:
            print(f"[필터-텍스트] {reason} → 스킵")
            return

        print(f"[ASR  input ] {korean_text}", flush=True)

        # NMT: 한국어 → 영어
        t_nmt = time.perf_counter()
        english_text = await asyncio.to_thread(
            _nmt_service.translate, korean_text, "ko", "en", 512, ""
        )
        t_nmt_done = time.perf_counter()
        print(f"[NMT  output] {english_text}", flush=True)

        if not english_text.strip():
            return

        # TTS: 영어 텍스트 → 음성 (실패해도 자막은 전송)
        t_tts = time.perf_counter()
        audio_output_b64 = None
        try:
            audio_output = await asyncio.to_thread(
                _tts_service.synthesize, english_text
            )
            audio_output_b64 = base64.b64encode(audio_output).decode()
        except Exception as tts_err:
            print(f"[TTS] 합성 실패, 자막만 전송: {tts_err}")
        t_tts_done = time.perf_counter()

        # 자막 파일에 append (세션 진행 중일 때만)
        if manager.current_session_id:
            transcripts.append_segment(
                manager.current_session_id, korean_text, english_text
            )

        # 수강자에게 전송 (audio 없으면 자막만)
        await manager.broadcast_to_students({
            "type": "transcription",
            "original": korean_text,
            "translated": english_text,
            "audio": audio_output_b64,
            "sentAt": sent_at,
        })
        print(f"[OUTPUT] 수강자 전송 완료: '{english_text[:60]}'", flush=True)

        # 강의자에게도 자막 전송 (오디오 없이 — 강의자는 TTS 재생 불필요)
        if manager.lecturer:
            try:
                await manager.lecturer.send_json({
                    "type": "transcription",
                    "original": korean_text,
                    "translated": english_text,
                    "audio": None,
                    "sentAt": sent_at,
                })
            except Exception:
                pass

        t_end = time.perf_counter()
        print(
            f"[LATENCY] ASR={t_asr_done - t_asr:.2f}s | "
            f"NMT={t_nmt_done - t_nmt:.2f}s | "
            f"TTS={t_tts_done - t_tts:.2f}s | "
            f"전체={t_end - t_start:.2f}s",
            flush=True,
        )

    except Exception as e:
        print(f"[WS] 오디오 처리 오류: {e}")


async def process_screen(message: dict):
    """
    화면 캡처 처리
    - 화면을 수강자에게 전달
    - 슬라이드 모드: 사전 처리된 overlay 전송
    - 순수 화면 공유 모드: 실시간 OCR + 번역 후 overlay 전송
    - 화면이 바뀌지 않으면 OCR 재실행 생략
    """
    try:
        screen_b64 = message.get("data", "")
        if not screen_b64:
            return

        # 화면 데이터를 수강자에게 전달
        await manager.broadcast_to_students({
            "type": "screen",
            "image": screen_b64,
            "slide_id": manager.current_slide_id,
            "page": manager.current_page,
        })

        # 슬라이드 모드: 사전 처리된 overlay 사용
        if manager.current_slide_id:
            from app.routers.slides import get_page_overlay
            overlay_items = get_page_overlay(
                manager.current_slide_id,
                manager.current_page
            )
            if overlay_items:
                await manager.broadcast_to_students({
                    "type": "overlay",
                    "items": overlay_items,
                })
            return

        # 순수 화면 공유 모드: 실시간 OCR
        if not _ocr_service or not _nmt_service:
            return

        image_bytes = base64.b64decode(screen_b64)
        screen_hash = hashlib.md5(image_bytes).hexdigest()[:16]

        # 화면이 바뀌지 않았으면 OCR 생략
        if screen_hash == manager.last_screen_hash:
            return
        manager.last_screen_hash = screen_hash

        # OCR + 번역 (블로킹 작업이므로 thread에서 실행)
        ocr_results = await asyncio.to_thread(
            _ocr_service.extract_with_positions, image_bytes
        )

        if not ocr_results:
            return

        overlay_items = []
        texts = [item["text"] for item in ocr_results if item["text"].strip()]

        if texts:
            # NMT 배치 번역
            translated_list = await asyncio.to_thread(
                _nmt_service.translate_batch, texts
            )
            text_idx = 0
            for item in ocr_results:
                if not item["text"].strip():
                    continue
                raw_bbox = item["bbox"]
                if raw_bbox is None:
                    bbox = None
                elif len(raw_bbox) == 4:
                    bbox = [raw_bbox[0][0], raw_bbox[0][1], raw_bbox[2][0], raw_bbox[2][1]]
                else:
                    bbox = raw_bbox
                overlay_items.append({
                    "original": item["text"],
                    "translated": translated_list[text_idx],
                    "bbox": bbox,
                    "confidence": item["confidence"],
                })
                text_idx += 1

        if overlay_items:
            await manager.broadcast_to_students({
                "type": "overlay",
                "items": overlay_items,
            })

    except Exception as e:
        print(f"[WS] 화면 처리 오류: {e}")
