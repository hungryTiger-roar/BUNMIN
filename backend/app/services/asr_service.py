"""
ASR (Automatic Speech Recognition) 서비스
음성 → 한국어 텍스트 변환
faster-whisper (CTranslate2 기반, GPU float16)
"""
import io
import numpy as np
from typing import Optional


class ASRService:
    """
    음성 인식 서비스

    faster-whisper large-v3-turbo
    - GPU: float16 (CTranslate2)
    - CPU: float32
    """

    def __init__(self, model_name: str, device: str = "cpu", dtype: str = "float32"):
        self.model_name = model_name
        self.device = device
        self.compute_type = dtype  # faster-whisper compute_type
        self.model = None
        self._load_model()

    def _load_model(self):
        """faster-whisper 모델 로드"""
        try:
            from faster_whisper import WhisperModel
            from huggingface_hub import snapshot_download

            # 로컬 캐시 경로를 먼저 확보 → WhisperModel이 자체 다운로드 시도하지 않음
            local_path = snapshot_download(self.model_name)

            self.model = WhisperModel(
                local_path,
                device=self.device,
                compute_type=self.compute_type,
            )
            print(f"[ASR] faster-whisper {self.model_name} 로드 완료 ({self.compute_type})")

        except ImportError:
            raise RuntimeError("faster-whisper가 설치되지 않았습니다: pip install faster-whisper")

    def transcribe(self, audio_bytes: bytes, language: str = "ko") -> str:
        """
        음성을 텍스트로 변환

        Args:
            audio_bytes: WAV/WebM 등 오디오 바이트 데이터
            language: 입력 언어 코드 (기본: 한국어)

        Returns:
            인식된 텍스트
        """
        if self.model is None:
            return ""

        try:
            audio_array = self._bytes_to_array(audio_bytes)
            segments, _ = self.model.transcribe(
                audio_array,
                language=language,
                task="transcribe",
            )
            text = " ".join([seg.text for seg in segments]).strip()
            return text

        except Exception as e:
            print(f"[ASR] 오류: {e}")
            return ""

    def _bytes_to_array(self, audio_bytes: bytes) -> np.ndarray:
        """오디오 바이트를 numpy 배열로 변환 (WebM/WAV 지원)"""
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
        """ffmpeg로 오디오를 WAV로 변환"""
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
