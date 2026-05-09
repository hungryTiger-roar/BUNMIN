"""
Streaming ASR 서비스 (실험 기능, ASR_STREAMING=true 시 활성)

기존 ASRService 와 같은 faster-whisper WhisperModel 인스턴스를 공유하면서
sliding audio buffer + periodic transcribe(word_timestamps=True) +
LocalAgreement-2 안정화 + 한국어 종결어미 boundary 로
"문장이 끝나는 시점에 1문장씩" finalize 하는 streaming 레이어.

목표: 호흡 없이 길게 말하는 강사 케이스에서 첫 자막 latency 단축.
1문장 발화에서는 chunk-based 와 거의 동등 (LocalAgreement 안정화 overhead 가
VAD redemption 절약분을 상쇄).

참고: 진짜 production-grade streaming 은 ufal/whisper_streaming 의
LocalAgreement-2 full 구현을 봐야 함. 이 파일은 단순화 버전.
"""
import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .asr_service import (
    _HALLUCINATION_PATTERNS,
    _SILENCE_HALLUCINATION_PHRASES,
    _TRAILING_HALLUCINATION,
)


def _env_float(key: str, default: float) -> float:
    """env 에서 float 값 읽기 — 파싱 실패 시 default. 운영 중 튜닝용."""
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[StreamingASR] env {key}={raw!r} 파싱 실패 → 기본값 {default} 사용", flush=True)
        return default


# 한국어 종결어미 — 문장이 끝났음을 표시하는 마지막 형태소 패턴.
# 보수적 매칭: "음절+종결어미+구두점(.!?)" 형태만 인정 → 본문 중간 "다음" 같은 단어
# 가 오탐되지 않게. 구두점 강제로 false positive 거의 없음.
# 알고리즘: 정규식 alternation 은 left-to-right first-match — 긴 패턴부터 나열해야
# "합니다." 가 "다." 가 아니라 "습니다." 로 매칭됨.
_SENTENCE_TERMINATOR = re.compile(
    r"[가-힣]*?"                              # 종결어미 앞 음절
    r"("
    # === 격식체 (formal) — 4~3글자 ===
    r"습니다|습니까|입니다|입니까|"
    r"십시오|십시다|ㅂ니다|ㅂ니까|"
    # === 존댓말 -요 종결 — 3글자 ===
    r"거든요|잖아요|는데요|던데요|는군요|"
    r"이에요|으세요|을게요|을까요|ㄹ게요|ㄹ까요|"
    r"잖니요|구나요|"
    # === 존댓말 -요 종결 — 2글자 ===
    r"네요|군요|지요|아요|어요|에요|예요|세요|대요|데요|"
    # === 반말 종결 — 2~3글자 ===
    r"잖아|거든|는데|구나|구먼|단다|더라|던데|는군|"
    r"답니다|답니까|"   # -답니다, -답니까 (대화체 인용)
    r"ㄹ까|ㄹ게|을까|을게|"
    # === 반말 + -요 (1글자 + 요) ===
    r"죠|"
    # === 반말 1글자 종결 (구두점 필수) ===
    r"네|군|데|대|"
    # === 단음절 종결 (구두점이 강제라 false positive 적음) ===
    r"다|요|까|야|자|어|아|지|니|냐|"
    # === 의문/감탄 ===
    r"나"                # "어쩌나.", "어디나." 같은 케이스
    r")"
    r"[.!?]+\s*"                              # 구두점 1개+ 와 trailing space
)

# 아래 4개 튜닝 상수는 env 로 오버라이드 가능. backend 재시작 없이 .env 만 바꾸고
# 프로세스 restart 하면 반영. 의미를 모르면 기본값 유지 권장.

# Whisper streaming context 에서 "꼬리" finalize 시 추가 grace 시간 (초).
# audio buffer 가 종결어미 직후 끝나도, 다음 word 가 N초 안에 안 오면 진짜 문장 끝으로 간주.
# ASR_STREAMING_GRACE_SEC: 작을수록 finalize 빨라짐 (자막 빨리 뜸) / 너무 작으면 다음 word 가
# 종결어미 의 부분으로 합쳐져야 했는데 미리 잘림. 0.2~0.5 권장.
_TERMINATION_GRACE_SEC = _env_float("ASR_STREAMING_GRACE_SEC", 0.3)

