"""
OCR (Optical Character Recognition) 서비스
슬라이드 이미지에서 텍스트 추출
RapidOCR 사용 (ONNX 기반, CPU 최적화)
"""
import io
from typing import Optional
import numpy as np


class OCRService:
    """
    텍스트 추출 서비스

    RapidOCR (ONNX 기반)
    - PaddleOCR 기반
    - CPU에서 빠른 추론
    - 한국어/영어 지원
    """

    def __init__(self):
        self.ocr = None
        self._load_model()

    def _load_model(self):
        """RapidOCR 초기화"""
        try:
            from rapidocr_onnxruntime import RapidOCR

            self.ocr = RapidOCR()
            print("[OCR] RapidOCR 초기화 완료")

        except ImportError:
            print("[OCR] RapidOCR이 설치되지 않았습니다")
            print("[OCR] pip install rapidocr-onnxruntime")

    def extract_texts(
        self,
        image: bytes | np.ndarray,
        min_confidence: float = 0.5,
    ) -> list[str]:
        """
        이미지에서 텍스트 추출

        Args:
            image: 이미지 바이트 또는 numpy 배열
            min_confidence: 최소 신뢰도 (0~1)

        Returns:
            추출된 텍스트 리스트
        """
        if self.ocr is None:
            return []

        try:
            # 이미지 준비
            if isinstance(image, bytes):
                image = self._bytes_to_array(image)

            # OCR 실행
            result, _ = self.ocr(image)

            if result is None:
                return []

            # 신뢰도 필터링 및 텍스트 추출
            texts = []
            for line in result:
                # line = [bbox, text, confidence]
                text = line[1]
                confidence = line[2]

                if confidence >= min_confidence:
                    texts.append(text)

            return texts

        except Exception as e:
            print(f"[OCR] 추출 오류: {e}")
            return []

    def extract_with_positions(
        self,
        image: bytes | np.ndarray,
        min_confidence: float = 0.5,
    ) -> list[dict]:
        """
        이미지에서 텍스트와 위치 정보 추출

        Args:
            image: 이미지 바이트 또는 numpy 배열
            min_confidence: 최소 신뢰도

        Returns:
            [{"text": str, "bbox": [[x1,y1], [x2,y2], ...], "confidence": float}, ...]
        """
        if self.ocr is None:
            return []

        try:
            if isinstance(image, bytes):
                image = self._bytes_to_array(image)

            result, _ = self.ocr(image)

            if result is None:
                return []

            extracted = []
            for line in result:
                bbox = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text = line[1]
                confidence = line[2]

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

    def _bytes_to_array(self, image_bytes: bytes) -> np.ndarray:
        """이미지 바이트를 numpy 배열로 변환"""
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            return np.array(img)

        except ImportError:
            raise RuntimeError("Pillow가 필요합니다: pip install Pillow")
