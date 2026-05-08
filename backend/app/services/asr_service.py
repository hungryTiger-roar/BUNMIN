"""
ASR (Automatic Speech Recognition) 서비스
음성 → 한국어 텍스트 변환
faster-whisper (CTranslate2) 기반
- condition_on_previous_text=False: 이전 발화 컨텍스트 무시 → hallucination 차단
- vad_filter=True: 무음 구간 자동 필터
- 환각 패턴 블랙리스트: ghost613 모델이 침묵/잡음에 뉴스/YouTube 정형구 토해내는 문제 후처리 차단
"""
import io
import re
import time
import numpy as np


# 모델이 학습 데이터에서 본 정치 뉴스/방송/YouTube 정형구 — 강의에서 등장 확률 ~0
# 실제 production 로그에서 관측된 패턴 + 알려진 Whisper 환각 정형구
_HALLUCINATION_PATTERNS = re.compile(
    "|".join([
        r"국감장",                  # 국정감사장 (정치 뉴스 빈출)
        r"조정식",                  # 특정 정치인 (관측됨)
        r"홍\s*사장",               # 특정 인물 (관측됨)
        r"용재진",                  # 환각으로 등장한 이름 (관측됨)
        r"국토교[통토]위원",        # "국토교토위원회/장" — Whisper 오타 포함 (관측됨)
        r"기관\s*증인",             # 국감 전용 용어 (관측됨)
        r"발언에\s*국감",           # "발언에 국감장이 술렁이자" (관측됨)
        r"술렁이자",                # 뉴스 정형 동사 (관측됨, 강의 등장 거의 없음)
        r"시청해\s*주셔서",         # YouTube outro
        r"구독과\s*좋아요",         # YouTube outro
        r"영상\s*편집",             # "영상편집 및 자막 제공..." (streaming 에서 관측됨)
        r"자막\s*제공",             # "자막 제공" — YouTube/방송 정형구
        r"광고\s*를?\s*포함",       # "광고를 포함하고 있습니다" — YouTube 정형구
        # "다음 영상에서 만나요" 류 — 작별 동사 (만나/뵙/봐) 붙은 형태만 매칭해
        # 강사의 정상 예고 ("다음 시간에는 미적분") 는 보존.
        r"다음\s*(?:화|편|영상|시간)\s*에\s*(?:서)?\s*(?:만나|뵙|봐|봬)",
        # 영어 YouTube outro — Whisper 가 language=ko 에서도 토하는 학습 잔재.
        # 한국어 강의에 진짜 영어 인사가 등장할 가능성 거의 없어 false positive 위험 작음.
        r"\bthank\s*you\b",
        r"\bthanks?\s*for\s*watching\b",
        r"\bsee\s*you\s*(?:next|in|soon|later)?\b",
        r"\bsubscribe\b",
        r"\blike\s*and\s*subscribe\b",
        r"MBC\s*뉴스",              # 방송 intro
        r"SBS\s*뉴스",
        r"KBS\s*뉴스",
        r"특파원\s*입니다",         # 방송 outro
        r"기자입니다",              # 방송 outro
    ]),
    # 영어 패턴은 대소문자 구분 안 함. 한국어 패턴엔 영향 없음.
    re.IGNORECASE,
)

# Whisper 가 침묵/노이즈에서 자주 토하는 짧은 한국어 정형 인사구 — YouTube 영상 끝마다
# 등장하는 표현들이 학습 데이터에 누적된 결과. 단독으로 등장하면 환각일 가능성 높음.
# (강의 진짜 끝 인사도 매칭되지만, no_speech_prob 가 높을 때만 차단해 false-positive 최소화)
_SILENCE_HALLUCINATION_PHRASES = re.compile(
    r"^\s*(?:"
    r"감사합니다|고맙습니다|감사해요|"
    r"수고하셨습니다|수고하세요|"
    r"안녕하세요|안녕히\s*가세요|안녕히\s*계세요|"
    r"구독\s*(부탁|해)|좋아요\s*(부탁|눌러)|"
    r"다음\s*(시간|영상)에서?\s*(만나|봬|봐)|"
    r"이상입니다|이상\s*\S+\s*이었습니다"
    r")[\s\.\!\?]*$"
)

