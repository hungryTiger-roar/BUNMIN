"""
TTS (Text-to-Speech) 서비스
영어 텍스트 → 음성 생성
Supertonic-2 ONNX (onnx-community/Supertonic-TTS-2-ONNX)
"""
import io
import wave
import struct
import numpy as np
from pathlib import Path
from typing import Optional


class TTSService:
    """
    음성 합성 서비스

    Supertonic-2 ONNX (66M)
    - CPU 실행
    - 실시간 합성 지원 (167x RTF)
    """

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.pipeline = None
        self.sampling_rate = 22050
        self._load_model()

    def _load_model(self):
        """Supertonic-2 ONNX 모델 로드"""
        try:
            from transformers import pipeline

            self.pipeline = pipeline(
                "text-to-speech",
                model=self.model_name,
                device=-1,  # CPU (-1), GPU (0)
            )

            # 샘플레이트 확인
            if hasattr(self.pipeline.model.config, 'sampling_rate'):
                self.sampling_rate = self.pipeline.model.config.sampling_rate

            print(f"[TTS] Supertonic-2 ONNX 로드 완료: {self.model_name}")

        except ImportError:
            raise RuntimeError("transformers가 설치되지 않았습니다")
        except Exception as e:
            print(f"[TTS] 모델 로드 오류: {e}")

    def synthesize(
        self,
        text: str,
        length_scale: float = 1.0,
    ) -> bytes:
        """
        텍스트를 음성으로 변환

        Args:
            text: 합성할 텍스트
            length_scale: 발화 속도 (1.0 = 기본)

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

            # numpy 배열 → WAV 바이트 변환
            return self._array_to_wav(audio_array, sampling_rate)

        except Exception as e:
            print(f"[TTS] 합성 오류: {e}")
            return self._create_silence(0.1)

    def _array_to_wav(self, audio_array: np.ndarray, sampling_rate: int) -> bytes:
        """numpy 배열을 WAV 바이트로 변환"""
        if audio_array.ndim > 1:
            audio_array = audio_array.squeeze()

        # float → int16 변환
        audio_int16 = (audio_array * 32767).clip(-32768, 32767).astype(np.int16)

        audio_buffer = io.BytesIO()
        with wave.open(audio_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sampling_rate)
            wav_file.writeframes(audio_int16.tobytes())

        return audio_buffer.getvalue()

    def _create_silence(self, duration: float) -> bytes:
        """무음 오디오 생성"""
        num_samples = int(self.sampling_rate * duration)
        audio_buffer = io.BytesIO()
        with wave.open(audio_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sampling_rate)
            wav_file.writeframes(struct.pack("<" + "h" * num_samples, *([0] * num_samples)))
        return audio_buffer.getvalue()

    def synthesize_streaming(self, text: str):
        """스트리밍 합성 (청크 단위 반환)"""
        yield self.synthesize(text)
