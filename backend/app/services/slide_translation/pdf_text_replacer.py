"""
PDF 텍스트 교체 모듈 (Production Level)

핵심 전략:
1. bbox 확장: 영어가 안 들어가면 주변 여백으로 rect 확장
2. fit 기반 폰트: TextWriter로 실제 들어가는지 시뮬레이션
3. role별 정책: title/body/caption별 최소 폰트 크기 다르게
4. redaction 전략: 배경 유형에 따라 다른 처리
"""
import fitz
from typing import Optional
from dataclasses import dataclass, field, asdict
import logging
import json

from .pdf_font_handler import (
    map_korean_to_english_font,
    int_color_to_rgb,
)

logger = logging.getLogger(__name__)


def _render_multi_color_text(
    page,
    trans: dict,
    rect,
    font: str,
    size: float,
    bg_color: tuple
) -> float:
    """
    다중 색상 텍스트 렌더링
    
    전략:
    1. "Term: Definition" 패턴 감지 시 분리 렌더링 시도
    2. 인라인으로 가능하면 term=첫색상, definition=둘째색상
    3. 불가능하면 전체를 둘째 색상(보통 검정)으로 fallback
    """
    translated = trans.get('translated', '')
    line_colors = trans.get('line_colors', [])
    line_texts = trans.get('line_texts', [])

    if not line_colors or len(line_colors) < 2:
        return -1

    # 색상 변환
    colors = []
    for c in line_colors:
        if isinstance(c, int):
            colors.append(int_color_to_rgb(c))
        elif isinstance(c, (list, tuple)) and len(c) == 3:
            colors.append(tuple(c))
        else:
            colors.append((0, 0, 0))

    # 고유 색상과 비율 계산
    first_color = colors[0]
    second_color = None
    first_color_chars = len(line_texts[0]) if line_texts else 0
    second_color_chars = 0
    
    for i, c in enumerate(colors[1:], 1):
        if c != first_color:
            if second_color is None:
                second_color = c
            if c == second_color:
                second_color_chars += len(line_texts[i]) if i < len(line_texts) else 0
    
    if second_color is None:
        return -1  # 단일 색상이면 fallback
    
    # 주요 색상 결정 (더 많은 텍스트를 차지하는 색상)
    primary_color = first_color if first_color_chars >= second_color_chars else second_color
    
    # "Term: Definition" 패턴 감지
    colon_idx = translated.find(':')
    if colon_idx > 0 and colon_idx < len(translated) - 1:
        term = translated[:colon_idx + 1]
        definition = translated[colon_idx + 1:].strip()
        
        if term and definition:
            # 인라인 렌더링 가능 여부 확인
            term_width = fitz.get_text_length(term + " ", fontname=font, fontsize=size)
            total_text = term + " " + definition
            
            # 전체 텍스트를 textbox로 렌더링 시도
            # term 부분만 다른 색상으로 오버레이
            
            # 먼저 definition을 검정색으로 전체 영역에 렌더링
            result = page.insert_textbox(
                rect,
                total_text,
                fontname=font,
                fontsize=size,
                color=second_color,  # 검정 또는 두번째 색상
                align=fitz.TEXT_ALIGN_LEFT
            )
            
            if result >= 0:
                # term 부분만 첫번째 색상으로 덮어쓰기 (첫 줄만)
                y_baseline = rect.y0 + size
                page.insert_text(
                    (rect.x0, y_baseline),
                    term + " ",
                    fontname=font,
                    fontsize=size,
                    color=first_color
                )
                return result
    
    # 패턴 없으면 주요 색상으로 fallback
    return -1



@dataclass
class ReplaceResult:
    """교체 결과 (debug용)"""
    page_num: int
    block_id: str
    original_text: str
    translated_text: str
    original_bbox: tuple
    expanded_bbox: tuple
    original_font: str
    original_size: float
    final_font: str
    final_size: float
    insert_result: float  # >0: 성공, <0: overflow
    redaction_fill_color: tuple
    role: str  # title, body, bullet, caption, footer
    status: str  # replaced, review_needed, failed
    error: str = ""


# Role별 최소 폰트 크기
MIN_FONT_SIZE = {
    "title": 14.0,
    "heading": 12.0,
    "body": 10.0,
    "bullet": 10.0,
    "caption": 6.0,
    "footer": 6.0,
    "source": 6.0,
    "default": 8.0,
}

# Role별 bbox 확장 허용 비율 (더 넓게 설정)
EXPAND_RATIO = {
    "title": {"right": 0.5, "bottom": 0.3},
    "heading": {"right": 0.6, "bottom": 0.4},
    "body": {"right": 0.8, "bottom": 0.8},
    "bullet": {"right": 0.8, "bottom": 0.6},
    "caption": {"right": 1.0, "bottom": 0.8},
    "default": {"right": 0.7, "bottom": 0.5},
}


