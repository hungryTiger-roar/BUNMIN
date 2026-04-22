"""
WebSocket 라우터
실시간 강의 번역 파이프라인 처리
"""
import asyncio
import base64
import hashlib
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.routers import transcripts

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
        self.students: list[WebSocket] = []
        self.current_slide_id: Optional[str] = None
        self.current_page: int = 1
        self.is_lecture_started: bool = False
        self.is_paused: bool = False
        self.presentation_mode: str = "slide"  # 'slide' or 'screen'
        self.last_screen_hash: Optional[str] = None
        self.current_session_id: Optional[str] = None  # 자막 저장 세션

    def disconnect_lecturer(self):
        self.lecturer = None
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
        print(f"[WS] 수강자 연결 해제 (남은 인원: {len(self.students)}명)")

    async def broadcast_to_students(self, message: dict):
        """모든 수강자에게 메시지 전송"""
        disconnected = []
        for student in self.students:
            try:
                await student.send_json(message)
            except Exception:
                disconnected.append(student)

        # 끊어진 연결 제거
        for ws in disconnected:
            self.disconnect_student(ws)


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

        if role == "lecturer":
            manager.lecturer = websocket
            print("[WS] 강의자 연결됨")
            await websocket.send_json({"type": "registered", "role": "lecturer"})
            await run_with_heartbeat(handle_lecturer(websocket), websocket)

        elif role == "student":
            manager.students.append(websocket)
            print(f"[WS] 수강자 연결됨 (총 {len(manager.students)}명)")
            await websocket.send_json({"type": "registered", "role": "student"})
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
        elif role == "student":
            manager.disconnect_student(websocket)


async def handle_lecturer(websocket: WebSocket):
    """강의자 메시지 처리"""
    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            print(f"[WS] 강의자 메시지: {msg_type}")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "pong":
                pass  # heartbeat 응답 확인

            elif msg_type == "audio":
                await process_audio(message)

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

    except WebSocketDisconnect:
        manager.disconnect_lecturer()


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

    except WebSocketDisconnect:
        manager.disconnect_student(websocket)


async def process_audio(message: dict):
    """
    오디오 처리 파이프라인
    오디오 → ASR → NMT → TTS → 수강자 전송
    """
    if not all([_asr_service, _nmt_service, _tts_service]):
        print("[WS] 서비스가 초기화되지 않았습니다")
        return

    try:
        # Base64 디코딩 (프론트엔드는 'audio' 키 사용)
        audio_b64 = message.get("audio", "") or message.get("data", "")
        if not audio_b64:
            print("[WS] 오디오 데이터 없음")
            return
        audio_bytes = base64.b64decode(audio_b64)

        # ASR: 음성 → 한국어 텍스트
        korean_text = await asyncio.to_thread(
            _asr_service.transcribe, audio_bytes
        )

        if not korean_text.strip():
            return

        print(f"[ASR] {korean_text}")

        # NMT: 한국어 → 영어
        english_text = await asyncio.to_thread(
            _nmt_service.translate, korean_text
        )
        print(f"[NMT] {english_text}")

        if not english_text.strip():
            return

        # TTS: 영어 텍스트 → 음성
        audio_output = await asyncio.to_thread(
            _tts_service.synthesize, english_text
        )
        audio_output_b64 = base64.b64encode(audio_output).decode()

        # 자막 파일에 append (세션 진행 중일 때만)
        if manager.current_session_id:
            transcripts.append_segment(
                manager.current_session_id, korean_text, english_text
            )

        # 수강자에게 전송 (프론트엔드는 'transcription' 타입 기대)
        await manager.broadcast_to_students({
            "type": "transcription",
            "original": korean_text,
            "translated": english_text,
            "audio": audio_output_b64,
        })

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
