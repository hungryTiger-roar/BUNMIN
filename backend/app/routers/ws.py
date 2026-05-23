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

# 진단 로그 — 강사 send (lecturerTimestamp) → 서버 도착 → broadcast 전 과정 visibility.
# 고빈도 (cursor / draw_point) 는 매 10번째만 sampling.
_sync_diag_counter: dict[str, int] = {}


def _sync_log(msg_type: str, message: dict, action: str = "recv") -> None:
    """진단 로그 출력. 고빈도 메시지는 sampling.
    action: 'recv' (강사로부터 도착) 또는 'broadcast' (학생에게 송출 직전)."""
    lec_ts = message.get("lecturerTimestamp")
    if msg_type in ("cursor", "draw_point"):
        _sync_diag_counter[msg_type] = _sync_diag_counter.get(msg_type, 0) + 1
        if _sync_diag_counter[msg_type] % 10 != 0:
            return
        n = _sync_diag_counter[msg_type]
        print(f"[Diag/Server] {action} {msg_type} #{n} lecTs={lec_ts}", flush=True)
    else:
        # 추가 필드 일부 미리보기.
        extras = ""
        if msg_type == "page_change":
            extras = f" page={message.get('page')}"
        elif msg_type in ("draw_begin", "draw_end"):
            extras = f" id={message.get('id')}"
        print(f"[Diag/Server] {action} {msg_type} lecTs={lec_ts}{extras}", flush=True)


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

    # 환각 정형구 sentence-level 재검사 — segment 레벨 (asr_service _transcribe_buffer)
    # 에서 못 잡은 multi-segment 결합 케이스 catch.
    # 예: Whisper 가 "다음 영상에서 만나요." + "만나요" 두 segment 로 쪼개면 두 번째
    # "만나요" 단독은 segment 패턴에 안 걸림. 단어가 buffer 에 누적되어 sentence 로
    # 합쳐진 후에야 전체 정형구가 보임.
    if _HALLUCINATION_PATTERNS.search(text):
        return False, f"환각 정형구 매칭 (sentence-level): {text[:50]!r}"

    # 단독 "감사합니다" 차단 — Whisper 가 침묵/노이즈에서 자주 토하는 outro 정형구.
    # silence-cascade (no_speech_prob 임계) 에 걸리지 않는 케이스에서도 새는 걸 차단.
    # 강사가 강의 마지막 1회 진짜로 말하는 경우도 막히지만 (false positive),
    # 수강자에게 "Thank you" / "감사합니다" 만 단독 출력되는 것보다 그게 낫다는 판단.
    if re.match(r"^\s*감사합니다[\s\.\!\?…]*$", text):
        return False, f"단독 인사 환각 (Korean): '{text}'"

    return True, ""


try:
    import kss as _kss  # 한국어 문장 분리 (마침표 + 종결어미 기반)
    _kss_available = True
except Exception as _e:
    _kss_available = False
    print(f"[Split] kss 미설치 — 정규식 fallback 사용: {_e}", flush=True)


def _assign_word_times_to_sentences(
    words: list[dict],
    sentences: list[str],
    chunk_speech_start_wall: Optional[int],
    audio_duration_ms: int,
) -> list[tuple[Optional[int], Optional[int]]]:
    """Whisper 단어별 시간 정보를 KSS 분리 문장에 매핑 — sub-sentence 별 정확한
    speechStartAt / sentAt 산출. 각 sentence 의 (sub_speech_start_wall, sub_sent_at) 반환.

    매칭 알고리즘 — 공백 제외 char 단위 누적:
      1) 모든 word 의 char 들을 평탄화 (각 char 의 출처 word index 기록)
      2) 각 sentence 의 char 길이만큼 word_chars 소비 → 첫 word 와 마지막 word 의 시간
      3) 첫 word.start, 마지막 word.end 를 chunk 시작 시각에 더해 절대 wall time

    매핑 실패 시 (words 없음 / chunk_speech_start_wall 없음) chunk 전체 시간으로 fallback.
    """
    fallback_start = chunk_speech_start_wall
    fallback_end = (
        (chunk_speech_start_wall + audio_duration_ms)
        if chunk_speech_start_wall is not None else None
    )
    fallback = (fallback_start, fallback_end)

    if not sentences:
        return []
    if not words or chunk_speech_start_wall is None:
        return [fallback] * len(sentences)

    # 평탄화 — 각 char 가 어느 word 인지 추적.
    word_chars: list[tuple[str, int]] = []
    for i, w in enumerate(words):
        clean = (w.get("text") or "").replace(" ", "").replace("\n", "")
        for c in clean:
            word_chars.append((c, i))
    if not word_chars:
        return [fallback] * len(sentences)

    result: list[tuple[Optional[int], Optional[int]]] = []
    char_idx = 0
    for sent in sentences:
        sent_chars = sent.replace(" ", "").replace("\n", "")
        sent_len = len(sent_chars)
        if sent_len == 0 or char_idx >= len(word_chars):
            result.append(fallback)
            continue
        start_word_idx = word_chars[char_idx][1]
        end_char_idx = min(char_idx + sent_len - 1, len(word_chars) - 1)
        end_word_idx = word_chars[end_char_idx][1]
        sub_start_sec = words[start_word_idx]["start"]
        sub_end_sec = words[end_word_idx]["end"]
        result.append((
            chunk_speech_start_wall + int(sub_start_sec * 1000),
            chunk_speech_start_wall + int(sub_end_sec * 1000),
        ))
        char_idx = end_char_idx + 1
    return result


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


