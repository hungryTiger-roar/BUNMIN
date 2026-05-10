"""
Region Type Classification

OCR region 타입 분류 (점수 기반)

입력:
- regions.deduplicated.json

출력:
- regions.classified.json

타입 목록:
- title, subtitle, paragraph
- bullet_head, bullet_continuation, bullet_candidate
- table_cell, diagram_label
- footer, copyright, page_number, affiliation, person_name
- list_number, section_number
- code, formula, url
- mixed
"""
import re
import unicodedata
from typing import Optional
from .config import cfg


# 상수 리스트 (점수 기반 분류에서 사용)
REGION_TYPES = [
    "title", "subtitle", "paragraph",
    "bullet_head", "bullet_continuation", "bullet_candidate",
    "table_cell", "diagram_label",
    "footer", "copyright", "page_number", "affiliation", "person_name",
    "list_number", "section_number",
    "code", "formula", "url",
    "mixed"
]


def classify_region_type_scored(
    region: dict,
    image_size: tuple[int, int],
    all_regions: list[dict],
    glossary: Optional[dict] = None,
    image=None
) -> str:
    """점수 기반 타입 분류 (후보도 저장)"""
    scores = {type_: 0 for type_ in REGION_TYPES}
    reasons = []

    text = region.get("ocr_text", "")
    bbox = region.get("bbox", [0, 0, 0, 0])
    page_w, page_h = image_size

    # 1. 위치 기반 점수
    y_ratio = bbox[1] / page_h if page_h > 0 else 0
    height_ratio = (bbox[3] - bbox[1]) / page_h if page_h > 0 else 0

    # 상단이면 title 가능성
    if y_ratio < 0.15 and height_ratio > 0.03:
        scores["title"] += 3
        reasons.append("position_top")

    # 하단이면 footer 가능성
    if y_ratio > 0.85:
        scores["footer"] += 3
        reasons.append("position_bottom")

    # 2. 텍스트 기반 점수 (prefix hint score 사용)
    prefix_score = get_prefix_hint_score(text)
    if prefix_score > 0:
        scores["bullet_head"] += prefix_score
        reasons.append(f"prefix_hint_score={prefix_score}")

    if is_copyright_text(text):
        scores["copyright"] += 5
        reasons.append("copyright_pattern")

    if is_page_number(text):
        scores["page_number"] += 5
        reasons.append("page_number_pattern")

    if is_section_number(text):
        scores["section_number"] += 4
        reasons.append("section_number_pattern")

    if is_url(text):
        scores["url"] += 5
        reasons.append("url_pattern")

    if is_code_like(text):
        scores["code"] += 4
        reasons.append("code_pattern")

    # 3. bullet layout 기반 점수 반영
    bullet_type, bullet_score = detect_bullet_by_layout(region, all_regions, image)
    if bullet_type == "bullet_head":
        scores["bullet_head"] += bullet_score
        reasons.append(f"bullet_layout_score={bullet_score}")
    elif bullet_type == "bullet_candidate":
        scores["bullet_candidate"] += bullet_score
        reasons.append(f"bullet_candidate_score={bullet_score}")

    # 4. glossary 매칭 (사람 이름)
    if glossary and text_matches_glossary(text, glossary, "proper_nouns"):
        scores["person_name"] += 4
        reasons.append("glossary_proper_noun")

    # 후보 리스트 생성 (점수 높은 순)
    candidates = sorted(
        [{"type": t, "score": s} for t, s in scores.items() if s > 0],
        key=lambda x: x["score"],
        reverse=True
    )

    # 최고 점수 타입
    best_type = candidates[0]["type"] if candidates else "paragraph"
    threshold = cfg("block.score_threshold", 3)

    # mixed 판정 (상위 2개 점수가 비슷하면)
    if len(candidates) >= 2:
        if candidates[0]["score"] - candidates[1]["score"] <= 1:
            if is_span_level_type_combination(candidates[0]["type"], candidates[1]["type"]):
                best_type = "mixed"

    region["_type"] = best_type if scores.get(best_type, 0) >= threshold else "paragraph"
    region["_type_scores"] = scores
    region["_type_reason"] = reasons
    region["_type_candidates"] = candidates[:3]  # 상위 3개 후보

    return region["_type"]