# 부분 환각 trim — 정상 문장 뒤에 붙은 YouTube outro 정형구 꼬리만 제거.
# "다음 시간에는 미적분" 같은 강의 예고는 보존하기 위해 작별 동사 (만나/봬/봐/뵐) 결합 시만 매칭.
# "오늘 강의는 X 였습니다 시청해주셔서 감사합니다" → "오늘 강의는 X 였습니다" 만 살림.
_TRAILING_HALLUCINATION = re.compile(
    r"\s*(?:"
    r"시청해\s*주(셔서|시는).*$|"
    r"구독과?\s*좋아요.*$|"
    r"다음\s*(시간|영상)에서?\s*(만나(요)?|봬요|봐요|뵐게요).*$|"
    r"감사합니다[\s\.\!\?]*$"
    r")",
    re.IGNORECASE,
)

# 짧은 인사 중복 차단 윈도우 (초). 진짜 강의 끝 인사 1번은 통과시키되 그 후 silence
# 환각으로 같은 표현이 또 와도 차단. 30초면 강의 흐름에 자연스러운 길이.
_POLITE_DEDUP_WINDOW_SEC = 30.0


class ASRService:
    def __init__(self, model_name: str = "models/whisper-large-v3-turbo-ct2-int8", device: str = "cpu", dtype: str = "float32"):
        self.model_name = model_name
        # faster-whisper는 "cuda:0" 대신 "cuda"만 받음
        self.device = "cuda" if device in ("cuda", "cuda:0") else "cpu"
        # dtype 대신 compute_type 사용 (bfloat16 미지원 → float16으로 대체)
        self.compute_type = "float16" if self.device == "cuda" else "float32"
        self.model = None
        # 짧은 인사 중복 차단 — 진짜 끝 인사 1번만 통과시키기 위한 캐시
        self._last_polite_text: str = ""
        self._last_polite_at: float = 0.0
        self._load_model()

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
            print(f"[ASR] {self.model_name} 로드 완료 ({self.compute_type}, {self.device})")
            if self.device == "cuda":
                try:
                    import torch
                    if torch.cuda.is_available():
                        vram_used = torch.cuda.memory_allocated() / 1024 ** 3
                        vram_total = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
                        vram_free = vram_total - vram_used
                        print(
                            f"[ASR] VRAM 사용량: {vram_used:.2f}GB / 잔량: {vram_free:.2f}GB "
                            f"(전체: {vram_total:.2f}GB)",
                            flush=True,
                        )
                except Exception:
                    pass
        except ImportError as e:
            raise RuntimeError(
                f"faster-whisper 패키지가 필요합니다: pip install faster-whisper\n{e}"
            )

    def transcribe(self, audio_bytes: bytes, language: str = "ko") -> str:
        if self.model is None:
            return ""
        try:
            audio_array = self._bytes_to_array(audio_bytes)
            segments, _ = self.model.transcribe(
                audio_array,
                language=language,
                beam_size=5,                       # 측정 결과 beam=1 대비 WER 1.9%p 우위, 속도 차이는 노이즈 안
                condition_on_previous_text=False,  # 이전 발화 컨텍스트 무시 → hallucination 차단
                vad_filter=True,                   # 무음 구간 자동 필터
            )
            texts = []
            for seg in segments:
                # 환각 차단 4중 필터 (메타정보 3 + 텍스트 패턴 1):
                # ① compression_ratio: 반복 환각 ("교통과 교통과 교통과...") 잡음. Whisper 권장 컷오프 2.4
                # ② no_speech_prob: 무음/잡음 구간 환각. 0.4로 강화
                # ③ avg_logprob: 모델 확신도 극히 낮은 출력
                # ④ 텍스트 블랙리스트: 모델이 "확신하면서" 토해내는 뉴스/YouTube 정형구 (메타필터 통과함)
                if seg.compression_ratio > 2.4:
                    print(f"[ASR] 세그먼트 스킵 — compression_ratio={seg.compression_ratio:.2f}: {seg.text!r}")
                    continue
                if seg.no_speech_prob > 0.4:
                    print(f"[ASR] 세그먼트 스킵 — no_speech_prob={seg.no_speech_prob:.2f}: {seg.text!r}")
                    continue
                if seg.avg_logprob < -0.8:
                    print(f"[ASR] 세그먼트 스킵 — avg_logprob={seg.avg_logprob:.2f}: {seg.text!r}")
                    continue
                if _HALLUCINATION_PATTERNS.search(seg.text):
                    print(f"[ASR] 세그먼트 스킵 — 환각 정형구 매칭: {seg.text!r}")
                    continue
                # ⑤ 짧은 인사 정형구 + 의심 metric 조합 — 진짜 강의 끝 인사는 metric 이
                #    깨끗하므로 통과, silence-환각으로 발생한 "감사합니다" 만 정확히 차단.
                #    no_speech_prob > 0.2 OR avg_logprob < -0.4 둘 중 하나만 의심돼도 차단.
                if _SILENCE_HALLUCINATION_PHRASES.match(seg.text):
                    if seg.no_speech_prob > 0.2 or seg.avg_logprob < -0.4:
                        print(
                            f"[ASR] 세그먼트 스킵 — silence 인사 환각 "
                            f"(no_speech={seg.no_speech_prob:.2f}, "
                            f"logprob={seg.avg_logprob:.2f}): {seg.text!r}"
                        )
                        continue
                # ⑥ 부분 환각 trim — 본문 뒤 꼬리 정형구만 제거. 작별 동사 결합 시만
                #    매칭되어 "다음 시간에는 미적분..." 같은 정상 예고는 보존.
                trimmed = _TRAILING_HALLUCINATION.sub("", seg.text).strip()
                if trimmed != seg.text.strip() and trimmed:
                    print(f"[ASR] 꼬리 환각 trim: {seg.text!r} → {trimmed!r}")
                if not trimmed:
                    continue
                texts.append(trimmed)
            final_text = "".join(texts).strip()

            # ⑦ 짧은 인사 중복 차단 — 진짜 강의 끝 "감사합니다" 1번은 통과,
            #    30초 내 같은 짧은 인사가 또 오면 silence 환각으로 간주하여 차단.
            if len(final_text) < 15 and _SILENCE_HALLUCINATION_PHRASES.match(final_text):
                now = time.time()
                if (
                    final_text == self._last_polite_text
                    and now - self._last_polite_at < _POLITE_DEDUP_WINDOW_SEC
                ):
                    print(f"[ASR] 짧은 인사 중복 차단 ({_POLITE_DEDUP_WINDOW_SEC:.0f}s 윈도우): {final_text!r}")
                    return ""
                self._last_polite_text = final_text
                self._last_polite_at = now
            return final_text
        except Exception as e:
            import traceback
            print(f"[ASR] 오류: {e}")
            print(traceback.format_exc())
            return ""

    def _bytes_to_array(self, audio_bytes: bytes) -> np.ndarray:
        try:
            import soundfile as sf
            try:
                audio_array, sample_rate = sf.read(io.BytesIO(audio_bytes))
            except Exception:
                audio_array, sample_rate = self._convert_with_ffmpeg(audio_bytes)

            if len(audio_array.shape) > 1:
                audio_array = audio_array.mean(axis=1)

            if sample_rate != 16000:
                import librosa
                audio_array = librosa.resample(
                    audio_array, orig_sr=sample_rate, target_sr=16000
                )

            return audio_array.astype(np.float32)
        except Exception as e:
            print(f"[ASR] 오디오 변환 오류: {e}")
            raise

    def _convert_with_ffmpeg(self, audio_bytes: bytes) -> tuple:
        import subprocess
        import tempfile
        import soundfile as sf
        import os

        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f_in:
            f_in.write(audio_bytes)
            input_path = f_in.name

        output_path = input_path.replace('.webm', '.wav')
        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', input_path,
                '-ar', '16000', '-ac', '1', '-f', 'wav', output_path
            ], capture_output=True, check=True)
            audio_array, sample_rate = sf.read(output_path)
            return audio_array, sample_rate
        finally:
            if os.path.exists(input_path):
                os.remove(input_path)
            if os.path.exists(output_path):
                os.remove(output_path)
