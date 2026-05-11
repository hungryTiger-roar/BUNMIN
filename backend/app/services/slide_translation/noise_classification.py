"""
OCR Region Noise Classification

OCR 영역의 노이즈 점수 계산 및 분류

분류 카테고리:
- translate_target: 번역 대상 (한글 포함)
- preserve_original: 원본 유지 (유효한 영문 텍스트)
- decorative_noise: 장식/노이즈 (배경, 깨진 텍스트 등)
- review_needed: 검토 필요 (불확실한 케이스)

입력: regions.normalized.json
출력:
- regions.classified.json
- excluded_noise_regions.json
"""
import re
from typing import Optional
from collections import Counter
from .config import cfg


# ============================================================
# 텍스트 분석 유틸리티
# ============================================================

def has_korean(text: str) -> bool:
    """한글 포함 여부"""
    return bool(re.search(r"[가-힣]", text))


def korean_char_count(text: str) -> int:
    """한글 글자 수"""
    return len(re.findall(r"[가-힣]", text))


def english_char_count(text: str) -> int:
    """영문 글자 수 (공백 제외)"""
    return len(re.findall(r"[a-zA-Z]", text))


def is_valid_english_word(text: str) -> bool:
    """유효한 영어 단어/약어인지 확인

    True 케이스:
    - NLP, CNN, RNN, HMM (대문자 약어)
    - Python, C++, Java (프로그래밍 언어)
    - 여러 단어로 구성된 기술 용어 (예: DATA PROCESSING)
    - word2vec, PyTorch (혼합 케이스)

    False 케이스:
    - GATATOTOTO (의미없는 문자열)
    - DEET EARNING (OCR 오류)
    - AGE PROCESSING (잘린 텍스트)
    """
    text = text.strip()
    if not text:
        return False

    # 알려진 기술 용어/약어 화이트리스트
    KNOWN_TERMS = {
        # 약어
        "NLP", "CNN", "RNN", "LSTM", "GRU", "HMM", "AI", "ML", "DL",
        "API", "QA", "GPU", "CPU", "OCR", "PDF", "URL", "HTTP", "HTTPS",
        "JSON", "XML", "HTML", "CSS", "SQL", "NoSQL",
        # 프로그래밍 언어
        "Python", "Java", "JavaScript", "C++", "C#", "Ruby", "Go", "Rust",
        "PHP", "Swift", "Kotlin", "TypeScript", "Scala",
        # 기술 용어
        "TensorFlow", "PyTorch", "Keras", "word2vec", "BERT", "GPT",
        "Transformer", "Attention", "Embedding",
        # 기관/플랫폼
        "Google", "Microsoft", "Amazon", "Facebook", "GitHub",
        # 일반 영어 단어 (단독 사용 가능)
        "Summary", "Reference", "Contents", "Index", "Chapter",
        "Application", "Introduction", "Conclusion", "Appendix",
        "Note", "Notice", "Warning", "Example", "Figure", "Table",
        "Source", "Output", "Input", "Data", "Model", "System",
        "Process", "Method", "Result", "Analysis", "Learning",
        "Deep", "Natural", "Language", "Processing", "Network",
    }

    # 텍스트를 단어로 분리해서 화이트리스트 체크
    words = text.split()

    # 단일 단어
    if len(words) == 1:
        word = words[0]
        # 정확히 화이트리스트에 있음
        if word in KNOWN_TERMS:
            return True
        # 대소문자 무시 매칭
        if word.upper() in [t.upper() for t in KNOWN_TERMS]:
            return True
        # 2-4자 대문자 약어 패턴 (NLP, API, GPU 등)
        if re.match(r'^[A-Z]{2,4}$', word):
            return True
        # 숫자 포함 약어 (word2vec, GPT-4 등)
        if re.match(r'^[A-Za-z]+[0-9]+[A-Za-z]*$', word):
            return True
        if re.match(r'^[A-Za-z]+-[0-9]+$', word):
            return True

    # 복수 단어 (구 체크)
    else:
        # 모든 단어가 화이트리스트에 있거나 일반 영단어면 유효
        valid_count = 0
        for word in words:
            if word in KNOWN_TERMS:
                valid_count += 1
            elif word.upper() in [t.upper() for t in KNOWN_TERMS]:
                valid_count += 1
            elif re.match(r'^[A-Z]{2,4}$', word):  # 대문자 약어
                valid_count += 1
            elif re.match(r'^[A-Za-z]{3,}$', word):  # 3자 이상 영단어
                valid_count += 1

        # 2/3 이상이 유효 단어면 전체적으로 유효
        if valid_count >= len(words) * 0.66:
            return True

    return False