# ── 스트리밍 ASR ────────────────────────────────────────────────────────────────
def _pcm16_to_wav(pcm16_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """raw int16 PCM → WAV bytes (ASR 입력용)."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16_bytes)
    return buf.getvalue()


_ASR_CHUNK_FRAMES = 5  # 200ms × 5 = 1초마다 증분 ASR 실행


class StreamingBuffer:
    """한 발화의 200ms 프레임을 누적 — 1초 주기 증분 ASR + 발화 종료 시 최종 ASR."""

    def __init__(self):
        self.pcm16_frames: list[bytes] = []
        self.frame_count: int = 0
        self.last_asr_frame: int = 0
        self.committed_sentences: list[str] = []   # NMT → broadcast 완료 문장
        self.prev_sentences: list[str] = []        # 직전 ASR 결과 (안정성 비교용)
        self.speech_start_wall: Optional[int] = None
        self.sent_at: Optional[int] = None
        self.slide_id: Optional[str] = None
        self.page: int = 1


def set_asr_service(service):
    global _asr_service
    _asr_service = service


def set_nmt_service(service):
    global _nmt_service
    _nmt_service = service


def set_ocr_service(service):
    global _ocr_service
    _ocr_service = service


class ConnectionManager:
    """WebSocket 연결 관리자"""

    def __init__(self):
        self.lecturer: Optional[WebSocket] = None
        self.lecturer_name: str = "professor"
        self.students: list[WebSocket] = []
        self.student_info: dict[WebSocket, dict] = {}  # ws -> {id, name, audio_lang}
        self.current_slide_id: Optional[str] = None
        self.current_page: int = 1
        self.is_lecture_started: bool = False
        self.is_paused: bool = False
        self.presentation_mode: str = "slide"  # 'slide' or 'screen'
        self.current_session_id: Optional[str] = None  # 자막 저장 세션
        self.lecture_title: str = ""  # 강사가 설정한 강의 제목
        # 강의 시작 시 config/glossary.csv 에서 로드된 한국어 용어 키 — ASR hotwords 로 전달.
        # lecture_end 시 비움. NMT 측 dict 는 _nmt_service.set_glossary() 가 별도 보관.
        self.lecture_glossary_keys: list[str] = []
        self._lock = asyncio.Lock()  # students 리스트 동시 접근 방지
        self._tasks: set[asyncio.Task] = set()  # 실행 중인 태스크 추적

        # 강사 WS 끊김 시 grace period 후 자동 lecture_end 처리하는 task.
        # transient (pong miss) vs permanent (브라우저/exe 종료) 구분 — 30초 안에
        # 재연결 안 되면 permanent 로 간주.
        self._lecturer_grace_task: Optional[asyncio.Task] = None

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
        """강사 WS 연결 해제 — 30초 grace 후 자동 lecture_end 처리.

        구분:
          - transient (pong miss / 네트워크 깜박 / 일시정지 silence + 브라우저 throttling):
            보통 3~10초 안에 재연결 → grace 안에 들어와서 cleanup 취소 → 강의 계속
          - permanent (브라우저 닫음 / exe 종료 / 영구 네트워크 단절):
            grace timeout → 자동 lecture_end → 자막 finalize + 학생 modal 표시

        WS ref 만 즉시 clear, 나머지 상태는 grace 후 cleanup task 가 정리.
        """
        self.lecturer = None
        # 이전 grace task 가 있으면 cancel (중복 disconnect 케이스)
        if self._lecturer_grace_task and not self._lecturer_grace_task.done():
            self._lecturer_grace_task.cancel()
        self._lecturer_grace_task = asyncio.create_task(self._lecturer_grace_cleanup())
        print("[WS] 강사 WS 연결 해제 — 30초 grace 시작 (재연결 대기)")

    async def _lecturer_grace_cleanup(self):
        """강사 재연결 grace period — timeout 후 강의 영구 종료 처리.
        grace 안에 새 강사 WS 가 들어와 manager.lecturer 가 set 되면 이 task 는 cancel 됨.
        """
        GRACE_SEC = 30
        try:
            await asyncio.sleep(GRACE_SEC)
        except asyncio.CancelledError:
            print("[WS] 강사 재연결 — grace cleanup 취소")
            return

        if self.lecturer is not None:
            # 어떤 이유로 재연결됐는데 task cancel 안 된 케이스 (race) — 정리 X
            return

        # permanent disconnect 확정 — lecture_end 와 동등 처리.
        print(f"[WS] 강사 grace timeout ({GRACE_SEC}초) — 자동 lecture_end 처리")
        ended_id = None
        if self.is_lecture_started and self.current_session_id:
            ended_id = transcripts.end_session(self.current_session_id)
            print(f"[WS] 자막 세션 자동 저장: {ended_id}")
            if _nmt_service:
                try:
                    _nmt_service.set_glossary(None)
                except Exception:
                    pass
        # 학생들에게 lecture_end broadcast (session_id 포함 → 다운로드 modal 표시)
        if ended_id:
            try:
                await self.broadcast_to_students({
                    "type": "lecture_end",
                    "session_id": ended_id,
                })
            except Exception as e:
                print(f"[WS] grace cleanup broadcast 오류: {e}")
        # 모든 강의 상태 reset — 다음 강사가 깨끗하게 시작
        self.current_session_id = None
        self.is_lecture_started = False
        self.is_paused = False
        self.lecturer_name = "professor"
        self.lecture_title = ""
        self.lecture_glossary_keys = []
        self.current_slide_id = None
        self.current_page = 1
        self.presentation_mode = "slide"

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
                    "audio_lang": info.get("audio_lang", "en"),
                }
                for ws, info in self.student_info.items()
                if ws in self.students
            ],
        }

    async def broadcast_to_students(self, message: dict):
        """모든 수강자에게 메시지 전송 (Lock으로 동시 접근 보호)"""
        # [Diag/Server] broadcast 직전 로그.
        mt = message.get("type", "?")
        if mt and mt not in ("student_count", "participants", "pong", "ping"):
            _sync_log(mt, message, action="broadcast")
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

    async def broadcast_toast(self, message: str):
        """글로벌 토스트 메시지를 강의자에게 push (frontend GlobalToast 표시).
        VLM 다운/적재 시간 안내 같은 사용자 인지용. 실패해도 swallow."""
        if self.lecturer is None:
            return
        try:
            await self.lecturer.send_json({"type": "toast", "message": message})
        except Exception as e:
            print(f"[WS] toast broadcast 실패: {e}")

    async def broadcast_slide_status(self, slide_id: str, status: str, error: str | None = None):
        """슬라이드 처리 상태 변경을 강의자에게 즉시 push (polling 보조).
        status: 'completed' / 'failed'. completed 시 frontend 가 slideStatus='ready' 로 갱신 + 라이브러리 refresh.
        실패해도 swallow — broadcast 실패가 처리 흐름을 막지 않게."""
        if self.lecturer is None:
            return
        payload = {"type": "slide_status_update", "slide_id": slide_id, "status": status}
        if error is not None:
            payload["error"] = error
        try:
            await self.lecturer.send_json(payload)
        except Exception as e:
            print(f"[WS] slide_status_update broadcast 실패: {e}")

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
_streaming_buffers: dict[int, StreamingBuffer] = {}  # id(websocket) → StreamingBuffer

# 전역 broadcast event seq — cursor / draw / transcription / page_change 등
# 학생측이 순서 검증 / 중복·누락 감지에 사용. WebSocket 자체 순서 보장 위에 추가
# safety net. 강사 wall clock (lecturerTimestamp) 와 별개로 서버 발사 순번.
_event_seq: int = 0


def _next_event_seq() -> int:
    """전역 broadcast event seq 다음 번호 발급. monotonic, 1부터 시작."""
    global _event_seq
    _event_seq += 1
    return _event_seq


def _ts(message: dict) -> dict:
    """incoming 메시지의 lecturerTimestamp 를 outgoing payload spread 용으로 추출.
    sync 작업 (학생측 useTimelineSync) 가 visual event 와 TTS 진도 매칭하는 데 사용.
    None 이면 빈 dict 반환 — payload 에 노이즈 추가 안 함."""
    ts = message.get("lecturerTimestamp")
    return {"lecturerTimestamp": ts} if ts is not None else {}


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
            # 이미 강의자가 연결되어 있으면 중복 연결 거부.
            # 단, 죽은 websocket 이 reference 만 남아 있는 경우 즉시 교체 (sticky lock 방지).
            #   배경: heartbeat 가 pong miss 로 websocket.close() 한 직후~handler 의 finally
            #         block 이 disconnect_lecturer() 호출하기 전 사이에 새 강사 연결 시도가 들어오면
            #         manager.lecturer 가 dead websocket 을 가리킨 채라 매번 4409 로 거부됨.
            #         (이전 운영 로그상 16~25회 거부 후에야 풀리는 sticky lock 발생.)
            if manager.lecturer is not None:
                existing_ws = manager.lecturer
                ws_alive = (
                    existing_ws.client_state == WebSocketState.CONNECTED
                    and existing_ws.application_state == WebSocketState.CONNECTED
                )
                if ws_alive:
                    print("[WS] 강의자 역할 거부 (중복 연결)")
                    await websocket.close(code=4409, reason="lecturer already connected")
                    return
                # dead websocket — 즉시 교체. 강의 상태는 보존 (transient disconnect 와 동일 효과).
                print("[WS] 기존 강사 websocket dead → 새 연결로 즉시 교체 (sticky lock 방지)")
                manager.lecturer = None
                if manager._lecturer_grace_task and not manager._lecturer_grace_task.done():
                    manager._lecturer_grace_task.cancel()
                    manager._lecturer_grace_task = None
            # grace cleanup 진행 중이면 cancel — 재연결로 강의 계속.
            if manager._lecturer_grace_task and not manager._lecturer_grace_task.done():
                manager._lecturer_grace_task.cancel()
                manager._lecturer_grace_task = None
                print("[WS] 강사 재연결 — grace cleanup 취소, 강의 상태 보존")
            manager.lecturer = websocket
            manager.lecturer_name = name or "professor"
            print(f"[WS] 강의자 연결됨 (이름: {manager.lecturer_name})")
            await websocket.send_json({
                "type": "registered",
                "role": "lecturer",
            })
            if manager.lecture_title:
                await websocket.send_json({
                    "type": "lecture_title",
                    "title": manager.lecture_title,
                })
            await manager.broadcast_participants()
            # pong_event 추가 — 일시정지 중 silent disconnect 감지용. 학생과 동일.
            # try/finally — heartbeat send 실패로 WebSocketDisconnect 안 던져진 케이스에도
            # 자리 정리 보장. 안 그러면 manager.lecturer 가 dead websocket 가리킨 채 남아
            # 새 연결을 "중복" 으로 거부하는 sticky bug 발생.
            lecturer_pong_event = asyncio.Event()
            try:
                await run_with_heartbeat(
                    handle_lecturer(websocket, lecturer_pong_event),
                    websocket,
                    lecturer_pong_event,
                )
            finally:
                # 1) 새 강사가 이미 자리 차지했으면 (identity 다름) → 그 자리 건드리지 않음.
                # 2) 내 자리면 → disconnect_lecturer().
                # 3) broadcast_all 경로로 disconnect_lecturer 가 먼저 호출돼 None 인 경우
                #    → disconnect 는 skip 하지만 participants 는 수행.
                other_lecturer_active = (
                    manager.lecturer is not None and manager.lecturer is not websocket
                )
                if not other_lecturer_active:
                    if manager.lecturer is websocket:
                        manager.disconnect_lecturer()
                    await manager.broadcast_participants()

        elif role == "student":
            student_id = str(uuid.uuid4())
            student_name = name or f"Guest{len(manager.students) + 1}"
            manager.students.append(websocket)
            manager.student_info[websocket] = {"id": student_id, "name": student_name, "audio_lang": "en"}
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
                    "page": manager.current_page,
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
            # try/finally — handler 가 어떻게 끝나도 (정상 close, silent disconnect,
            # 예외) 자리 정리 보장. 강사와 동일 패턴.
            try:
                await run_with_heartbeat(handle_student(websocket, pong_event), websocket, pong_event)
            finally:
                manager.disconnect_student(websocket)
                await manager.broadcast_student_count()
                await manager.broadcast_participants()

        else:
            await websocket.close(code=4001, reason="올바른 역할이 아닙니다")

    except WebSocketDisconnect:
        # finally 블록이 이미 cleanup 수행 — 여기선 추가 동작 불필요.
        # WebSocketDisconnect 외 예외가 올라오면 fastapi 가 처리하도록 두기 위해 except 유지.
        pass


async def handle_lecturer(websocket: WebSocket, pong_event: asyncio.Event | None = None):
    """강의자 메시지 처리"""
    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            # [Diag/Server] 강사 메시지 도착 로그. ping/pong/heartbeat 류 노이즈는 제외.
            if msg_type and msg_type not in ("ping", "pong"):
                _sync_log(msg_type, message, action="recv")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "pong":
                # heartbeat 응답 — 일시정지 중 silent disconnect 감지용 (timeout 시 강제 close)
                if pong_event:
                    pong_event.set()

            elif msg_type == "audio":
                audio_size = len(message.get("audio", "")) * 3 // 4 // 1024
                task = asyncio.create_task(process_audio(message))
                manager.track_task(task)

            elif msg_type == "audio_chunk":
                if not manager.is_paused:
                    task = asyncio.create_task(process_audio_chunk(message, id(websocket)))
                    manager.track_task(task)

            elif msg_type == "audio_chunk_end":
                task = asyncio.create_task(flush_audio_stream(message, id(websocket)))
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
                # 옵션 C 가드: 슬라이드 처리 중에는 강의 시작 거부 (양방향 가드).
                # 슬라이드 처리는 VLM 적재 → 강의 시작 시 ASR/NMT 적재 시도 → GPU 충돌.
                from app.routers.slides import is_any_slide_processing
                if is_any_slide_processing():
                    await websocket.send_json({
                        "type": "lecture_start_rejected",
                        "reason": "slide_processing",
                        "message": "강의 자료 번역이 진행 중입니다. 완료 후 강의를 시작해주세요.",
                    })
                    print("[WS] 강의 시작 거부 — 슬라이드 처리 중")
                    continue
                # 신규 가드: ASR/NMT 미적재 시 거부 — backend 부팅 후 ~10초 race window 차단.
                # frontend modelsReady=false 와 polling 가드가 1차이지만, .exe 시작 직후 첫 polling
                # 도착 전 강의 시작 시 ASR/NMT None → process_audio silent return → 첫 발화 손실.
                # 백엔드에서 명시 거부해 학생들에게 첫 인사 누락되는 사고 차단.
                if _asr_service is None or _nmt_service is None:
                    await websocket.send_json({
                        "type": "lecture_start_rejected",
                        "reason": "models_not_ready",
                        "message": "AI 모델 준비 중입니다. 5~10초 후 다시 시도해주세요.",
                    })
                    print("[WS] 강의 시작 거부 — ASR/NMT 미적재")
                    continue
                # 이전 강의 stale 세션 finalize — 강사 WS 가 비정상 종료된 후 lecture_end
                # 못 보낸 채로 재연결 / 새 강의 시작 시 jsonl 만 남고 final json 안 만들어짐.
                # 여기서 명시적으로 정리.
                if manager.current_session_id:
                    stale_id = transcripts.end_session(manager.current_session_id)
                    print(f"[WS] 이전 미종료 세션 정리: {stale_id}")
                manager.is_lecture_started = True
                manager.is_paused = False  # 재시작 시 pause 상태 reset
                manager.current_slide_id = message.get("slide_id")
                manager.current_page = int(message.get("page") or 1)
                manager.presentation_mode = message.get("mode", "slide")
                # 새 강의 — 이전 강의의 누적 필기 폐기 (replay 시 stale 방지)
                manager.page_draw_events.clear()
                # 자막 세션 시작 — session_id 발급
                manager.current_session_id = transcripts.start_session(
                    manager.current_slide_id
                )
                print(f"[WS] 강의 시작: {manager.current_slide_id}, 모드: {manager.presentation_mode}, 세션: {manager.current_session_id}")
                # 도메인 용어집 (config/glossary.csv) 주입 — NMT 는 한글→영어 inline 치환,
                # ASR 은 한국어 키를 hotwords 로 (process_audio 가 manager 캐시에서 읽음).
                # 로드 실패해도 강의는 그대로 진행 — 용어집은 품질 보강용이라 fail-safe.
                # 항상 set_glossary 호출 (빈 dict 면 None) — 이전 강의가 lecture_end/grace 없이
                # 끊긴 stale 케이스에서도 NMT 잔여 glossary 가 새 강의로 새지 않게 보장.
                try:
                    from app.services.slide_translation.term_corrections import get_mandatory_terms
                    glossary_terms = get_mandatory_terms() or {}
                    _nmt_service.set_glossary(glossary_terms if glossary_terms else None)
                    manager.lecture_glossary_keys = list(glossary_terms.keys())
                    if glossary_terms:
                        print(f"[WS] glossary 주입: {len(glossary_terms)}개 (NMT inline 치환 + ASR hotwords)")
                    else:
                        print("[WS] glossary 비어 있음 — 기본 동작")
                except Exception as e:
                    manager.lecture_glossary_keys = []
                    try:
                        _nmt_service.set_glossary(None)  # 잔여 상태 방어
                    except Exception:
                        pass
                    print(f"[WS] glossary 로드 실패 (무시됨): {e}")
                # 강의자에게 session_id 회신 (다운로드 시 필요)
                await websocket.send_json({
                    "type": "session_started",
                    "session_id": manager.current_session_id,
                })
                await manager.broadcast_to_students({
                    "type": "lecture_start",
                    "slide_id": manager.current_slide_id,
                    "page": manager.current_page,
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
                # 자막 세션 finalize — jsonl → final json 병합.
                ended_id = transcripts.end_session(manager.current_session_id)
                print(f"[WS] 강의 종료 (세션: {ended_id})")
                # 학생들에게 lecture_end broadcast — session_id 포함 → 다운로드 modal.
                await manager.broadcast_to_students({
                    "type": "lecture_end",
                    "session_id": ended_id,
                    **_ts(message),
                })
                # 상태 reset — 이후 들어오는 stale transcript broadcast 차단.
                manager.is_lecture_started = False
                manager.is_paused = False
                manager.current_session_id = None
                if _nmt_service:
                    try:
                        _nmt_service.set_glossary(None)
                    except Exception:
                        pass
                manager.lecture_glossary_keys = []
                manager.current_slide_id = None
                manager.current_page = 1
                manager.presentation_mode = "slide"
                # 강의 제목 초기화 — 다음 강의에서 이전 제목이 새 학생에게 stale 노출되는 것 차단.
                manager.lecture_title = ""

            elif msg_type == "lecture_pause":
                manager.is_paused = True
                print("[WS] 강의 일시정지")
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
                # page + eventSeq: 학생측 currentPage 매칭 가드 + 순서 보장.
                await manager.broadcast_to_students({
                    "type": "cursor",
                    "x": message.get("x", 0),
                    "y": message.get("y", 0),
                    "visible": message.get("visible", False),
                    "color": message.get("color", "#60A5FA"),
                    "slide_id": manager.current_slide_id,
                    "page": manager.current_page,
                    "eventSeq": _next_event_seq(),
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

            elif msg_type == "student_audio_lang":
                # 학생이 자기 audioLang 변경/초기 통보 → 강의자 참여자 패널 라벨 갱신용
                new_lang = (message.get("audio_lang") or "").strip()
                if not new_lang:
                    continue
                info = manager.student_info.get(websocket)
                if info is None:
                    continue
                info["audio_lang"] = new_lang
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
        # 발화 시작 page — chunk path 는 발화가 끝난 직후 도착하므로 current_page ≈
        # 발화 종료 page. 발화 도중 page 전환이 있었다면 종료 page 가 우선 (정책상
        # 발화 시작 page 가 이상적이나 chunk 모드는 그 시점 캡처 어려움 → 근사).
        speech_start_slide_id = manager.current_slide_id
        speech_start_page = manager.current_page

        # ASR 어휘 힌트 — 강의 제목 + config/glossary.csv 한국어 키를 Whisper hotwords 로
        # 넘겨 도메인 단어를 더 정확히 받아쓰게 함. 용어집 없으면 빈 리스트 → 기존 동작과 동일.
        # term_corrections 의 길이 내림차순 정렬 덕에 앞쪽에 긴 합성어가 와서, asr_service 의
        # 32개/280자 상한에 잘릴 때도 가장 도움 되는 (길고 구체적인) 용어가 살아남음.
        asr_hint_terms: list = []
        try:
            if manager.lecture_title:
                asr_hint_terms.append(manager.lecture_title)
            if manager.lecture_glossary_keys:
                asr_hint_terms.extend(manager.lecture_glossary_keys)
        except Exception:
            asr_hint_terms = []

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
            korean_text, asr_words = await asyncio.to_thread(
                _asr_service.transcribe_with_words, audio_bytes, "ko", asr_hint_terms
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
                print(f"[SKIP/ASR  seq={seq}] 차단 — {reason}: {korean_text!r}", flush=True)
                return

            print(f"[ASR  seq={seq}] 한: {korean_text}", flush=True)

        # _asr_semaphore 해제 → 다음 발화 ASR이 즉시 시작 가능 (pipeline parallelism)
        # Phase 2: NMT — 문장 단위 분할 처리. ASR이 한 덩어리(5초+)로 보내도 NMT/broadcast는
        # 문장별로 순차 송출 → 첫 자막이 빨리 뜸. 분할 결과 1개면 기존과 동일.
        sentences = _split_korean_sentences(korean_text)
        # 각 sub-sentence 의 정확한 lecturer 시계 시간 — Whisper 단어별 timestamp 활용.
        # multi-sentence chunk 에서 그림·커서가 첫 문장에만 몰리는 sync 문제 해결용.
        sub_timings = _assign_word_times_to_sentences(
            asr_words, sentences, speech_start_wall, audio_duration_ms,
        )

        t_nmt = time.perf_counter()
        # ASR duration — chunk 발화 전체 한 번만 측정. 같은 seq 의 모든 문장이 공유.
        asr_ms = int((t_asr_done - t_asr) * 1000)

        async def _process_sentence(sub_seq: int, sentence: str) -> None:
            """한 문장을 NMT → broadcast. NMT 완료 즉시 송출되어 첫 자막 latency 단축."""
            # pause / 강의 종료 boundary 가드.
            # ASR 끝났는데 강의 paused / 종료 됐으면 broadcast skip.
            if manager.is_paused or not manager.is_lecture_started:
                boundary = "paused" if manager.is_paused else "not started"
                print(f"[SKIP/BOUNDARY seq={seq}.{sub_seq}] {boundary} — 한: {sentence!r}", flush=True)
                return
            # sub-sentence 별 정확한 시간 — 단어별 timestamp 매핑 결과. 매핑 실패
            # (whisper word 누락 / chunk_speech_start_wall null) 시 chunk 전체 시간으로 fallback.
            sub_speech_start_wall, sub_sent_at = sub_timings[sub_seq] if sub_seq < len(sub_timings) else (speech_start_wall, sent_at)
            t_nmt_call = time.perf_counter()
            async with _nmt_semaphore:
                english = await asyncio.to_thread(
                    _nmt_service.translate, sentence, "ko", "en", 512
                )
            nmt_ms = int((time.perf_counter() - t_nmt_call) * 1000)
            # NMT 빈 결과 — 환각 트리거 차단 ('아멘', 짧은 음절 반복 등) 또는 모델 실패.
            # 학생에게 한국어 원문 자막 띄우면 환각 노이즈가 그대로 노출되므로 broadcast 자체 skip.
            # 자막 / transcripts 저장도 skip — 학생 화면에 안 뜨고 강사 측 로그만 남김.
            if not english.strip():
                print(f"[SKIP/NMT  seq={seq}.{sub_seq}] 빈 번역 — 한: {sentence!r}", flush=True)
                return
            # 원문 + 번역본 한 줄로 정리해 둘 다 한눈에 보이게.
            print(f"[BROADCAST seq={seq}.{sub_seq}] 한: {sentence}  →  영: {english}", flush=True)
            # 첫 자막 latency — 분할 효과 측정용 (마지막 자막은 LATENCY 로그의 '전체')
            if sub_seq == 0:
                print(
                    f"[FIRST seq={seq}] 첫 자막 {time.perf_counter() - t_start:.2f}s",
                    flush=True,
                )

            if manager.current_session_id:
                transcripts.append_segment(
                    manager.current_session_id, sentence, english,
                    slide_id=speech_start_slide_id, page=speech_start_page,
                )

            # TTS는 수강자 브라우저(WASM)에서 처리 — audio 필드 없이 텍스트만 전송
            # asrMs / nmtMs: 서버 단일 시계로 측정한 처리 시간 (시계 동기화 무관).
            # frontend 가 ttsMs / 전체 latency 와 합쳐 단계별 표시.
            # (sub_speech_start_wall / sub_sent_at 은 위에서 sub_timings 로 이미 추출.)
            payload = {
                "type": "transcription",
                "seq": seq,
                "sub_seq": sub_seq,           # 같은 seq 안 문장 순서 (frontend 정렬용)
                "total_sub": len(sentences),  # 한 발화의 총 문장 수
                "original": sentence,
                "translated": english,
                "sentAt": sub_sent_at if sub_sent_at is not None else sent_at,
                "speechStartAt": sub_speech_start_wall if sub_speech_start_wall is not None else speech_start_wall,
                "asrMs": asr_ms,
                "nmtMs": nmt_ms,
                "slide_id": speech_start_slide_id,
                "page": speech_start_page,
                "eventSeq": _next_event_seq(),
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


async def _incremental_asr(buf: StreamingBuffer, is_final: bool = False) -> None:
    """
    StreamingBuffer 에 쌓인 PCM16 프레임 전체를 ASR → NMT → broadcast.

    is_final=False: 직전 ASR 결과와 동일한 안정 문장(연속 2회 일치)만 commit.
    is_final=True : 남은 모든 문장을 commit.
    """
    if not all([_asr_service, _nmt_service]):
        return
    if not buf.pcm16_frames:
        return

    all_pcm16 = b''.join(buf.pcm16_frames)
    if len(all_pcm16) < 9600:  # 0.3s @ 16kHz × 2 bytes
        return

    wav_bytes = _pcm16_to_wav(all_pcm16)
    ok, reason = _validate_audio(wav_bytes)
    if not ok and not is_final:
        return

    try:
        async with _asr_semaphore:
            korean_text, _words = await asyncio.to_thread(
                _asr_service.transcribe_with_words, wav_bytes, "ko",
                manager.lecture_glossary_keys,
            )
    except Exception as e:
        print(f"[StreamASR] 오류: {e}", flush=True)
        return

    korean_text = korean_text.strip()
    if not korean_text:
        return

    ok, reason = _validate_asr_text(korean_text)
    if not ok:
        print(f"[StreamASR] 차단 — {reason}: {korean_text!r}", flush=True)
        return

    curr_sentences = _split_korean_sentences(korean_text)
    if not curr_sentences:
        return

    print(f"[StreamASR] {'FINAL' if is_final else 'INC  '}: {korean_text}", flush=True)

    if is_final:
        to_commit = curr_sentences[len(buf.committed_sentences):]
    else:
        # 직전 ASR 결과와 공통 prefix 만 안정적 — 2회 연속 동일한 문장만 commit.
        stable: list[str] = []
        for p, c in zip(buf.prev_sentences, curr_sentences):
            if p == c:
                stable.append(p)
            else:
                break
        to_commit = stable[len(buf.committed_sentences):]

    buf.prev_sentences = curr_sentences

    if not to_commit:
        return

    for sentence in to_commit:
        if manager.is_paused or not manager.is_lecture_started:
            break
        sub_seq = len(buf.committed_sentences)
        buf.committed_sentences.append(sentence)

        try:
            async with _nmt_semaphore:
                english = await asyncio.to_thread(
                    _nmt_service.translate, sentence, "ko", "en", 512
                )
        except Exception as e:
            print(f"[StreamNMT] 오류 '{sentence}': {e}", flush=True)
            continue

        if not english.strip():
            print(f"[StreamNMT] 빈 번역 — 한: {sentence!r}", flush=True)
            continue

        print(f"[StreamBROADCAST sub={sub_seq}] 한: {sentence}  →  영: {english}", flush=True)

        if manager.current_session_id:
            transcripts.append_segment(
                manager.current_session_id, sentence, english,
                slide_id=buf.slide_id, page=buf.page,
            )

        payload = {
            "type": "transcription",
            "seq": -1,
            "sub_seq": sub_seq,
            "total_sub": -1,
            "original": sentence,
            "translated": english,
            "sentAt": buf.sent_at,
            "speechStartAt": buf.speech_start_wall,
            "asrMs": 0,
            "nmtMs": 0,
            "slide_id": buf.slide_id,
            "page": buf.page,
            "streaming": True,
            "eventSeq": _next_event_seq(),
        }
        await manager.broadcast_to_students(payload)
        if manager.lecturer:
            try:
                await manager.lecturer.send_json(payload)
            except Exception:
                pass


async def process_audio_chunk(message: dict, ws_key: int) -> None:
    """
    스트리밍 200ms PCM16 프레임 수신 — 버퍼에 누적 후 5프레임(1s)마다 증분 ASR.
    """
    buf = _streaming_buffers.setdefault(ws_key, StreamingBuffer())

    if not buf.pcm16_frames:
        buf.speech_start_wall = (
            message.get("speechStartAt") or int(time.time() * 1000) - 200
        )
        buf.sent_at = message.get("sentAt") or int(time.time() * 1000)
        buf.slide_id = manager.current_slide_id
        buf.page = manager.current_page

    frame_b64 = message.get("frame", "")
    if not frame_b64:
        return
    try:
        pcm16 = base64.b64decode(frame_b64)
    except Exception:
        return

    buf.pcm16_frames.append(pcm16)
    buf.frame_count += 1

    if buf.frame_count - buf.last_asr_frame >= _ASR_CHUNK_FRAMES:
        buf.last_asr_frame = buf.frame_count
        await _incremental_asr(buf, is_final=False)


async def flush_audio_stream(message: dict, ws_key: int) -> None:
    """발화 종료 — 남은 프레임 전체에 최종 ASR 실행 후 버퍼 삭제."""
    buf = _streaming_buffers.pop(ws_key, None)
    if buf is None or not buf.pcm16_frames:
        return
    await _incremental_asr(buf, is_final=True)