def is_span_level_type_combination(type1: str, type2: str) -> bool:
    """span-level 처리가 필요한 타입 조합인지"""
    span_combinations = [
        {"footer", "copyright"},
        {"footer", "person_name"},
        {"copyright", "person_name"},
        {"section_number", "title"},
    ]
    return {type1, type2} in span_combinations


def has_repeated_list_layout(region: dict, all_regions: list[dict]) -> bool:
    """같은 indent로 반복되는 리스트 레이아웃인지 감지

    bullet 기호가 없어도, 같은 x 위치로 반복되는 항목이면 bullet 후보
    """
    bbox = region.get("bbox")
    if not bbox:
        return False

    x1, y1, x2, y2 = bbox
    h = y2 - y1
    if h <= 0:
        return False

    similar_count = 0

    for other in all_regions:
        if other is region:
            continue

        other_bbox = other.get("bbox")
        if not other_bbox:
            continue

        ox1, oy1, ox2, oy2 = other_bbox
        oh = oy2 - oy1

        # 조건:
        # 1. 비슷한 x 시작 위치 (indent)
        same_indent = abs(ox1 - x1) < 40

        # 2. 비슷한 높이 (폰트 크기)
        similar_height = oh > 0 and 0.6 <= (oh / h) <= 1.6

        # 3. 수직 방향으로 가까운 이웃 (같은 리스트 내)
        vertical_neighbor = abs(oy1 - y1) < h * 8

        if same_indent and similar_height and vertical_neighbor:
            similar_count += 1

    return similar_count >= 2


def is_short_list_like_line(region: dict) -> bool:
    """짧은 리스트 항목처럼 보이는지"""
    text = region.get("ocr_text", "")
    if not text:
        return False

    # 한 줄짜리, 문장 종결이 아닌 경우
    lines = text.strip().split("\n")
    if len(lines) > 1:
        return False

    # 너무 길지 않음
    if len(text) > 100:
        return False

    # 마침표로 끝나지 않음 (단, 약어 제외)
    if text.rstrip().endswith(".") and not re.search(r"\b(etc|vs|Mr|Ms|Dr)\.$", text):
        return False

    return True


def detect_bullet_by_layout(
    region: dict,
    all_regions: list[dict],
    image=None
) -> tuple[str, int]:
    """layout 기반 bullet 감지 (점수 기반 판단)

    Returns:
        (타입, 점수) - "bullet_head", "bullet_candidate", 또는 ""
    """
    text = region.get("ocr_text", "")
    bbox = region.get("bbox")
    if not bbox:
        return "", 0

    score = 0
    reasons = []

    # 1. prefix hint score (Unicode category + 패턴 기반)
    prefix_score = get_prefix_hint_score(text)
    if prefix_score > 0:
        score += prefix_score
        reasons.append(f"prefix={prefix_score}")

    # 2. repeated list layout 감지
    if has_repeated_list_layout(region, all_regions):
        score += 3
        reasons.append("repeated_layout")

    # 3. 짧은 리스트 항목처럼 보이는지
    if is_short_list_like_line(region):
        score += 1
        reasons.append("short_list_line")

    # 4. 위쪽에 bullet이 있고, 들여쓰기가 있으면 continuation 후보
    x_start = bbox[0]
    y_top = bbox[1]

    has_bullet_above = False
    for other in all_regions:
        other_bbox = other.get("bbox")
        if not other_bbox or other is region:
            continue

        # 위쪽에 있고, 비슷한 x 위치
        if other_bbox[3] < y_top and abs(other_bbox[0] - x_start) < 100:
            if get_prefix_hint_score(other.get("ocr_text", "")) >= 2:
                has_bullet_above = True
                break

    if has_bullet_above and prefix_score == 0:
        # bullet 위에 있지만 자신은 prefix 없음 → continuation 후보
        score += 2
        reasons.append("below_bullet")

    # 점수 기반 판정
    # bullet_head는 반드시 bullet prefix가 있어야 함 (prefix_score > 0)
    # prefix 없이 bullet_head가 되면 안 됨 (예: "직 면"이 bullet_head로 잘못 분류되는 문제)
    if score >= 5 and prefix_score > 0:
        return "bullet_head", score
    elif score >= 3:
        # prefix 없이 score >= 5면 candidate로 낮춤 (continuation 가능성 높음)
        if prefix_score == 0 and score >= 5:
            return "bullet_candidate", score
        return "bullet_candidate", score

    return "", 0