def is_broken_or_garbled(text: str) -> bool:
    """깨진/garbled 텍스트인지 확인

    True 케이스:
    - AAABBBCCC (의미없는 반복)
    - 1010101010 (숫자 반복)
    - 앞부분이 잘린 텍스트 (1-3자 + 일반 단어)
    - 희귀한 자음 조합이 있는 텍스트
    """
    text = text.strip()
    if not text:
        return False

    # 1. 반복 패턴 감지
    # 같은 문자가 4번 이상 연속
    if re.search(r'(.)\1{3,}', text):
        return True

    # 같은 2글자가 3번 이상 반복
    if re.search(r'(.{2})\1{2,}', text):
        return True

    # 2. 숫자만 있는데 의미없는 긴 숫자열
    if re.match(r'^[0-9]{6,}$', text):
        # 날짜나 의미있는 숫자가 아니면 노이즈
        if not re.match(r'^\d{4}[-/]\d{2}[-/]\d{2}$', text):
            return True

    # 3. 잘린 영어 패턴
    # 먼저 유효한 구문인지 체크
    # Common valid multi-word phrases (domain-agnostic)
    VALID_PHRASES = {
        # General processing terms
        "DATA PROCESSING", "SIGNAL PROCESSING", "TEXT PROCESSING",
        "IMAGE PROCESSING", "BATCH PROCESSING", "PARALLEL PROCESSING",
        # Common tech phrases (add domain-specific phrases via config if needed)
    }
    text_upper = text.upper().strip()
    if text_upper in VALID_PHRASES:
        return False  # 유효한 구문이면 garbled 아님

    # Generic truncated text patterns (1-3 chars before common words)
    TRUNCATED_PATTERNS = [
        r'^[A-Z]{1,3}\s+PROCESSING$',      # truncated before PROCESSING
        r'^[A-Z]{1,3}\s+LEARNING$',        # truncated before LEARNING  
        r'^[A-Z]{1,3}\s+AND\s+[A-Z]{1,3}$', # truncated phrases with AND
    ]
    for pattern in TRUNCATED_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE):
            return True

    # 4. Generic garbled text detection (removed domain-specific patterns)
    # Instead of specific typo patterns, use heuristics:
    # - Uncommon consonant clusters
    # - Incomplete parenthetical expressions
    GARBLED_PATTERNS = [
        r'\(All\s+\w{2,6}$',  # truncated parenthetical like "(All ref"
        r'\([A-Za-z]{2,6}$',    # incomplete parenthetical
    ]
    text_lower = text.lower()
    for pattern in GARBLED_PATTERNS:
        if re.search(pattern, text_lower):
            return True

    # 5. 같은 대문자만 반복 (HIOIE, GATATOTOTO)
    text_upper_only = re.sub(r'[^A-Z]', '', text.upper())
    if len(text_upper_only) >= 5:
        # 고유 문자 비율이 너무 낮으면 노이즈
        unique_ratio = len(set(text_upper_only)) / len(text_upper_only)
        if unique_ratio < 0.4:  # 40% 미만 고유 문자
            return True

    return False