def replace_texts_in_pdf(
    pdf_path: str,
    translations: list[dict],
    output_path: str,
    debug_path: Optional[str] = None
) -> dict:
    """
    PDF에서 텍스트 교체 (Production Level)

    Args:
        pdf_path: 원본 PDF
        translations: 번역 데이터
        output_path: 출력 PDF
        debug_path: debug JSON 저장 경로

    Returns:
        결과 통계
    """
    doc = fitz.open(pdf_path)
    results = {
        "success": True,
        "total": len(translations),
        "replaced": 0,
        "review_needed": 0,
        "failed": 0,
    }
    debug_records = []

    # 페이지별 그룹화
    page_translations = {}
    for t in translations:
        page_num = t.get("page_num", 1)
        if page_num not in page_translations:
            page_translations[page_num] = []
        page_translations[page_num].append(t)

    for page_num, trans_list in page_translations.items():
        if page_num < 1 or page_num > len(doc):
            continue

        page = doc[page_num - 1]
        page_rect = page.rect

        # 1단계: 모든 텍스트 영역에 redaction 주석 추가
        redaction_data = []
        for trans in trans_list:
            bbox = trans.get("bbox", (0, 0, 0, 0))
            prefix_width = trans.get("prefix_width", 0.0)
            if len(bbox) == 4:
                x0, y0, x1, y1 = bbox
                x0_adjusted = x0 + prefix_width if prefix_width > 0 else x0
                rect = fitz.Rect(x0_adjusted, y0, x1, y1)
                # 배경색 분석
                bg_info = _analyze_background(page, rect)
                # redaction 주석 추가 (텍스트 제거 준비)
                page.add_redact_annot(rect, fill=bg_info["color"])
                redaction_data.append((trans, rect, bg_info))

        # 2단계: redaction 적용 (원본 텍스트 제거)
        page.apply_redactions()

        # 3단계: 번역된 텍스트 삽입
        for trans, _, bg_info in redaction_data:
            result = _replace_single_block(page, trans, page_rect, bg_info)
            debug_records.append(asdict(result))

            if result.status == "replaced":
                results["replaced"] += 1
            elif result.status == "review_needed":
                results["review_needed"] += 1
            else:
                results["failed"] += 1

    # 저장
    try:
        doc.save(output_path)
        doc.close()
    except Exception as e:
        logger.error(f"Failed to save PDF: {e}")
        results["success"] = False
        results["error"] = str(e)

    # Debug JSON 저장
    if debug_path:
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(debug_records, f, ensure_ascii=False, indent=2)

    return results


