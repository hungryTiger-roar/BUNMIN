"""
Image Text Extraction (Phase 1)

이미지 영역 감지 및 이미지 내 텍스트 추출

입력: 페이지 이미지 + OCR regions
출력: image_regions.json + image_texts.raw.json

Enhanced OCR:
- 색상 배경 텍스트 감지 개선
- 확대 + contrast + threshold 전처리 후 재시도
"""
import re
from typing import Optional, Any, Union
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from .config import cfg


# ============================================================
# Enhanced OCR Preprocessing for Colored Backgrounds
# ============================================================

def preprocess_for_ocr(crop: np.ndarray, scale: float = 2.5) -> list[np.ndarray]:
    """색상 배경 텍스트 감지를 위한 전처리

    Args:
        crop: 원본 crop 이미지 (numpy array, RGB)
        scale: 확대 비율 (기본 2.5배)

    Returns:
        전처리된 이미지들 (여러 버전 시도)
    """
    try:
        import cv2
    except ImportError:
        return [crop]

    pil_img = Image.fromarray(crop)
    h, w = crop.shape[:2]
    new_size = (int(w * scale), int(h * scale))

    processed = []

    # 1. 확대 + contrast 증가
    enlarged = pil_img.resize(new_size, Image.Resampling.LANCZOS)
    enhanced = ImageEnhance.Contrast(enlarged).enhance(1.5)
    processed.append(np.array(enhanced))

    # 2. 확대 + grayscale + threshold (adaptive)
    gray = enlarged.convert('L')
    gray_np = np.array(gray)
    # Adaptive threshold
    thresh = cv2.adaptiveThreshold(
        gray_np, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    # 3채널로 변환 (OCR 호환)
    thresh_rgb = cv2.cvtColor(thresh, cv2.COLOR_GRAY2RGB)
    processed.append(thresh_rgb)

    # 3. 확대 + 색상 반전 (밝은 배경에 어두운 텍스트로)
    inverted = np.array(ImageEnhance.Contrast(enlarged).enhance(1.8))
    # 밝은 색상 배경을 흰색으로, 어두운 텍스트를 검정으로
    hsv = cv2.cvtColor(inverted, cv2.COLOR_RGB2HSV)
    # 채도가 높은 부분(색상 배경)을 흰색으로
    saturation_mask = hsv[:, :, 1] > 30
    inverted[saturation_mask] = [255, 255, 255]
    processed.append(inverted)

    # 4. 확대 + sharpen + contrast
    sharpened = enlarged.filter(ImageFilter.SHARPEN)
    sharp_contrast = ImageEnhance.Contrast(sharpened).enhance(1.6)
    processed.append(np.array(sharp_contrast))

    return processed


def extract_text_with_enhanced_ocr(
    crop: np.ndarray,
    ocr_service=None,
    enable_retry: bool = True
) -> list[dict]:
    """전처리 + 재시도를 포함한 향상된 텍스트 추출

    Args:
        crop: 이미지 crop
        ocr_service: OCR 서비스 인스턴스
        enable_retry: 실패 시 전처리 후 재시도 여부

    Returns:
        추출된 텍스트 리스트
    """
    # 1차 시도: 원본 crop으로 OCR
    results = _run_ocr_on_image(crop, ocr_service)

    # 한글이 감지되면 바로 반환
    if any(has_korean(r.get("text", "")) for r in results):
        return results

    # 재시도 비활성화면 원본 결과 반환
    if not enable_retry:
        return results

    # 2차 시도: 전처리된 이미지들로 OCR 재시도
    print("[ImageText] 한글 미감지, 전처리 후 재시도...")

    preprocessed_images = preprocess_for_ocr(crop)

    for idx, processed_img in enumerate(preprocessed_images):
        retry_results = _run_ocr_on_image(processed_img, ocr_service)

        # 한글이 감지되면 좌표 역변환 후 반환
        korean_results = [r for r in retry_results if has_korean(r.get("text", ""))]
        if korean_results:
            print(f"[ImageText] 전처리 버전 {idx+1}에서 한글 {len(korean_results)}개 감지")
            # bbox 좌표를 원본 크기로 역변환
            scale = processed_img.shape[1] / crop.shape[1]
            for r in korean_results:
                if r.get("bbox"):
                    r["bbox"] = [int(v / scale) for v in r["bbox"]]
            return korean_results

    print("[ImageText] 전처리 후에도 한글 미감지")
    return results


def _run_ocr_on_image(image: np.ndarray, ocr_service=None) -> list[dict]:
    """이미지에 OCR 수행"""
    try:
        if ocr_service is None:
            from app.services.ocr_service import OCRService
            ocr_service = OCRService()

        if ocr_service.mode != "surya" or not hasattr(ocr_service, 'det_predictor'):
            return []

        results = ocr_service.extract_with_positions(image, min_confidence=0.3)

        extracted = []
        for r in results:
            bbox = r.get("bbox")
            if bbox:
                if isinstance(bbox, list) and len(bbox) == 4:
                    if isinstance(bbox[0], list):
                        xs = [p[0] for p in bbox]
                        ys = [p[1] for p in bbox]
                        bbox = [min(xs), min(ys), max(xs), max(ys)]

                extracted.append({
                    "text": r.get("text", ""),
                    "bbox": bbox,
                    "confidence": r.get("confidence", 1.0)
                })

        return extracted
    except Exception as e:
        print(f"[ImageText] OCR 오류: {e}")
        return []


def to_numpy(image: Any) -> np.ndarray:
    """PIL Image 또는 numpy array를 numpy array로 변환"""
    if isinstance(image, np.ndarray):
        return image
    elif isinstance(image, Image.Image):
        return np.array(image)
    else:
        raise ValueError(f"지원하지 않는 이미지 타입: {type(image)}")


def detect_image_regions(
    page_image: Union[np.ndarray, Image.Image],
    ocr_regions: list[dict],
    pdf_page=None
) -> list[dict]:
    """이미지 영역 감지 (2단계 접근)

    Args:
        page_image: 페이지 이미지 (numpy array 또는 PIL Image)
        ocr_regions: OCR로 추출한 텍스트 영역들
        pdf_page: PDF 페이지 객체 (있으면 PDF 객체 기반 감지)

    Returns:
        이미지 영역 정보 리스트
    """
    # PIL Image -> numpy array 변환
    page_image = to_numpy(page_image)

    image_regions = []
    region_id = 0

    # 방법 1: PDF 객체 기반 감지 (우선)
    if pdf_page is not None:
        pdf_images = extract_pdf_image_objects(pdf_page)
        for img_obj in pdf_images:
            image_regions.append({
                "id": f"img_{region_id:03d}",
                "bbox": img_obj["bbox"],
                "type": classify_image_type(page_image, img_obj["bbox"]),
                "detection_method": "pdf_object"
            })
            region_id += 1

    # 방법 2: 컨투어 기반 감지 (PDF 객체로 못 찾은 영역)
    existing_bboxes = [r["bbox"] for r in image_regions]
    contour_regions = detect_image_regions_by_contour(
        page_image, ocr_regions, existing_bboxes
    )

    for bbox in contour_regions:
        image_regions.append({
            "id": f"img_{region_id:03d}",
            "bbox": bbox,
            "type": classify_image_type(page_image, bbox),
            "detection_method": "contour"
        })
        region_id += 1

    return image_regions


def extract_pdf_image_objects(pdf_page) -> list[dict]:
    """PDF 페이지에서 이미지 객체 추출"""
    images = []
    try:
        # PyMuPDF (fitz) 사용 시
        for img in pdf_page.get_images():
            xref = img[0]
            rect = pdf_page.get_image_rects(xref)
            if rect:
                r = rect[0]
                images.append({
                    "bbox": [int(r.x0), int(r.y0), int(r.x1), int(r.y1)],
                    "xref": xref
                })
    except Exception:
        pass
    return images


def detect_image_regions_by_contour(
    page_image: np.ndarray,
    ocr_regions: list[dict],
    existing_bboxes: list
) -> list[list]:
    """컨투어 기반 이미지 영역 감지 + 다이어그램 박스 감지"""
    try:
        import cv2
    except ImportError:
        return []

    detected = []
    h, w = page_image.shape[:2]

    # 1. 색상 기반 다이어그램 박스 감지 (작은 라벨 박스)
    diagram_boxes = detect_colored_diagram_boxes(page_image, ocr_regions)
    detected.extend(diagram_boxes)

    # 2. OCR 텍스트 영역을 마스킹
    mask = np.ones((h, w), dtype=np.uint8) * 255

    for region in ocr_regions:
        bbox = region.get("bbox")
        if bbox and len(bbox) == 4:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            cv2.rectangle(mask, (x1, y1), (x2, y2), 0, -1)

    # 기존 이미지 영역도 마스킹
    for bbox in existing_bboxes + detected:
        if bbox and len(bbox) == 4:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            cv2.rectangle(mask, (x1, y1), (x2, y2), 0, -1)

    # 3. 컨투어 찾기 (큰 이미지 영역)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = cfg("image_text.detection_min_area", 10000)

    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cw * ch

        # 전체 페이지 크기의 영역은 스킵 (너무 큼)
        if cw > w * 0.9 and ch > h * 0.9:
            continue

        if area >= min_area:
            bbox = [x, y, x + cw, y + ch]
            if not overlaps_any(bbox, existing_bboxes + detected, threshold=0.5):
                detected.append(bbox)

    return detected


def detect_colored_diagram_boxes(
    page_image: np.ndarray,
    ocr_regions: list[dict]
) -> list[list]:
    """색상이 있는 다이어그램 박스 감지 (라벨이 포함된 박스)

    다이어그램의 파란색/청록색/회색 등 배경색이 있는 박스를 찾아
    그 안의 텍스트를 추출할 수 있도록 함
    """
    try:
        import cv2
    except ImportError:
        return []

    detected = []
    h, w = page_image.shape[:2]

    # HSV 변환
    if len(page_image.shape) == 2:
        return []  # 그레이스케일이면 스킵

    hsv = cv2.cvtColor(page_image, cv2.COLOR_RGB2HSV)

    # 여러 색상 범위에서 박스 찾기 (높은 채도로 명확한 박스만)
    color_ranges = [
        # 청록색/시안 계열 - 높은 채도 (명확한 박스)
        ((80, 40, 140), (110, 255, 255)),
        # 하늘색/밝은 파란색 - 높은 채도
        ((95, 40, 150), (115, 255, 255)),
        # 파란색 계열
        ((100, 40, 120), (130, 255, 255)),
        # 초록색 계열
        ((35, 40, 120), (85, 255, 255)),
        # 연한 민트/청록 - 중간 채도
        ((75, 30, 180), (100, 200, 255)),
    ]

    # OCR 영역 bbox 수집 (겹침 체크용)
    ocr_bboxes = [r.get("bbox") for r in ocr_regions if r.get("bbox")]

    for lower, upper in color_ranges:
        lower = np.array(lower)
        upper = np.array(upper)

        # 색상 마스크
        mask = cv2.inRange(hsv, lower, upper)

        # 모폴로지 연산 - 작은 커널로 박스 분리 유지
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        # 컨투어 찾기
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            area = cw * ch

            # 다이어그램 박스 크기 필터 (더 작은 박스도 허용)
            # 최소 500px², 최대 페이지의 25%
            if area < 500 or area > (w * h * 0.25):
                continue

            # 최소 크기 (가로 또는 세로가 너무 작으면 스킵)
            if cw < 30 or ch < 15:
                continue

            # 극단적 비율만 스킵 (화살표 형태 등 다양한 모양 허용)
            aspect_ratio = cw / ch if ch > 0 else 0
            if aspect_ratio < 0.2 or aspect_ratio > 15:
                continue

            bbox = [x, y, x + cw, y + ch]

            # OCR 영역과 완전히 겹치면 스킵 (이미 OCR로 처리됨)
            if overlaps_any(bbox, ocr_bboxes, threshold=0.85):
                continue

            # 기존 감지 영역과 겹치면 스킵
            if overlaps_any(bbox, detected, threshold=0.5):
                continue

            detected.append(bbox)

    return detected


def classify_image_type(page_image: np.ndarray, bbox: list) -> str:
    """이미지 타입 분류"""
    x1, y1, x2, y2 = [int(v) for v in bbox]

    # 범위 체크
    h, w = page_image.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return "unknown"

    crop = page_image[y1:y2, x1:x2]

    # 간단한 휴리스틱 (추후 개선 가능)
    if has_chart_pattern(crop):
        return "chart"
    if has_diagram_pattern(crop):
        return "diagram"
    if has_table_pattern(crop):
        return "table_image"

    return "unknown"


def has_chart_pattern(crop: np.ndarray) -> bool:
    """차트 패턴 감지 (간단한 휴리스틱)"""
    # 색상 다양성이 낮고, 직선이 많으면 차트
    try:
        import cv2
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 50, minLineLength=30, maxLineGap=10)
        return lines is not None and len(lines) > 5
    except Exception:
        return False