def get_prefix_hint_score(text: str) -> int:
    """prefix 기반 bullet 힌트 점수 (하드코딩 목록 대신 Unicode category + 패턴 사용)

    Returns:
        힌트 점수 (0~5)
    """
    if not text:
        return 0

    stripped = text.strip()
    if not stripped:
        return 0

    first = stripped[0]
    score = 0

    # 1. Unicode category 기반 판단 (Symbol, Punctuation 계열)
    category = unicodedata.category(first)
    if category.startswith(("S", "P")):  # Symbol, Punctuation
        # 단, 일반적인 문장 부호는 제외 (쉼표, 마침표 등)
        if first not in ".,;:!?'\"()[]{}":
            score += 2

    # 2. 숫자 목록 패턴: 1. / 1) / (1)
    if re.match(r"^\s*\(?\d+\)?[.)]\s+", stripped):
        score += 3

    # 3. 알파벳 목록 패턴: A. / a) / (a)
    if re.match(r"^\s*\(?[A-Za-z]\)?[.)]\s+", stripped):
        score += 2

    # 4. 한글 목록 패턴: 가. / 나)
    if re.match(r"^\s*[가-하][.)]\s+", stripped):
        score += 2

    # 5. 원문자 패턴: ①②③ 등
    if re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]", stripped):
        score += 3

    return min(score, 5)  # 최대 5점


def starts_with_bullet(text: str) -> bool:
    """bullet 기호로 시작하는지 (하위 호환용)"""
    return get_prefix_hint_score(text) >= 2


def is_copyright_text(text: str) -> bool:
    """copyright 패턴인지"""
    patterns = [
        r"©",
        r"[Cc]opyright",
        r"[Aa]ll [Rr]ights [Rr]eserved",
    ]
    return any(re.search(p, text) for p in patterns)


def is_page_number(text: str) -> bool:
    """페이지 번호인지"""
    text = text.strip()
    # 숫자만 있거나, "Page X", "X/Y" 형식
    patterns = [
        r"^\d{1,3}$",
        r"^[Pp]age\s*\d+",
        r"^\d+\s*/\s*\d+$",
    ]
    return any(re.match(p, text) for p in patterns)


def is_section_number(text: str) -> bool:
    """섹션 번호인지"""
    patterns = [
        r"^\d{1,2}\.\s",  # "1. "
        r"^\d{1,2}\.\d+\s",  # "1.1 "
        r"^[IVX]+\.\s",  # "I. ", "II. "
    ]
    return any(re.match(p, text.strip()) for p in patterns)


def is_url(text: str) -> bool:
    """URL인지"""
    return bool(re.search(r"https?://|www\.", text))


def is_code_like(text: str) -> bool:
    """코드 패턴인지"""
    patterns = [
        r"[{}();]",  # 괄호/세미콜론
        r"def\s+\w+",  # Python 함수
        r"function\s+\w+",  # JS 함수
        r"class\s+\w+",  # 클래스
        r"import\s+\w+",  # import
        r"return\s+",  # return
    ]
    # 패턴이 많이 매칭되면 코드일 가능성
    matches = sum(1 for p in patterns if re.search(p, text))
    return matches >= 2


def text_matches_glossary(text: str, glossary: dict, section: str) -> bool:
    """glossary 섹션에 매칭되는지"""
    if not glossary or section not in glossary:
        return False
    return text in glossary[section]


