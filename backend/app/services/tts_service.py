"""
TTS (Text-to-Speech) 서비스
영어 텍스트 → 음성 생성
Piper TTS (en_US-lessac-medium.onnx, piper-tts 패키지)
"""
import io
import struct
import wave
from pathlib import Path

_MODEL_DIR = Path(__file__).parent / "models"
_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"


class TTSService:
    def __init__(self, model_name: str = "piper", device: str = "cpu"):
        self.model_path = _MODEL_DIR / "en_US-lessac-medium.onnx"
        self.config_path = _MODEL_DIR / "en_US-lessac-medium.onnx.json"
        self.sampling_rate = 22050
        self.voice = None
        self._ensure_model()
        self._load_model()

    def _ensure_model(self):
        if self.model_path.exists() and self.config_path.exists():
            return
        _MODEL_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import requests
        except ImportError:
            raise RuntimeError("requests 미설치: pip install requests")
        for fname, path in [
            ("en_US-lessac-medium.onnx", self.model_path),
            ("en_US-lessac-medium.onnx.json", self.config_path),
        ]:
            if path.exists():
                continue
            print(f"[TTS] Piper 모델 다운로드 중: {fname}")
            resp = requests.get(f"{_BASE_URL}/{fname}", stream=True)
            resp.raise_for_status()
            with open(path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"[TTS] {fname} 다운로드 완료")

    def _load_model(self):
        try:
            from piper import PiperVoice
            self.voice = PiperVoice.load(str(self.model_path), str(self.config_path))
            self.sampling_rate = self.voice.config.sample_rate
            print("[TTS] Piper en_US-lessac-medium 로드 완료")
        except ImportError as e:
            print(f"[TTS] piper-tts 미설치: {e}")
            print("[TTS] pip install piper-tts")
        except Exception as e:
            print(f"[TTS] 모델 로드 오류: {e}")

    def synthesize(self, text: str, length_scale: float = 1.0) -> bytes:
        if self.voice is None or not text.strip():
            return self._create_silence(0.1)
        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self.sampling_rate)
                for chunk in self.voice.synthesize(text):
                    wav.writeframes(chunk.audio_int16_bytes)
            return buf.getvalue()
        except Exception as e:
            print(f"[TTS] 합성 오류: {e}")
            return self._create_silence(0.1)

    def _create_silence(self, duration: float) -> bytes:
        num_samples = int(self.sampling_rate * duration)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sampling_rate)
            wf.writeframes(struct.pack("<" + "h" * num_samples, *([0] * num_samples)))
        return buf.getvalue()

    def synthesize_streaming(self, text: str):
        yield self.synthesize(text)