def has_diagram_pattern(crop: np.ndarray) -> bool:
    """다이어그램 패턴 감지"""
    # 도형(사각형, 원)이 많으면 다이어그램
    return False  # 추후 구현


def has_table_pattern(crop: np.ndarray) -> bool:
    """표 패턴 감지"""
    # 격자 구조가 있으면 표
    return False  # 추후 구현


def overlaps_any(bbox: list, existing: list, threshold: float = 0.5) -> bool:
    """기존 bbox들과 겹치는지 확인"""
    for existing_bbox in existing:
        if calculate_overlap_ratio(bbox, existing_bbox) >= threshold:
            return True
    return False


def calculate_overlap_ratio(bbox1: list, bbox2: list) -> float:
    """두 bbox의 겹침 비율 계산"""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])

    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])

    if area1 == 0 or area2 == 0:
        return 0.0

    return intersection / min(area1, area2)


def extract_image_texts(
    image_region: dict,
    page_image: Union[np.ndarray, Image.Image],
    page_no: int = 1
) -> list[dict]:
    """이미지 영역에서 텍스트 추출 (OCR)

    Args:
        image_region: 이미지 영역 정보
        page_image: 페이지 전체 이미지 (numpy array 또는 PIL Image)
        page_no: 페이지 번호

    Returns:
        이미지 내 텍스트 정보 리스트
    """
    # PIL Image -> numpy array 변환
    page_image = to_numpy(page_image)

    bbox = image_region["bbox"]
    x1, y1, x2, y2 = [int(v) for v in bbox]

    # 범위 체크
    h, w = page_image.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return []

    crop = page_image[y1:y2, x1:x2]

    # OCR로 텍스트 추출
    ocr_results = extract_text_from_crop(crop)

    texts = []
    for i, item in enumerate(ocr_results):
        # 한글이 있는 것만 추출
        if not has_korean(item.get("text", "")):
            continue

        local_bbox = item["bbox"]
        page_bbox = convert_to_page_bbox(local_bbox, bbox)

        texts.append({
            "id": f"{image_region['id']}_t{i:02d}",
            "parent_image_region_id": image_region["id"],
            "page_no": page_no,
            "text": item["text"],
            "text_ocr_raw": item["text"],
            "bbox_local": local_bbox,
            "bbox_page": page_bbox,
            "confidence": item.get("confidence", 1.0),
            "type": "label",
            "source": "image_text"
        })

    return texts


