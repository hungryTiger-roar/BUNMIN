"""
ASR (Automatic Speech Recognition) 서비스
음성 → 한국어 텍스트 변환
"""
import io
import numpy as np
from typing import Optional


class ASRService:
    """
    음성 인식 서비스

    CPU: openai/whisper-small
    GPU: CohereLabs/cohere-transcribe-03-2026
    """

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.processor = None
        self._load_model()

    def _load_model(self):
        """모델 로드"""
        if "whisper" in self.model_name.lower():
            self._load_whisper()
        else:
            self._load_transformers()

    def _load_whisper(self):
        """OpenAI Whisper 모델 로드 (CPU 최적화)"""
        try:
            import whisper
            # small 모델: 속도와 정확도 균형
            size = "small"
            if "tiny" in self.model_name:
                size = "tiny"
            elif "base" in self.model_name:
                size = "base"
            elif "medium" in self.model_name:
                size = "medium"
            elif "large" in self.model_name:
                size = "large"

            self.model = whisper.load_model(size, device=self.device)
            print(f"[ASR] Whisper {size} 모델 로드 완료")

        except ImportError:
            raise RuntimeError("Whisper가 설치되지 않았습니다: pip install openai-whisper")

    def _load_transformers(self):
        """Transformers 기반 모델 로드 (GPU)"""
        try:
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
            import torch

            self.processor = AutoProcessor.from_pretrained(self.model_name)
            self.model = AutoModelForSpeechSeq2Seq.from_pretrained(
                self.model_name,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                device_map=self.device,
            )
            print(f"[ASR] {self.model_name} 모델 로드 완료")

        except ImportError:
            raise RuntimeError("Transformers가 설치되지 않았습니다")

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
            # 오디오 바이트를 numpy 배열로 변환
            audio_array = self._bytes_to_array(audio_bytes)

            if "whisper" in self.model_name.lower():
                return self._transcribe_whisper(audio_array, language)
            else:
                return self._transcribe_transformers(audio_array, language)

        except Exception as e:
            print(f"[ASR] 오류: {e}")
            return ""

    def _bytes_to_array(self, audio_bytes: bytes) -> np.ndarray:
        """오디오 바이트를 numpy 배열로 변환 (WebM/WAV 지원)"""
        import subprocess
        import tempfile
        import os

        try:
            # 먼저 soundfile로 시도 (WAV 등)
            import soundfile as sf
            try:
                audio_array, sample_rate = sf.read(io.BytesIO(audio_bytes))
            except Exception:
                # WebM 등 지원 안 되는 형식이면 ffmpeg로 변환
                audio_array, sample_rate = self._convert_with_ffmpeg(audio_bytes)

            # 모노로 변환
            if len(audio_array.shape) > 1:
                audio_array = audio_array.mean(axis=1)

            # 16kHz로 리샘플링
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

        # 임시 파일로 저장
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f_in:
            f_in.write(audio_bytes)
            input_path = f_in.name

        output_path = input_path.replace('.webm', '.wav')

        try:
            # ffmpeg로 WAV 변환
            subprocess.run([
                'ffmpeg', '-y', '-i', input_path,
                '-ar', '16000', '-ac', '1', '-f', 'wav', output_path
            ], capture_output=True, check=True)

            # 변환된 WAV 읽기
            audio_array, sample_rate = sf.read(output_path)
            return audio_array, sample_rate

        finally:
            # 임시 파일 삭제
            import os
            if os.path.exists(input_path):
                os.remove(input_path)
            if os.path.exists(output_path):
                os.remove(output_path)

    def _transcribe_whisper(self, audio_array: np.ndarray, language: str) -> str:
        """Whisper로 음성 인식"""
        result = self.model.transcribe(
            audio_array,
            language=language,
            task="transcribe",
        )
        return result.get("text", "").strip()

    def _transcribe_transformers(self, audio_array: np.ndarray, language: str) -> str:
        """Transformers 모델로 음성 인식"""
        import torch

        # Cohere 모델은 language 파라미터 필요
        try:
            inputs = self.processor(
                audio_array,
                sampling_rate=16000,
                return_tensors="pt",
                language=language,
            )
        except TypeError:
            # language 파라미터 미지원 시
            inputs = self.processor(
                audio_array,
                sampling_rate=16000,
                return_tensors="pt",
            )

        # inputs가 dict인지 확인
        if isinstance(inputs, dict):
            if "cuda" in self.device:
                inputs = {k: v.to(self.device) if hasattr(v, 'to') else v for k, v in inputs.items()}
            with torch.no_grad():
                generated_ids = self.model.generate(**inputs)
        else:
            # inputs가 리스트나 텐서일 경우
            input_features = inputs if torch.is_tensor(inputs) else torch.tensor(inputs)
            if "cuda" in self.device:
                input_features = input_features.to(self.device)
            with torch.no_grad():
                generated_ids = self.model.generate(input_features)

        text = self.processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )[0]

        return text.strip()
