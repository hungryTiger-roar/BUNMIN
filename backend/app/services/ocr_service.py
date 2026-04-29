"""
OCR (Optical Character Recognition) 서비스
슬라이드 이미지에서 텍스트 추출

OCR_MODEL 환경변수로 백엔드 선택:
  - "surya" (기본값): Surya OCR Transformer 기반, GPU 최적화, 한글 정확도 우수
  - "rapidocr": RapidOCR ONNX 기반, CPU 최적화, 한국어/영어 지원
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

        if model_id.lower() == "surya":
            self._load_surya()
        elif model_id.lower() == "rapidocr":
            self._load_rapidocr()
        else:
            self._load_hf_model(model_id)

    def _load_surya(self):
        """Surya OCR 로드 (슬라이드 번역에서 사용하는 것과 동일)"""
        try:
            from surya.foundation import FoundationPredictor
            from surya.detection import DetectionPredictor
            from surya.recognition import RecognitionPredictor

            self.foundation_predictor = FoundationPredictor()
            self.det_predictor = DetectionPredictor(self.foundation_predictor)
            self.rec_predictor = RecognitionPredictor(self.foundation_predictor)
            self.mode = "surya"
            print("[OCR] Surya OCR (Transformer) 초기화 완료")
        except ImportError as e:
            print(f"[OCR] Surya 패키지 미설치: {e}")
            print("[OCR] pip install surya-ocr")
            # Fallback to RapidOCR
            print("[OCR] RapidOCR로 폴백...")
            self._load_rapidocr()

    def _load_rapidocr(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
            from app.config import resolve_model_dir
            # 로컬 디렉토리 우선 (setup이 받은 곳/동봉), 없으면 HF hub 폴백
            # Windows 심볼릭 미지원/Electron 배포 환경에서 hf_hub_download가 깨지는 문제 회피
            local_dir = resolve_model_dir("rapidocr-korean")
            if local_dir and (local_dir / "model.onnx").is_file() and (local_dir / "korean_dict.txt").is_file():
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
        if self.mode is None:
            return []

        try:
            if self.mode == "surya":
                return self._extract_surya(image, min_confidence)
            elif self.mode == "rapidocr":
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
        if self.mode is None:
            return []

        try:
            if self.mode == "surya":
                return self._extract_surya_with_positions(image, min_confidence)
            elif self.mode == "rapidocr":
                return self._extract_rapidocr_with_positions(image, min_confidence)
            else:
                # HuggingFace 모델은 bbox 미지원 — 텍스트만 반환
                texts = self.extract_texts(image, min_confidence)
                return [{"text": t, "bbox": None, "confidence": 1.0} for t in texts]
        except Exception as e:
            print(f"[OCR] 추출 오류: {e}")
            return []

    def _extract_surya(self, image, min_confidence: float) -> list[str]:
        """Surya OCR로 텍스트만 추출"""
        results = self._extract_surya_with_positions(image, min_confidence)
        return [r["text"] for r in results]

    def _extract_surya_with_positions(self, image, min_confidence: float) -> list[dict]:
        """Surya OCR로 텍스트 + 위치 추출"""
        from PIL import Image as PILImage

        if isinstance(image, bytes):
            image = self._bytes_to_array(image)
        if isinstance(image, np.ndarray):
            pil_image = PILImage.fromarray(image)
        else:
            pil_image = image

        # Detection
        det_results = self.det_predictor([pil_image])
        # Recognition
        rec_results = self.rec_predictor([pil_image], det_results)

        extracted = []
        for page_result in rec_results:
            for line in page_result.text_lines:
                text = line.text.strip()
                confidence = line.confidence
                if confidence >= min_confidence and text:
                    # bbox: [x1, y1, x2, y2] 형식으로 변환
                    bbox = line.bbox
                    extracted.append({
                        "text": text,
                        "bbox": [[bbox[0], bbox[1]], [bbox[2], bbox[1]],
                                 [bbox[2], bbox[3]], [bbox[0], bbox[3]]],
                        "confidence": confidence,
                    })
        return extracted

    def _extract_rapidocr_with_positions(self, image, min_confidence: float) -> list[dict]:
        """RapidOCR로 텍스트 + 위치 추출"""
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