def is_footer_or_copyright(text: str, bbox: list, page_size: tuple) -> tuple[bool, str]:
    """Footer, copyright, 페이지 번호, 출처 텍스트인지 확인

    Args:
        text: 텍스트 내용
        bbox: [x1, y1, x2, y2] bounding box
        page_size: (width, height)

    Returns:
        (is_footer_like, reason)
    """
    text = text.strip()
    if not text:
        return False, ""

    text_lower = text.lower()
    page_w, page_h = page_size

    # bbox 위치 계산
    if bbox and len(bbox) >= 4 and page_h > 0:
        x1, y1, x2, y2 = bbox
        y_center = (y1 + y2) / 2
        y_ratio = y_center / page_h  # 0=상단, 1=하단

        # 하단 10% 영역 체크
        is_bottom = y_ratio > 0.9
        # 상단 10% 영역 체크
        is_top = y_ratio < 0.1
    else:
        is_bottom = False
        is_top = False

    # 1. Copyright 패턴
    COPYRIGHT_PATTERNS = [
        r'©',
        r'copyright',
        r'all rights reserved',
        r'\(c\)\s*\d{4}',
        r'copyrighted',
    ]
    for pattern in COPYRIGHT_PATTERNS:
        if re.search(pattern, text_lower):
            return True, "copyright_notice"

    # 2. 하단 페이지 번호 패턴
    if is_bottom:
        PAGE_NUMBER_PATTERNS = [
            r'^[0-9]{1,3}$',                    # 단순 숫자: 1, 23, 100
            r'^page\s*[0-9]+$',                 # page 1, page23
            r'^p\.?\s*[0-9]+$',                 # p.1, p 23
            r'^[0-9]+\s*/\s*[0-9]+$',           # 1/10, 23/50
            r'^-\s*[0-9]+\s*-$',                # -1-, -23-
            r'^[0-9]+페이지$',                  # 1페이지
            r'^\[\s*[0-9]+\s*\]$',              # [1], [23]
        ]
        for pattern in PAGE_NUMBER_PATTERNS:
            if re.match(pattern, text_lower):
                return True, "page_number"

    # 3. 출처/참조 패턴
    SOURCE_PATTERNS = [
        r'^source[:\s]',
        r'^ref[:\.\s]',
        r'^reference[:\s]',
        r'^출처[:\s]',
        r'^참고[:\s]',
        r'^자료[:\s]',
        r'^from\s+',
        r'image\s*source',
        r'data\s*source',
    ]
    for pattern in SOURCE_PATTERNS:
        if re.match(pattern, text_lower):
            return True, "source_reference"

    # 4. 하단/상단의 짧은 장식 텍스트 (5자 이하)
    if (is_bottom or is_top) and len(text) <= 5:
        # 유의미한 번호/기호는 제외
        if not re.match(r'^[0-9①②③④⑤⑥⑦⑧⑨⑩]+$', text):
            return True, "decorative_short_text"

    # 5. 회사/기관명 패턴 (하단)
    if is_bottom:
        COMPANY_PATTERNS = [
            r'inc\.?$',
            r'corp\.?$',
            r'ltd\.?$',
            r'llc\.?$',
            r'주식회사',
            r'(주)',
            r'\s+co\.$',
        ]
        for pattern in COMPANY_PATTERNS:
            if re.search(pattern, text_lower):
                return True, "company_footer"

    return False, ""