# transcribe 주기 — 너무 짧으면 GPU 부하 ↑, 길면 자막 lag ↑.
# ASR_STREAMING_INTERVAL_SEC: 200ms frame push 받을 때마다 transcribe 트리거 후 본 시간만큼 throttle.
# 0.2~0.5 권장. 단일 GPU 환경에서 chunk path 와 경합 시 늘리면 부하 분산.
_MIN_TRANSCRIBE_INTERVAL_SEC = _env_float("ASR_STREAMING_INTERVAL_SEC", 0.25)

# Buffer 최대 길이 (초) — 종결어미 못 잡고 누적되는 비정상 케이스 방어. 초과 시 force-finalize.
# ASR_STREAMING_MAX_BUFFER_SEC: 너무 짧으면 정상 발화도 강제로 잘림 / 길면 sync 어긋남.
# 8s 권장 — 22~66s buffer 누적으로 학생측 lecturerSpan 비정상 → visual sync 깨짐 방지.
# 강사가 한 호흡 8s 이상 길게 말하면 중간에 잘릴 수 있음 (절충점).
_MAX_BUFFER_SEC = _env_float("ASR_STREAMING_MAX_BUFFER_SEC", 8.0)

# Buffer 최소 길이 (초) — 너무 짧은 buffer 는 transcribe 무의미.
# ASR_STREAMING_MIN_BUFFER_SEC: 0.3~0.8 권장. 작으면 transcribe 잦아져 GPU 부하 ↑.
_MIN_TRANSCRIBE_BUFFER_SEC = _env_float("ASR_STREAMING_MIN_BUFFER_SEC", 0.4)


@dataclass
class _Word:
    """faster-whisper Word 의 dataclass 카피 (메모리 보관용)."""
    text: str
    start: float
    end: float


@dataclass
class _StreamingState:
    """Service 상태 — flush/reset 시 한 번에 초기화."""
    audio_buffer: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    prev_words: list[_Word] = field(default_factory=list)
    last_transcribe_at: float = 0.0