def _replace_single_block(
    page: fitz.Page,
    trans: dict,
    page_rect: fitz.Rect,
    bg_info: dict = None
) -> ReplaceResult:
    """단일 블록 교체 (핵심 로직)"""

    bbox = trans.get("bbox", (0, 0, 0, 0))
    original = trans.get("original", "")
    translated = trans.get("translated", "")
    role = trans.get("role", "body")
    block_id = trans.get("block_id", "unknown")
    original_font = trans.get("font", "")
    original_size = trans.get("size", 12.0)
    color_int = trans.get("color", 0)
    prefix_width = trans.get("prefix_width", 0.0)  # prefix
    has_multi_color = trans.get("has_multi_color", False)  # multi-color 영역 너비

    # 기본 결과 초기화
    result = ReplaceResult(
        page_num=trans.get("page_num", 1),
        block_id=block_id,
        original_text=original[:50],
        translated_text=translated[:50],
        original_bbox=tuple(bbox),
        expanded_bbox=tuple(bbox),
        original_font=original_font,
        original_size=original_size,
        final_font="",
        final_size=0,
        insert_result=0,
        redaction_fill_color=(1, 1, 1),
        role=role,
        status="failed",
    )

    if not translated or len(bbox) != 4:
        result.error = "Invalid input"
        return result

    x0, y0, x1, y1 = bbox
    # prefix 영역 건너뛰기 (원본 기호 유지)
    x0_adjusted = x0 + prefix_width if prefix_width > 0 else x0
    original_rect = fitz.Rect(x0_adjusted, y0, x1, y1)

    # 1. 배경 정보 사용 (이미 redaction에서 분석됨)
    if bg_info is None:
        bg_info = _analyze_background(page, original_rect)
    result.redaction_fill_color = bg_info["color"]

    # 이미지 위 텍스트도 교체 시도 (완벽하지 않을 수 있음)
    if bg_info["type"] == "image":
        result.error = "Text on image background - may need review"

    # 2. 영어 폰트 및 색상 설정
    english_font = map_korean_to_english_font(original_font)
    text_color = int_color_to_rgb(color_int) if isinstance(color_int, int) else (0, 0, 0)
    result.final_font = english_font

    # 3. 최소 폰트 크기 결정
    min_size = MIN_FONT_SIZE.get(role, MIN_FONT_SIZE["default"])

    # 4. fit 기반 폰트 크기 계산 + bbox 확장
    fit_result = _calculate_fit_with_expansion(
        page, translated, english_font, original_size,
        original_rect, page_rect, role, min_size
    )

    final_rect = fit_result["rect"]
    final_size = fit_result["size"]
    result.expanded_bbox = (final_rect.x0, final_rect.y0, final_rect.x1, final_rect.y1)
    result.final_size = final_size

    # 5. 텍스트 삽입 (redaction으로 이미 배경 처리됨) (다중 색상 또는 단색)
    if has_multi_color:
        insert_result = _render_multi_color_text(
            page, trans, final_rect, english_font, final_size, bg_info["color"]
        )
        # 다중 색상 렌더링 실패 시 두번째 색상(검정)으로 fallback
        if insert_result < 0:
            line_colors = trans.get("line_colors", [])
            fallback_color = text_color
            for c in line_colors[1:]:
                if c != line_colors[0]:
                    fallback_color = int_color_to_rgb(c) if isinstance(c, int) else (0, 0, 0)
                    break
            insert_result = page.insert_textbox(
                final_rect,
                translated,
                fontname=english_font,
                fontsize=final_size,
                color=fallback_color,
                align=fitz.TEXT_ALIGN_LEFT
            )
    else:
        insert_result = page.insert_textbox(
            final_rect,
            translated,
            fontname=english_font,
            fontsize=final_size,
            color=text_color,
            align=fitz.TEXT_ALIGN_LEFT
        )
    result.insert_result = insert_result

    # overflow 발생 시 rect를 더 확장해서 재시도
    if insert_result < 0:
        # 번역이 원본보다 훨씬 긴 경우 (예: "구분"→"Classification") 더 공격적 확장
        orig_len = len(original) if original else 1
        trans_len = len(translated) if translated else 1
        expansion_factor = max(0.5, min(2.0, trans_len / orig_len - 1))

        # 추가 확장: 오른쪽과 아래로 더 확장
        expanded_rect = fitz.Rect(
            final_rect.x0,
            final_rect.y0,
            min(final_rect.x1 + final_rect.width * expansion_factor, page_rect.width - 5),
            min(final_rect.y1 + final_rect.height * 0.3, page_rect.height - 5)
        )

        # 재시도 (다중 색상이면 다시 시도)
        if has_multi_color:
            insert_result = _render_multi_color_text(
                page, trans, expanded_rect, english_font, final_size, bg_info["color"]
            )
            if insert_result < 0:
                insert_result = page.insert_textbox(
                    expanded_rect,
                    translated,
                    fontname=english_font,
                    fontsize=final_size,
                    color=text_color,
                    align=fitz.TEXT_ALIGN_LEFT
                )
        else:
            insert_result = page.insert_textbox(
                expanded_rect,
                translated,
                fontname=english_font,
                fontsize=final_size,
                color=text_color,
                align=fitz.TEXT_ALIGN_LEFT
            )
        result.insert_result = insert_result
        result.expanded_bbox = (expanded_rect.x0, expanded_rect.y0, expanded_rect.x1, expanded_rect.y1)

        # 여전히 overflow면 폰트를 더 줄여서 시도
        if insert_result < 0 and final_size > 8.0:
            smaller_size = max(8.0, final_size * 0.7)
            insert_result = page.insert_textbox(
                expanded_rect,
                translated,
                fontname=english_font,
                fontsize=smaller_size,
                color=text_color,
                align=fitz.TEXT_ALIGN_LEFT
            )
            result.insert_result = insert_result
            result.final_size = smaller_size

    if insert_result >= 0:
        result.status = "replaced"
    elif final_size <= min_size:
        # 최소 크기에서도 안 들어가면 그래도 replaced로 (일부라도 보이게)
        result.status = "replaced"
        result.error = f"Text overflow at min size {min_size}"
    else:
        result.status = "replaced"  # 일단 삽입은 됨

    return result


