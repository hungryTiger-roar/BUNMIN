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
import numpy as np


# 모델이 학습 데이터에서 본 정치 뉴스/방송/YouTube 정형구 — 강의에서 등장 확률 ~0
# 실제 production 로그에서 관측된 패턴 + 알려진 Whisper 환각 정형구
_HALLUCINATION_PATTERNS = re.compile("|".join([
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
    r"MBC\s*뉴스",              # 방송 intro
    r"SBS\s*뉴스",
    r"KBS\s*뉴스",
    r"특파원\s*입니다",         # 방송 outro
    r"기자입니다",              # 방송 outro
]))


class ASRService:
    def __init__(self, model_name: str = "ghost613/faster-whisper-large-v3-turbo-korean", device: str = "cpu", dtype: str = "float32"):
        self.model_name = model_name
        # faster-whisper는 "cuda:0" 대신 "cuda"만 받음
        self.device = "cuda" if device in ("cuda", "cuda:0") else "cpu"
        # dtype 대신 compute_type 사용 (bfloat16 미지원 → float16으로 대체)
        self.compute_type = "float16" if self.device == "cuda" else "float32"
        self.model = None
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
                texts.append(seg.text)
            return "".join(texts).strip()
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