def classify_all_regions(
    regions: list[dict],
    image_size: tuple[int, int],
    glossary: Optional[dict] = None,
    image=None
) -> list[dict]:
    """모든 region 타입 분류"""
    for region in regions:
        classify_region_type_scored(region, image_size, regions, glossary, image)
    return regions


def save_classified_regions(regions: list[dict], output_path: str):
    """분류된 region 저장"""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "regions": regions,
            "count": len(regions),
            "type_counts": _count_by_type(regions)
        }, f, ensure_ascii=False, indent=2)


def _count_by_type(regions: list[dict]) -> dict:
    """타입별 개수 집계"""
    counts = {}
    for r in regions:
        t = r.get("_type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


# ===== Page Type Classification =====

PAGE_TYPES = [
    "diagram_or_label_dense",  # 다이어그램/라벨 밀집 (짧은 텍스트가 많고 흩어져 있음)
    "paragraph_or_bullet",     # 문단/불릿 (긴 텍스트 위주)
    "agenda_or_toc",           # 목차/아젠다
]


def classify_page_type(
    page_regions: list[dict],
    page_size: tuple[int, int]
) -> dict:
    """페이지 타입 분류

    Args:
        page_regions: 페이지의 모든 region 리스트
        page_size: (width, height)

    Returns:
        {
            "page_type": "diagram_or_label_dense" | "paragraph_or_bullet" | "agenda_or_toc",
            "confidence": float,
            "metrics": {...}
        }
    """
    if not page_regions:
        return {
            "page_type": "paragraph_or_bullet",
            "confidence": 0.5,
            "metrics": {}
        }

    page_w, page_h = page_size

    # 텍스트 길이 통계
    text_lengths = []
    short_text_count = 0  # < 20자
    medium_text_count = 0  # 20-80자
    long_text_count = 0  # > 80자

    # 위치 분포
    x_positions = []
    y_positions = []

    # 타입별 카운트
    type_counts = {}
    diagram_label_count = 0
    bullet_count = 0
    paragraph_count = 0

    for region in page_regions:
        text = region.get("ocr_text", "")
        text_len = len(text.strip())
        text_lengths.append(text_len)

        if text_len < 20:
            short_text_count += 1
        elif text_len < 80:
            medium_text_count += 1
        else:
            long_text_count += 1

        bbox = region.get("bbox", [0, 0, 0, 0])
        x_center = (bbox[0] + bbox[2]) / 2 if bbox else 0
        y_center = (bbox[1] + bbox[3]) / 2 if bbox else 0
        x_positions.append(x_center)
        y_positions.append(y_center)

        # 타입별 카운트
        region_type = region.get("_type", "paragraph")
        type_counts[region_type] = type_counts.get(region_type, 0) + 1

        if region_type == "diagram_label":
            diagram_label_count += 1
        elif region_type in ("bullet_head", "bullet_candidate", "bullet_continuation"):
            bullet_count += 1
        elif region_type == "paragraph":
            paragraph_count += 1

    total_regions = len(page_regions)
    avg_text_len = sum(text_lengths) / total_regions if total_regions > 0 else 0

    # X 위치 분산 계산 (텍스트가 흩어져 있는지)
    x_variance = _calculate_variance(x_positions)
    x_spread = x_variance / (page_w ** 2) if page_w > 0 else 0

    # 짧은 텍스트 비율
    short_ratio = short_text_count / total_regions if total_regions > 0 else 0

    # 점수 계산
    scores = {
        "diagram_or_label_dense": 0,
        "paragraph_or_bullet": 0,
        "agenda_or_toc": 0,
    }

    # ===== diagram_or_label_dense 점수 =====
    # 짧은 텍스트가 많음 (70% 이상)
    if short_ratio > 0.7:
        scores["diagram_or_label_dense"] += 4
    elif short_ratio > 0.5:
        scores["diagram_or_label_dense"] += 2

    # X 위치가 많이 분산됨 (흩어진 라벨)
    if x_spread > 0.03:
        scores["diagram_or_label_dense"] += 3
    elif x_spread > 0.02:
        scores["diagram_or_label_dense"] += 1

    # diagram_label 타입이 많음
    if diagram_label_count > 3:
        scores["diagram_or_label_dense"] += 3
    elif diagram_label_count > 1:
        scores["diagram_or_label_dense"] += 1

    # 평균 텍스트 길이가 짧음 (30자 이하)
    if avg_text_len < 30:
        scores["diagram_or_label_dense"] += 2
    elif avg_text_len < 50:
        scores["diagram_or_label_dense"] += 1

    # ===== paragraph_or_bullet 점수 =====
    # 긴 텍스트가 있음
    if long_text_count >= 2:
        scores["paragraph_or_bullet"] += 4
    elif long_text_count >= 1:
        scores["paragraph_or_bullet"] += 2

    # bullet 타입이 많음 - 가중치 대폭 강화
    # bullet_candidate도 bullet으로 카운트 (region_classification에서 bullet_candidate는 ■ 등으로 시작하는 텍스트)
    total_bullet_count = bullet_count + type_counts.get("bullet_candidate", 0)

    # bullet이 5개 이상이면 거의 확실히 paragraph_or_bullet
    if total_bullet_count >= 8:
        scores["paragraph_or_bullet"] += 10  # 압도적 가중치
    elif total_bullet_count >= 5:
        scores["paragraph_or_bullet"] += 7  # 강화
    elif total_bullet_count >= 3:
        scores["paragraph_or_bullet"] += 5  # 강화
    elif total_bullet_count >= 1:
        scores["paragraph_or_bullet"] += 2

    # 평균 텍스트 길이가 김
    if avg_text_len > 80:
        scores["paragraph_or_bullet"] += 2
    elif avg_text_len > 50:
        scores["paragraph_or_bullet"] += 1

    # 중간 길이 텍스트(20-80자)가 많으면 paragraph일 가능성 높음
    # (OCR이 문장을 여러 region으로 분할한 경우)
    medium_ratio = medium_text_count / total_regions if total_regions > 0 else 0
    if medium_ratio > 0.3:
        scores["paragraph_or_bullet"] += 2
    elif medium_ratio > 0.2:
        scores["paragraph_or_bullet"] += 1

    # ===== agenda_or_toc 점수 =====
    # section_number 또는 list_number가 많음
    section_count = type_counts.get("section_number", 0) + type_counts.get("list_number", 0)
    if section_count >= 5:
        scores["agenda_or_toc"] += 4
    elif section_count >= 3:
        scores["agenda_or_toc"] += 2

    # 숫자 목록 패턴 확인
    numbered_items = 0
    for region in page_regions:
        text = region.get("ocr_text", "").strip()
        if re.match(r"^\d+\.", text) or re.match(r"^[IVX]+\.", text):
            numbered_items += 1
    if numbered_items >= 5:
        scores["agenda_or_toc"] += 3
    elif numbered_items >= 3:
        scores["agenda_or_toc"] += 1

    # 최고 점수 타입 선택
    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]
    total_score = sum(scores.values())

    # confidence 계산
    confidence = best_score / total_score if total_score > 0 else 0.5

    # 점수가 너무 낮으면 기본값
    if best_score < 3:
        best_type = "paragraph_or_bullet"
        confidence = 0.3

    return {
        "page_type": best_type,
        "confidence": round(confidence, 2),
        "metrics": {
            "total_regions": total_regions,
            "avg_text_len": round(avg_text_len, 1),
            "short_ratio": round(short_ratio, 2),
            "x_spread": round(x_spread, 4),
            "type_counts": type_counts,
            "scores": scores,
        }
    }


def _calculate_variance(values: list) -> float:
    """분산 계산"""
    if len(values) < 2:
        return 0
    mean = sum(values) / len(values)
    return sum((x - mean) ** 2 for x in values) / len(values)
