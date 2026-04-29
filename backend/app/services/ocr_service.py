"""
OCR (Optical Character Recognition) 서비스
슬라이드 이미지에서 텍스트 추출

OCR_MODEL 환경변수로 백엔드 선택:
  - "rapidocr" (기본값): RapidOCR ONNX 기반, CPU 최적화, 한국어/영어 지원
  - HuggingFace 모델 ID (예: "microsoft/trocr-base-printed"): transformers 기반
"""
import io
from typing import Optional
import numpy as np


class OCRService:
    def __init__(self):
        self.ocr = None
        self.mode = None
        self._load_model()

    def _load_model(self):
        from app.config import ModelConfig
        model_id = ModelConfig.OCR_MODEL

        if model_id.lower() == "rapidocr":
            self._load_rapidocr()
        else:
            self._load_hf_model(model_id)

    def _load_rapidocr(self):
        try:
            from pathlib import Path
            from rapidocr_onnxruntime import RapidOCR
            # 로컬 디렉토리 우선 (setup이 받은 곳), 없으면 HF hub 폴백
            # Windows 심볼릭 미지원/Electron 배포 환경에서 hf_hub_download가 깨지는 문제 회피
            local_dir = Path(__file__).parent.parent.parent.parent / "models" / "rapidocr-korean"
            if (local_dir / "model.onnx").is_file() and (local_dir / "korean_dict.txt").is_file():
                rec_path  = str(local_dir / "model.onnx")
                dict_path = str(local_dir / "korean_dict.txt")
                print(f"[OCR] RapidOCR 로컬 모델 사용: {local_dir}")
            else:
                from huggingface_hub import hf_hub_download
                rec_path  = hf_hub_download("cycloneboy/korean_PP-OCRv4_rec_infer", "model.onnx")
                dict_path = hf_hub_download("cycloneboy/korean_PP-OCRv4_rec_infer", "korean_dict.txt")
            self.ocr  = RapidOCR(rec_model_path=rec_path, rec_keys_path=dict_path)
            self.mode = "rapidocr"
            print("[OCR] RapidOCR (Korean PP-OCRv4) 초기화 완료")
        except ImportError as e:
            print(f"[OCR] 패키지 미설치: {e}")
            print("[OCR] pip install rapidocr-onnxruntime huggingface_hub")

    def _load_hf_model(self, model_id: str):
        try:
            from transformers import pipeline
            from app.config import ModelConfig
            device = 0 if ModelConfig.OCR_DEVICE == "cuda" else -1
            self.ocr = pipeline("image-to-text", model=model_id, device=device)
            self.mode = "hf"
            print(f"[OCR] HuggingFace 모델 {model_id} 초기화 완료")
        except Exception as e:
            print(f"[OCR] HuggingFace 모델 로드 실패: {e}")

    def extract_texts(
        self,
        image: "bytes | np.ndarray",
        min_confidence: float = 0.5,
    ) -> list[str]:
        if self.ocr is None:
            return []

        try:
            if self.mode == "rapidocr":
                return self._extract_rapidocr(image, min_confidence)
            elif self.mode == "hf":
                return self._extract_hf(image)
            return []
        except Exception as e:
            print(f"[OCR] 추출 오류: {e}")
            return []

    def extract_with_positions(
        self,
        image: "bytes | np.ndarray",
        min_confidence: float = 0.5,
    ) -> list[dict]:
        if self.ocr is None or self.mode != "rapidocr":
            # HuggingFace 모델은 bbox 미지원 — 텍스트만 반환
            texts = self.extract_texts(image, min_confidence)
            return [{"text": t, "bbox": None, "confidence": 1.0} for t in texts]

        try:
            if isinstance(image, bytes):
                image = self._bytes_to_array(image)

            result, _ = self.ocr(image)
            if result is None:
                return []

            extracted = []
            for line in result:
                bbox, text, confidence = line[0], line[1], line[2]
                if confidence >= min_confidence:
                    extracted.append({
                        "text": text,
                        "bbox": bbox,
                        "confidence": confidence,
                    })
            return extracted
        except Exception as e:
            print(f"[OCR] 추출 오류: {e}")
            return []

    def _extract_rapidocr(self, image, min_confidence: float) -> list[str]:
        if isinstance(image, bytes):
            image = self._bytes_to_array(image)

        result, _ = self.ocr(image)
        if result is None:
            return []

        return [
            line[1] for line in result
            if line[2] >= min_confidence
        ]

    def _extract_hf(self, image) -> list[str]:
        if isinstance(image, np.ndarray):
            from PIL import Image
            image = Image.fromarray(image)
        elif isinstance(image, bytes):
            from PIL import Image
            image = Image.open(io.BytesIO(image))

        result = self.ocr(image)
        return [r["generated_text"] for r in result if r.get("generated_text")]

    def _bytes_to_array(self, image_bytes: bytes) -> np.ndarray:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            return np.array(img)
        except ImportError:
            raise RuntimeError("Pillow가 필요합니다: pip install Pillow")