class ASRStreamingService:
    """faster-whisper WhisperModel 을 공유해 streaming 처리.
    호출자는 push_frame() 으로 PCM 을 누적시키고, 반환된 finalize 문장 리스트를
    NMT/broadcast 로 흘려보낸다. 발화 종료 시 flush() 로 잔여 buffer 강제 finalize.
    """

    def __init__(self, whisper_model, gpu_lock: Optional[asyncio.Semaphore] = None):
        self.model = whisper_model
        self._state = _StreamingState()
        self._lock = asyncio.Lock()
        # chunk path 의 _asr_semaphore 와 같은 인스턴스를 공유받아 두 path 가
        # 동일 GPU/모델로 동시에 transcribe 들어가지 않도록 직렬화. None 이면
        # 단독 사용으로 간주 (테스트용).
        self._gpu_lock = gpu_lock

    async def _run_transcribe(self) -> list["_Word"]:
        """GPU semaphore 를 잡고 thread 에서 transcribe. push_frame / _force_finalize
        에서 공통으로 호출."""
        if self._gpu_lock is not None:
            async with self._gpu_lock:
                return await asyncio.to_thread(self._transcribe_buffer)
        return await asyncio.to_thread(self._transcribe_buffer)

    async def push_frame(self, pcm_int16: np.ndarray, sample_rate: int = 16000) -> list[str]:
        """16kHz mono PCM int16 frame 을 buffer 에 누적하고, 종결어미가 잡히면
        그 시점까지의 문장 리스트를 반환. 매 호출마다 transcribe 하지 않고
        _MIN_TRANSCRIBE_INTERVAL_SEC throttle 적용.
        """
        if self.model is None or pcm_int16.size == 0:
            return []
        async with self._lock:
            float_frame = pcm_int16.astype(np.float32) / 32768.0
            if sample_rate != 16000:
                # streaming 경로는 16kHz 고정 가정 — 다른 rate 면 frontend 버그
                print(f"[StreamingASR] WARN sample_rate={sample_rate} (16000 expected)", flush=True)
            self._state.audio_buffer = np.concatenate(
                [self._state.audio_buffer, float_frame]
            )

            # buffer 폭주 방어 — 종결어미 못 잡고 15초 누적되면 강제 finalize
            buf_sec = len(self._state.audio_buffer) / 16000
            if buf_sec >= _MAX_BUFFER_SEC:
                print(
                    f"[StreamingASR] buffer 한도 초과 ({buf_sec:.1f}s) → 강제 finalize",
                    flush=True,
                )
                return await self._force_finalize()

            # transcribe throttle — 짧은 간격으로 들어오는 frame 은 묶어서 처리
            now = time.time()
            if now - self._state.last_transcribe_at < _MIN_TRANSCRIBE_INTERVAL_SEC:
                return []
            if buf_sec < _MIN_TRANSCRIBE_BUFFER_SEC:
                return []
            self._state.last_transcribe_at = now

            transcript_words = await self._run_transcribe()
            stable_words = self._local_agreement(transcript_words)
            self._state.prev_words = transcript_words

            sentences, consumed_until_sec = self._extract_finalized(stable_words)
            if sentences and consumed_until_sec > 0:
                self._trim_buffer(consumed_until_sec)
                # 다음 transcribe 의 LocalAgreement 비교 기준 리셋
                # (buffer 가 잘렸으니 이전 word timestamp 는 의미 없음)
                self._state.prev_words = []
            return sentences

    async def flush(self) -> list[str]:
        """VAD onSpeechEnd 시 호출 — buffer 잔여분 transcribe 후 종결어미
        못 찾아도 통째로 finalize. 종결어미 매칭이 가능하면 분할.
        """
        async with self._lock:
            return await self._force_finalize()

    async def reset(self) -> None:
        """강의 종료 등 세션 boundary 에서 buffer 완전 비움."""
        async with self._lock:
            self._state = _StreamingState()

    # ── 내부 유틸 ───────────────────────────────────────────────────────────

    async def _force_finalize(self) -> list[str]:
        """buffer 잔여분을 transcribe 한 후 통째로 / 종결어미 단위로 분할 반환.
        호출 후 buffer 는 비워짐. push_frame / flush 둘 다 self._lock 보유 상태에서 호출.
        """
        if len(self._state.audio_buffer) < int(16000 * 0.2):
            self._state = _StreamingState()
            return []
        try:
            words = await self._run_transcribe()
        except Exception as e:
            print(f"[StreamingASR] flush transcribe 실패: {e}", flush=True)
            self._state = _StreamingState()
            return []
        text = "".join(w.text for w in words).strip()
        self._state = _StreamingState()
        if not text:
            return []
        # 종결어미가 텍스트 안에 여러 개 있으면 분할, 없으면 통째 1문장
        sentences = []
        remaining = text
        while True:
            m = _SENTENCE_TERMINATOR.search(remaining)
            if not m:
                break
            sentences.append(remaining[: m.end()].strip())
            remaining = remaining[m.end():].strip()
        if remaining:
            sentences.append(remaining)
        return [s for s in sentences if s]

    def _transcribe_buffer(self) -> list[_Word]:
        """현재 buffer 전체를 transcribe → word-level 결과. 환각 가드 포함.
        sync 함수 — push_frame 에서 to_thread 로 호출됨.
        """
        if len(self._state.audio_buffer) < int(16000 * _MIN_TRANSCRIBE_BUFFER_SEC):
            return []
        segments, _ = self.model.transcribe(
            self._state.audio_buffer,
            language="ko",
            beam_size=1,                       # streaming 은 속도 우선 (chunk path 는 5)
            condition_on_previous_text=False,
            vad_filter=True,
            word_timestamps=True,
        )
        words: list[_Word] = []
        for seg in segments:
            # 환각 가드 — chunk path 와 동일 임계값. 진단용으로 어떤 가드에서 떨어지는지
            # 로그 남김. 운영 안정화되면 silent 로 되돌릴 수 있음.
            if seg.compression_ratio > 2.4:
                print(
                    f"[STREAM] 세그먼트 스킵 — compression_ratio={seg.compression_ratio:.2f}: {seg.text!r}",
                    flush=True,
                )
                continue
            if seg.no_speech_prob > 0.4:
                print(
                    f"[STREAM] 세그먼트 스킵 — no_speech_prob={seg.no_speech_prob:.2f}: {seg.text!r}",
                    flush=True,
                )
                continue
            if seg.avg_logprob < -0.8:
                print(
                    f"[STREAM] 세그먼트 스킵 — avg_logprob={seg.avg_logprob:.2f}: {seg.text!r}",
                    flush=True,
                )
                continue
            if _HALLUCINATION_PATTERNS.search(seg.text):
                print(
                    f"[STREAM] 세그먼트 스킵 — 환각 정형구 매칭: {seg.text!r}",
                    flush=True,
                )
                continue
            # silence-phrase + 의심 metric 가드 (chunk path 와 동등).
            # 정상 발화는 metric 깨끗하므로 통과, silence 환각으로 발생한 "감사합니다" /
            # "안녕하세요" 류는 metric 이 의심스러워 차단. shadow log 측정 결과 95%+ 가
            # 환각으로 분류돼 활성화.
            if _SILENCE_HALLUCINATION_PHRASES.match(seg.text):
                if seg.no_speech_prob > 0.2 or seg.avg_logprob < -0.4:
                    print(
                        f"[STREAM] 세그먼트 스킵 — silence 인사 환각 "
                        f"(no_speech={seg.no_speech_prob:.2f} logprob={seg.avg_logprob:.2f}): {seg.text!r}",
                        flush=True,
                    )
                    continue
            for w in (seg.words or []):
                # word.word 에는 보통 leading space 가 포함됨 — 보존하면 join 시 공백 자연스러움
                words.append(_Word(text=w.word, start=float(w.start), end=float(w.end)))
        return words

    def _local_agreement(self, current: list[_Word]) -> list[_Word]:
        """LocalAgreement-2 단순화: prev 와 current 의 prefix 가 일치하는
        구간까지만 'stable' 로 인정. 단어 텍스트 비교 (whitespace 제거).
        """
        prev = self._state.prev_words
        stable: list[_Word] = []
        for i, w in enumerate(current):
            if i < len(prev) and prev[i].text.strip() == w.text.strip():
                stable.append(w)
            else:
                break
        return stable

    def _extract_finalized(
        self, stable_words: list[_Word]
    ) -> tuple[list[str], float]:
        """안정 word 시퀀스에서 종결어미 매칭으로 완전한 문장(들) 추출.
        반환: (문장 리스트, buffer 에서 finalize 된 마지막 시각[초]).
        """
        if not stable_words:
            return [], 0.0
        text = "".join(w.text for w in stable_words)
        # 마지막 안정 word 의 end 시각 — 그 시각 이후로 grace period 가 지나지
        # 않았다면 finalize 보류 (다음 단어가 막 들어올 가능성)
        last_word_end = stable_words[-1].end
        buf_sec = len(self._state.audio_buffer) / 16000
        if buf_sec - last_word_end < _TERMINATION_GRACE_SEC:
            # 아직 grace period 안 — 다음 frame 받고 다시 판단
            return [], 0.0

        sentences: list[str] = []
        consumed_until_word_idx: int = -1
        cursor = 0
        for idx, w in enumerate(stable_words):
            cursor_end = cursor + len(w.text)
            chunk = text[: cursor_end]
            m = _SENTENCE_TERMINATOR.search(chunk)
            if m:
                sentence = chunk[: m.end()].strip()
                # 환각 trim — 꼬리 정형구 제거
                trimmed = _TRAILING_HALLUCINATION.sub("", sentence).strip()
                if trimmed:
                    sentences.append(trimmed)
                consumed_until_word_idx = idx
                # 다음 종결어미 검색 시작점 갱신
                text = text[m.end():]
                # cursor 도 같이 reset (text 가 잘렸으니)
                cursor = 0
                continue
            cursor = cursor_end

        if consumed_until_word_idx < 0:
            return [], 0.0
        consumed_until_sec = stable_words[consumed_until_word_idx].end
        return sentences, consumed_until_sec

    def _trim_buffer(self, until_sec: float) -> None:
        """audio_buffer 에서 until_sec 시각 이전 구간을 잘라냄.
        sample_rate=16000 가정.
        """
        cut_samples = int(until_sec * 16000)
        if cut_samples <= 0:
            return
        if cut_samples >= len(self._state.audio_buffer):
            self._state.audio_buffer = np.zeros(0, dtype=np.float32)
        else:
            self._state.audio_buffer = self._state.audio_buffer[cut_samples:]
