"""
TTS (Text-to-Speech) 서비스
영어 텍스트 → 음성 생성
Piper TTS 사용 (ONNX 기반, CPU 최적화)
"""
import io
import wave
import struct
from pathlib import Path
from typing import Optional


class TTSService:
    """
    음성 합성 서비스

    Piper TTS (ONNX 기반)
    - 빠른 추론 속도
    - 낮은 메모리 사용
    - 자연스러운 음성
    """

    def __init__(self, model_dir: str):
        self.model_dir = Path(model_dir)
        self.voice = None
        self._load_model()

    def _load_model(self):
        """Piper 모델 로드"""
        try:
            from piper import PiperVoice

            # 영어 모델 찾기 (en_US 또는 en_GB)
            onnx_files = list(self.model_dir.glob("*.onnx"))

            if not onnx_files:
                print(f"[TTS] 모델 파일이 없습니다: {self.model_dir}")
                print("[TTS] 모델 다운로드 필요: https://github.com/rhasspy/piper/releases")
                return

            model_path = onnx_files[0]
            config_path = model_path.with_suffix(".onnx.json")

            if not config_path.exists():
                # .json 확장자만 있는 경우
                config_path = model_path.with_suffix(".json")

            self.voice = PiperVoice.load(
                str(model_path),
                str(config_path) if config_path.exists() else None,
            )

            print(f"[TTS] Piper 모델 로드 완료: {model_path.name}")

        except ImportError:
            print("[TTS] Piper가 설치되지 않았습니다: pip install piper-tts")
        except Exception as e:
            print(f"[TTS] 모델 로드 오류: {e}")

    def synthesize(
        self,
        text: str,
        speaker_id: Optional[int] = None,
        length_scale: float = 1.0,
        sentence_silence: float = 0.2,
    ) -> bytes:
        """
        텍스트를 음성으로 변환

        Args:
            text: 합성할 텍스트
            speaker_id: 화자 ID (멀티 스피커 모델용)
            length_scale: 발화 속도 (1.0 = 기본)
            sentence_silence: 문장 간 침묵 (초)

        Returns:
            WAV 형식 오디오 바이트
        """
        if self.voice is None:
            # 모델이 없으면 빈 오디오 반환
            return self._create_silence(0.1)

        if not text.strip():
            return self._create_silence(0.1)

        try:
            # 음성 합성
            audio_buffer = io.BytesIO()

            with wave.open(audio_buffer, "wb") as wav_file:
                wav_file.setnchannels(1)  # 모노
                wav_file.setsampwidth(2)  # 16비트
                wav_file.setframerate(22050)  # 샘플레이트

                self.voice.synthesize(
                    text,
                    wav_file,
                    speaker_id=speaker_id,
                    length_scale=length_scale,
                    sentence_silence=sentence_silence,
                )

            return audio_buffer.getvalue()

        except Exception as e:
            print(f"[TTS] 합성 오류: {e}")
            return self._create_silence(0.1)

    def _create_silence(self, duration: float) -> bytes:
        """무음 오디오 생성"""
        sample_rate = 22050
        num_samples = int(sample_rate * duration)

        audio_buffer = io.BytesIO()
        with wave.open(audio_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(struct.pack("<" + "h" * num_samples, *([0] * num_samples)))

        return audio_buffer.getvalue()

    def synthesize_streaming(self, text: str):
        """
        스트리밍 합성 (청크 단위 반환)
        향후 구현 예정
        """
        # 현재는 전체 합성 후 반환
        yield self.synthesize(text)
