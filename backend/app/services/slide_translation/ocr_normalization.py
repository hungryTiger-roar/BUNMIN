"""
OCR Normalization 단계

입력: OCR 원본 결과 (regions.raw.json)
출력: 정규화된 결과 (regions.normalized.json)

처리 항목:
1. 텍스트 정규화 (공백, 유니코드)
2. Low confidence 처리 (skip 대신 flag)
3. 작은 영역 처리
4. 빈 텍스트 제거
"""
import re
import unicodedata
from typing import Optional
from .config import cfg


def normalize_text(text: str) -> str:
    """텍스트 정규화"""
    # 1. 연속 공백 → 단일 공백
    text = re.sub(r"\s+", " ", text)

    # 2. 유니코드 정규화
    text = unicodedata.normalize("NFC", text)

    # 3. 단독 세로선 기호 보정
    if text.strip() in ["ㅣ", "｜", "丨"]:
        text = "|"

    # 4. 앞뒤 공백 제거
    text = text.strip()

    return text


def korean_char_count(text: str) -> int:
    """한글 글자 수 반환"""
    return len(re.findall(r"[가-힣]", text))


def has_korean(text: str) -> bool:
    """한글 포함 여부"""
    return bool(re.search(r"[가-힣]", text))


def is_isolated_symbol(text: str) -> bool:
    """고립된 기호인지 판단"""
    # 한글/영문/숫자 제외하고 남은 것만 있으면 기호
    cleaned = re.sub(r"[가-힣a-zA-Z0-9\s]", "", text)
    text_cleaned = re.sub(r"\s", "", text)
    return len(cleaned) == len(text_cleaned) and len(text_cleaned) <= 2


def is_meaningful_number_or_label(text: str) -> bool:
    """의미 있는 번호/라벨인지 판단"""
    # 1, 2, A, B, 01, (1), 1., 1) 등
    patterns = [
        r"^\d{1,3}$",  # 숫자만
        r"^[A-Za-z]$",  # 알파벳 하나
        r"^\(\d+\)$",  # (1), (2)
        r"^\d+[\.\)]$",  # 1., 1)
        r"^[①②③④⑤⑥⑦⑧⑨⑩]$",  # 동그라미 숫자
    ]
    return any(re.match(p, text.strip()) for p in patterns)


def should_skip_low_confidence(
    region: dict,
    text: str,
    glossary: Optional[dict] = None
) -> bool:
    """low confidence 영역 skip 여부 판단 (정규화된 text 기준)"""
    # 1. glossary 후보면 keep
    if glossary and is_glossary_candidate(text, glossary):
        return False

    # 2. 한글 글자 2자 이상이면 keep
    if korean_char_count(text) >= cfg("ocr.min_korean_chars", 2):
        return False

    # 3. 의미 있는 번호/라벨이면 keep
    if is_meaningful_number_or_label(text):
        return False

    # 4. isolated symbol이면 skip
    if is_isolated_symbol(text):
        return True

    # 5. 나머지는 flag만 하고 keep
    return False


def is_glossary_candidate(text: str, glossary: dict) -> bool:
    """glossary 후보인지 확인"""
    for section in ["proper_nouns", "organizations", "terms"]:
        if text in glossary.get(section, {}):
            return True
    return False


def is_meaningful_small_region(region: dict, text: str) -> bool:
    """작은 영역이지만 의미 있는지 판단 (정규화된 text 기준)"""
    # 1. 번호/라벨
    if is_meaningful_number_or_label(text):
        return True

    # 2. 한글 글자 2자 이상
    if korean_char_count(text) >= cfg("ocr.min_korean_chars", 2):
        return True

    # 3. isolated symbol은 제거
    if is_isolated_symbol(text):
        return False

    return False


def normalize_ocr_regions(
    regions: list[dict],
    image_size: tuple[int, int],
    glossary: Optional[dict] = None
) -> list[dict]:
    """OCR 정규화 (normalize_text를 먼저 적용)

    Args:
        regions: OCR 원본 결과 리스트
        image_size: (width, height)
        glossary: 기존 glossary (있으면 skip 판단에 사용)

    Returns:
        정규화된 region 리스트
    """
    normalized = []
    page_w, page_h = image_size

    for region in regions:
        # 텍스트 정규화를 먼저 적용
        raw_text = region.get("text", region.get("ocr_text", ""))
        text = normalize_text(raw_text)

        # 원본 보존 + 정규화 결과 저장
        region["ocr_text_raw"] = raw_text
        region["ocr_text"] = text
        region["_quality_flags"] = []

        confidence = region.get("confidence", 1.0)

        # bbox 정규화 (다양한 형식 지원)
        bbox = normalize_bbox(region.get("bbox"))
        if bbox:
            region["bbox"] = bbox
            h = bbox[3] - bbox[1]
        else:
            h = 0

        # 1. confidence 체크
        min_conf = cfg("ocr.min_confidence", 0.60)
        if confidence < min_conf:
            region["_quality_flags"].append("low_confidence")
            region["_low_confidence"] = True

            if should_skip_low_confidence(region, text, glossary):
                region["_skip_reason"] = "low_confidence_noise"
                continue

        # 2. 너무 작은 영역 체크
        min_height_ratio = cfg("ocr.min_text_height_ratio", 0.006)
        if page_h > 0 and h / page_h < min_height_ratio:
            if not is_meaningful_small_region(region, text):
                region["_skip_reason"] = "too_small_noise"
                continue

        # 3. 빈 텍스트 체크
        if not text.strip():
            region["_skip_reason"] = "empty_text"
            continue

        normalized.append(region)

    return normalized


def normalize_bbox(bbox) -> Optional[list]:
    """다양한 bbox 형식을 [x1, y1, x2, y2]로 정규화"""
    if bbox is None:
        return None

    # 이미 [x1, y1, x2, y2] 형식
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        if all(isinstance(x, (int, float)) for x in bbox):
            return list(bbox)

    # [[x1,y1], [x2,y1], [x2,y2], [x1,y2]] 형식 (4점)
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        if all(isinstance(p, (list, tuple)) and len(p) == 2 for p in bbox):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            return [min(xs), min(ys), max(xs), max(ys)]

    return None


def save_normalized_regions(regions: list[dict], output_path: str):
    """정규화 결과 저장"""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "regions": regions,
            "count": len(regions),
            "skipped_count": sum(1 for r in regions if "_skip_reason" in r)
        }, f, ensure_ascii=False, indent=2)


def load_raw_regions(input_path: str) -> list[dict]:
    """OCR 원본 결과 로드"""
    import json
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "regions" in data:
        return data["regions"]
    return []