def is_small_label_or_decorative(
    text: str,
    bbox: list,
    page_size: tuple
) -> tuple[bool, str]:
    """작은 라벨/장식 요소인지 확인

    Args:
        text: 텍스트 내용
        bbox: [x1, y1, x2, y2]
        page_size: (width, height)

    Returns:
        (is_decorative, reason)
    """
    text = text.strip()
    if not text:
        return False, ""

    page_w, page_h = page_size

    if not bbox or len(bbox) < 4 or page_w <= 0 or page_h <= 0:
        return False, ""

    x1, y1, x2, y2 = bbox
    box_w = x2 - x1
    box_h = y2 - y1
    area = box_w * box_h
    page_area = page_w * page_h

    area_ratio = area / page_area if page_area > 0 else 0
    height_ratio = box_h / page_h if page_h > 0 else 0

    # 1. 매우 작은 영역 (페이지의 0.3% 미만 + 짧은 텍스트)
    if area_ratio < 0.003 and len(text) < 20:
        return True, "tiny_label"

    # 2. 높이가 매우 낮음 (0.5% 미만) + 한글 없음
    if height_ratio < 0.005 and not has_korean(text):
        return True, "flat_decorative"

    # 3. 코너 영역의 단일 문자/기호
    x_ratio = (x1 + x2) / 2 / page_w if page_w > 0 else 0.5
    is_corner = (
        (x_ratio < 0.1 or x_ratio > 0.9) and
        (y1 / page_h < 0.1 or y2 / page_h > 0.9)
    )
    if is_corner and len(text) <= 3:
        return True, "corner_decorative"

    return False, ""


def is_decorative_background(text: str, page_texts: list[str]) -> bool:
    """장식용 배경 텍스트인지 확인 (페이지 간 반복)

    슬라이드 템플릿의 반복되는 배경 요소:
    - 여러 페이지에 동일하게 반복되는 헤더/푸터 텍스트
    - 섹션 마커나 장식 텍스트
    - 페이지 장식 요소
    """
    text = text.strip()
    if not text:
        return False

    # 같은 텍스트가 여러 페이지에 나타나면 배경 요소
    count = sum(1 for pt in page_texts if pt.strip() == text)

    # 3번 이상 반복되면 배경 요소 가능성
    if count >= 3:
        # 하지만 유의미한 숫자(1, 2, 01, 02 등)나 불렛은 제외
        if re.match(r'^[0-9]{1,2}$', text):
            return False
        if re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]$', text):
            return False
        return True

    return False


# ============================================================
# 노이즈 점수 계산
# ============================================================

def calculate_noise_score(
    region: dict,
    page_texts: list[str],
    image_size: tuple[int, int]
) -> dict:
    """Region의 노이즈 점수 계산

    Returns:
        {
            "score": 0-100 (높을수록 노이즈),
            "factors": {factor_name: contribution},
            "reason": "주요 판단 근거"
        }
    """
    text = region.get("ocr_text", "").strip()
    confidence = region.get("confidence", 1.0)
    bbox = region.get("bbox", [0, 0, 0, 0])

    score = 0
    factors = {}
    reasons = []

    page_w, page_h = image_size

    # 1. 텍스트 내용 분석
    # ---------------------------------------------

    # 1a. 깨진/garbled 텍스트: +50
    if is_broken_or_garbled(text):
        factors["broken_garbled"] = 50
        score += 50
        reasons.append("broken_or_garbled_text")

    # 1b. 장식 배경 텍스트: +40
    if is_decorative_background(text, page_texts):
        factors["decorative_background"] = 40
        score += 40
        reasons.append("decorative_background")

    # 1c. 영어만 있는데 유효하지 않음: +30
    if not has_korean(text) and english_char_count(text) > 0:
        if not is_valid_english_word(text):
            factors["invalid_english"] = 30
            score += 30
            reasons.append("invalid_english_only")

    # 1d. 너무 짧은 텍스트 (1-2자): +15
    text_len = len(text.replace(" ", ""))
    if text_len <= 2:
        # 하지만 의미있는 번호/기호는 제외
        if not re.match(r'^[0-9①②③④⑤⑥⑦⑧⑨⑩]$', text):
            factors["too_short"] = 15
            score += 15
            reasons.append("too_short_text")

    # 1e. Footer/Copyright/페이지번호/출처: +45 (번역 대상 아님)
    is_footer, footer_reason = is_footer_or_copyright(text, bbox, image_size)
    if is_footer:
        factors["footer_copyright"] = 45
        score += 45
        reasons.append(f"footer_copyright:{footer_reason}")

    # 1f. 작은 라벨/장식 요소: +35
    is_decorative, decorative_reason = is_small_label_or_decorative(text, bbox, image_size)
    if is_decorative:
        factors["small_decorative"] = 35
        score += 35
        reasons.append(f"small_decorative:{decorative_reason}")

    # 2. 위치 분석
    # ---------------------------------------------

    if bbox and page_h > 0 and page_w > 0:
        x1, y1, x2, y2 = bbox
        region_h = y2 - y1
        region_w = x2 - x1

        # 2a. 매우 작은 영역: +20
        height_ratio = region_h / page_h
        if height_ratio < 0.01:  # 페이지 높이의 1% 미만
            factors["tiny_region"] = 20
            score += 20
            reasons.append("tiny_region")

        # 2b. 페이지 가장자리 (상단/하단 5%): +10
        if y1 / page_h < 0.05 or y2 / page_h > 0.95:
            factors["edge_position"] = 10
            score += 10
            reasons.append("edge_position")

    # 3. OCR 신뢰도
    # ---------------------------------------------

    # 3a. 낮은 신뢰도: +20
    if confidence < 0.6:
        factors["low_confidence"] = 20
        score += 20
        reasons.append(f"low_confidence_{confidence:.2f}")
    elif confidence < 0.7:
        factors["low_confidence"] = 10
        score += 10
        reasons.append(f"medium_confidence_{confidence:.2f}")

    # 4. 한글 포함 시 점수 감소 (번역 대상)
    # ---------------------------------------------

    if has_korean(text):
        korean_count = korean_char_count(text)
        if korean_count >= 3:
            factors["korean_content"] = -30
            score -= 30
            reasons.append(f"korean_content_{korean_count}chars")
        elif korean_count >= 1:
            factors["korean_content"] = -15
            score -= 15
            reasons.append(f"korean_content_{korean_count}chars")

    # 점수 범위 제한
    score = max(0, min(100, score))

    return {
        "score": score,
        "factors": factors,
        "reasons": reasons,
        "primary_reason": reasons[0] if reasons else "none"
    }