def extract_text_from_crop(crop: np.ndarray, ocr_service=None) -> list[dict]:
    """이미지 crop에서 텍스트 추출

    Step 1-2에서는 1차 OCR만 수행 (Enhanced OCR 재시도 비활성화)
    Enhanced OCR은 Step 4-4 (최종 이미지 잔존 한글 재처리)에서만 사용

    Args:
        crop: 이미지 crop (numpy array)
        ocr_service: OCRService 인스턴스 (None이면 생성 시도)

    Returns:
        추출된 텍스트 리스트
    """
    # 1차 OCR만 수행 (Enhanced OCR 재시도 비활성화)
    # Enhanced OCR은 Step 4-4 최종 잔존 한글 bbox 재처리에서만 사용
    return extract_text_with_enhanced_ocr(crop, ocr_service, enable_retry=False)


def convert_to_page_bbox(local_bbox: list, parent_bbox: list) -> list:
    """로컬 좌표를 페이지 절대 좌표로 변환"""
    x1, y1, x2, y2 = local_bbox
    px1, py1 = parent_bbox[0], parent_bbox[1]

    return [
        px1 + x1,
        py1 + y1,
        px1 + x2,
        py1 + y2
    ]


def has_korean(text: str) -> bool:
    """한글 포함 여부"""
    return bool(re.search(r"[가-힣]", text))


def save_image_regions(regions: list[dict], output_path: str):
    """이미지 영역 정보 저장"""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "image_regions": regions,
            "count": len(regions)
        }, f, ensure_ascii=False, indent=2)


def save_image_texts(texts: list[dict], output_path: str):
    """이미지 텍스트 정보 저장"""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "image_texts": texts,
            "count": len(texts)
        }, f, ensure_ascii=False, indent=2)
