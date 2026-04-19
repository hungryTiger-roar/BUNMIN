"""
TTS (Text-to-Speech) 서비스
영어 텍스트 → 음성 생성
facebook/mms-tts-eng (VITS 기반, transformers)
"""
import io
import wave
import struct
import numpy as np


class TTSService:
    """
    음성 합성 서비스

    facebook/mms-tts-eng
    - CPU 실행
    - VITS 기반 신경망 TTS
    """

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.pipeline = None
        self.sampling_rate = 16000
        self._load_model()

    def _load_model(self):
        """MMS-TTS 모델 로드"""
        try:
            from transformers import pipeline

            self.pipeline = pipeline(
                "text-to-speech",
                model=self.model_name,
                device=0 if self.device == "cuda" else -1,
            )

            if hasattr(self.pipeline.model.config, 'sampling_rate'):
                self.sampling_rate = self.pipeline.model.config.sampling_rate

            print(f"[TTS] {self.model_name} 로드 완료")

        except ImportError as e:
            raise RuntimeError(f"필수 패키지 누락: {e}")
        except Exception as e:
            print(f"[TTS] 모델 로드 오류: {e}")

    def synthesize(self, text: str, length_scale: float = 1.0) -> bytes:
        """
        텍스트를 음성으로 변환

        Args:
            text: 합성할 영어 텍스트
            length_scale: 미사용 (호환성 유지)

        Returns:
            WAV 형식 오디오 바이트
        """
        if self.pipeline is None:
            return self._create_silence(0.1)

        if not text.strip():
            return self._create_silence(0.1)

        try:
            output = self.pipeline(text)
            audio_array = output["audio"]
            sampling_rate = output.get("sampling_rate", self.sampling_rate)
            return self._array_to_wav(audio_array, sampling_rate)

        except Exception as e:
            print(f"[TTS] 합성 오류: {e}")
            return self._create_silence(0.1)

    def _array_to_wav(self, audio_array: np.ndarray, sampling_rate: int) -> bytes:
        """numpy 배열을 WAV 바이트로 변환"""
        if audio_array.ndim > 1:
            audio_array = audio_array.squeeze()

        audio_int16 = (audio_array * 32767).clip(-32768, 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sampling_rate)
            wf.writeframes(audio_int16.tobytes())
        return buf.getvalue()

    def _create_silence(self, duration: float) -> bytes:
        """무음 오디오 생성"""
        num_samples = int(self.sampling_rate * duration)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sampling_rate)
            wf.writeframes(struct.pack("<" + "h" * num_samples, *([0] * num_samples)))
        return buf.getvalue()

    def synthesize_streaming(self, text: str):
        """스트리밍 합성 (청크 단위 반환)"""
        yield self.synthesize(text)