# ============================================================
# 분류 결정
# ============================================================

def classify_region(
    region: dict,
    noise_info: dict
) -> str:
    """Region을 카테고리로 분류

    Returns:
        "translate_target" | "preserve_original" | "decorative_noise" | "review_needed"
    """
    text = region.get("ocr_text", "").strip()
    score = noise_info.get("score", 0)

    # 1. 한글 포함 → 번역 대상 (노이즈 점수 무시)
    if has_korean(text):
        # 단, 노이즈 점수가 매우 높으면 검토 필요
        if score >= 70:
            return "review_needed"
        return "translate_target"

    # 2. 영어만 있는 경우
    if english_char_count(text) > 0:
        # 노이즈 점수 높음 → decorative_noise
        if score >= 50:
            return "decorative_noise"

        # 유효한 영어 → preserve_original
        if is_valid_english_word(text):
            return "preserve_original"

        # 애매함 → review_needed
        if score >= 30:
            return "review_needed"

        # 낮은 노이즈 점수 → preserve_original
        return "preserve_original"

    # 3. 숫자/기호만
    # 의미있는 번호 → preserve_original
    if re.match(r'^[0-9]{1,3}$', text) or re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]$', text):
        return "preserve_original"

    # 기타 기호 → decorative_noise
    if score >= 30:
        return "decorative_noise"

    return "preserve_original"


# ============================================================
# 메인 분류 함수
# ============================================================

