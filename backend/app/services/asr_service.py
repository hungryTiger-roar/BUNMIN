"""
ASR (Automatic Speech Recognition) 서비스
음성 → 한국어 텍스트 변환
CohereLabs/cohere-transcribe-03-2026 (transformers, GPU: bfloat16 / CPU: float32)
"""
import io
import numpy as np


def _normalize_device(device: str) -> str:
    """'cuda' → 'cuda:0' 정규화"""
    return "cuda:0" if device == "cuda" else device


class ASRService:
    def __init__(self, model_name: str = "CohereLabs/cohere-transcribe-03-2026", device: str = "cpu", dtype: str = "float32"):
        self.model_name = model_name
        self.device = _normalize_device(device)
        self.dtype = dtype
        self.processor = None
        self.model = None
        self._load_model()

    def _torch_dtype(self):
        import torch
        return {"float16": torch.float16, "bfloat16": torch.bfloat16}.get(self.dtype, torch.float32)

    def _load_model(self):
        try:
            import torch
            from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq

            self.processor = AutoProcessor.from_pretrained(
                self.model_name, trust_remote_code=True
            )
            self.model = AutoModelForSpeechSeq2Seq.from_pretrained(
                self.model_name,
                torch_dtype=self._torch_dtype(),
                device_map=self.device,
                trust_remote_code=True,
            )
            self.model.eval()
            print(f"[ASR] {self.model_name} 로드 완료 ({self.dtype}, {self.device})")
        except ImportError as e:
            raise RuntimeError(f"패키지 임포트 실패: {e}")

    def transcribe(self, audio_bytes: bytes, language: str = "ko") -> str:
        if self.model is None:
            return ""
        try:
            audio_array = self._bytes_to_array(audio_bytes)
            results = self.model.transcribe(
                processor=self.processor,
                language=language,
                audio_arrays=[audio_array],
                sample_rates=[16000],
            )
            return results[0].strip() if results else ""
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
