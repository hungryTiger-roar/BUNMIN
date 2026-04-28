"""
ASR (Automatic Speech Recognition) 서비스
음성 → 한국어 텍스트 변환
faster-whisper (CTranslate2) 기반
- condition_on_previous_text=False: 이전 발화 컨텍스트 무시 → hallucination 차단
- vad_filter=True: 무음 구간 자동 필터
"""
import io
import numpy as np


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
                condition_on_previous_text=False,  # 이전 발화 컨텍스트 무시 → hallucination 차단
                vad_filter=True,                   # 무음 구간 자동 필터
                beam_size=5,
            )
            return "".join(s.text for s in segments).strip()
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