def classify_ocr_regions(
    regions: list[dict],
    image_size: tuple[int, int],
    all_page_texts: Optional[list[str]] = None
) -> tuple[list[dict], list[dict]]:
    """모든 OCR 영역을 분류

    Args:
        regions: 정규화된 OCR 영역들
        image_size: (width, height)
        all_page_texts: 전체 페이지의 모든 텍스트 (배경 감지용)

    Returns:
        (classified_regions, excluded_regions)
    """
    if all_page_texts is None:
        all_page_texts = [r.get("ocr_text", "") for r in regions]

    classified = []
    excluded = []

    for region in regions:
        # 노이즈 점수 계산
        noise_info = calculate_noise_score(region, all_page_texts, image_size)

        # 분류 결정
        classification = classify_region(region, noise_info)

        # 정보 추가
        region["_noise_score"] = noise_info["score"]
        region["_noise_factors"] = noise_info["factors"]
        region["_noise_reasons"] = noise_info["reasons"]
        region["_classification"] = classification

        # 분류별 처리
        if classification == "decorative_noise":
            region["_skip_reason"] = f"decorative_noise:{noise_info['primary_reason']}"
            excluded.append(region)
        else:
            classified.append(region)

    return classified, excluded


def classify_all_pages_regions(
    pages_regions: dict[int, list[dict]],
    page_sizes: dict[int, tuple[int, int]]
) -> tuple[dict[int, list[dict]], list[dict]]:
    """모든 페이지의 OCR 영역을 분류

    Args:
        pages_regions: {page_no: [regions]} 형태
        page_sizes: {page_no: (width, height)} 형태

    Returns:
        (classified_pages_regions, all_excluded_regions)
    """
    # 전체 텍스트 수집 (배경 패턴 감지용)
    all_texts = []
    for page_regions in pages_regions.values():
        for r in page_regions:
            all_texts.append(r.get("ocr_text", ""))

    classified_pages = {}
    all_excluded = []

    for page_no, regions in pages_regions.items():
        image_size = page_sizes.get(page_no, (1920, 1080))
        classified, excluded = classify_ocr_regions(regions, image_size, all_texts)

        # 페이지 번호 추가
        for r in excluded:
            r["page_no"] = page_no

        classified_pages[page_no] = classified
        all_excluded.extend(excluded)

    return classified_pages, all_excluded


# ============================================================
# 분류 통계
# ============================================================

def get_classification_stats(regions: list[dict]) -> dict:
    """분류 통계 생성"""
    stats = {
        "total": len(regions),
        "by_classification": Counter(),
        "by_reason": Counter(),
    }

    for r in regions:
        classification = r.get("_classification", "unknown")
        stats["by_classification"][classification] += 1

        for reason in r.get("_noise_reasons", []):
            stats["by_reason"][reason] += 1

    return stats


# ============================================================
# 저장 함수
# ============================================================

def save_classified_regions_with_noise(
    regions: list[dict],
    output_path: str
):
    """분류된 영역 저장"""
    import json

    stats = get_classification_stats(regions)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "regions": regions,
            "count": len(regions),
            "classification_stats": {
                "by_classification": dict(stats["by_classification"]),
                "by_reason": dict(stats["by_reason"]),
            }
        }, f, ensure_ascii=False, indent=2)


def save_excluded_noise_regions(
    excluded: list[dict],
    output_path: str
):
    """제외된 노이즈 영역 저장 (추적용)"""
    import json

    # 제외 사유별 그룹핑
    by_reason = {}
    for r in excluded:
        reason = r.get("_skip_reason", "unknown")
        if reason not in by_reason:
            by_reason[reason] = []
        by_reason[reason].append({
            "page_no": r.get("page_no"),
            "text": r.get("ocr_text", ""),
            "bbox": r.get("bbox"),
            "noise_score": r.get("_noise_score"),
            "noise_factors": r.get("_noise_factors"),
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_excluded": len(excluded),
            "by_reason": by_reason,
            "excluded_regions": [
                {
                    "page_no": r.get("page_no"),
                    "text": r.get("ocr_text", ""),
                    "bbox": r.get("bbox"),
                    "classification": r.get("_classification"),
                    "skip_reason": r.get("_skip_reason"),
                    "noise_score": r.get("_noise_score"),
                    "noise_factors": r.get("_noise_factors"),
                }
                for r in excluded
            ]
        }, f, ensure_ascii=False, indent=2)