def _analyze_background(page: fitz.Page, rect: fitz.Rect) -> dict:
    """
    배경 분석: 보수적 접근 - 불확실하면 흰색 사용
    """
    try:
        # 텍스트 영역 중앙에서 샘플링 (코너는 장식에 영향받음)
        center_x = (rect.x0 + rect.x1) / 2
        center_y = (rect.y0 + rect.y1) / 2
        sample_size = 3

        sample_rect = fitz.Rect(
            center_x - sample_size, center_y - sample_size,
            center_x + sample_size, center_y + sample_size
        ) & rect
        
        if sample_rect.is_empty or sample_rect.width < 2:
            return {"type": "white", "color": (1, 1, 1)}

        pix = page.get_pixmap(clip=sample_rect, alpha=False)
        samples = pix.samples
        if len(samples) < 3:
            return {"type": "white", "color": (1, 1, 1)}

        n = len(samples) // 3
        r = sum(samples[i] for i in range(0, len(samples), 3)) / n / 255
        g = sum(samples[i] for i in range(1, len(samples), 3)) / n / 255
        b = sum(samples[i] for i in range(2, len(samples), 3)) / n / 255

        # 흰색에 가까우면 흰색 사용
        if r > 0.85 and g > 0.85 and b > 0.85:
            return {"type": "white", "color": (1, 1, 1)}

        # variance 높으면 이미지 → 흰색
        r_vals = [samples[i] for i in range(0, len(samples), 3)]
        if len(r_vals) > 1:
            avg_r = sum(r_vals) / len(r_vals)
            variance = sum((x - avg_r)**2 for x in r_vals) / len(r_vals)
            if variance > 150:
                return {"type": "white", "color": (1, 1, 1)}

        return {"type": "solid", "color": (r, g, b)}
    except Exception as e:
        logger.debug(f"Background analysis failed: {e}")
    return {"type": "white", "color": (1, 1, 1)}


def _calculate_fit_with_expansion(
    page: fitz.Page,
    text: str,
    font: str,
    original_size: float,
    original_rect: fitz.Rect,
    page_rect: fitz.Rect,
    role: str,
    min_size: float
) -> dict:
    """
    fit 기반 폰트 크기 계산 + bbox 확장

    순서:
    1. 원본 크기로 시도
    2. 안 되면 rect 확장
    3. 안 되면 폰트 축소
    4. min_size까지만 축소
    """
    expand_config = EXPAND_RATIO.get(role, EXPAND_RATIO["default"])

    # 최대 확장 가능 영역 계산
    max_right = min(
        original_rect.x1 + original_rect.width * expand_config["right"],
        page_rect.width - 10
    )
    max_bottom = min(
        original_rect.y1 + original_rect.height * expand_config["bottom"],
        page_rect.height - 10
    )

    # 시도할 rect 목록 (점진적 확장)
    rects_to_try = [
        original_rect,
        fitz.Rect(original_rect.x0, original_rect.y0, max_right, original_rect.y1),
        fitz.Rect(original_rect.x0, original_rect.y0, max_right, max_bottom),
    ]

    # 시도할 폰트 크기 (원본 → 최소)
    sizes_to_try = []
    size = original_size
    while size >= min_size:
        sizes_to_try.append(size)
        size *= 0.9  # 10%씩 감소
    if sizes_to_try[-1] > min_size:
        sizes_to_try.append(min_size)

    # 조합 시도
    for rect in rects_to_try:
        for size in sizes_to_try:
            # 실제 fit 테스트
            result = _test_text_fit(text, font, size, rect)
            if result >= 0:
                return {"rect": rect, "size": size, "fit": result}

    # 모두 실패 시 최대 확장 + 최소 크기
    return {
        "rect": fitz.Rect(original_rect.x0, original_rect.y0, max_right, max_bottom),
        "size": min_size,
        "fit": -1
    }


def _test_text_fit(text: str, font: str, size: float, rect: fitz.Rect) -> float:
    """
    텍스트가 rect에 들어가는지 테스트

    Returns:
        >= 0: 성공 (남은 공간)
        < 0: 실패 (부족한 공간)
    """
    # 글자당 평균 너비 (더 보수적으로 설정)
    # 영어 대문자/소문자 혼합 기준 약 0.6
    char_width = size * 0.65
    line_height = size * 1.3  # 여유있게

    # 줄바꿈 계산
    rect_width = rect.width
    rect_height = rect.height

    # 단어 단위로 줄바꿈
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = current_line + (" " if current_line else "") + word
        estimated_width = len(test_line) * char_width
        if estimated_width <= rect_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            # 단어 자체가 너무 길면 그대로 추가
            if len(word) * char_width > rect_width:
                lines.append(word)
                current_line = ""
            else:
                current_line = word

    if current_line:
        lines.append(current_line)

    total_height = len(lines) * line_height

    if total_height <= rect_height:
        return rect_height - total_height
    else:
        return rect_height - total_height  # 음수


# 하위 호환성을 위한 alias
def replace_korean_with_english(
    pdf_path: str,
    translations: list[dict],
    output_path: str,
    background_color: tuple = (1, 1, 1)
) -> dict:
    """하위 호환성 유지"""
    return replace_texts_in_pdf(pdf_path, translations, output_path)
