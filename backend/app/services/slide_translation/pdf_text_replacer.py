"""
PDF 텍스트 교체 모듈 (Production Level)

핵심 전략:
1. bbox 확장: 영어가 안 들어가면 주변 여백으로 rect 확장
2. fit 기반 폰트: TextWriter로 실제 들어가는지 시뮬레이션
3. role별 정책: title/body/caption별 최소 폰트 크기 다르게
4. redaction 전략: 배경 유형에 따라 다른 처리
"""
import fitz
import os
import re
from typing import Optional
from dataclasses import dataclass, field, asdict
import logging
import json

from .pdf_font_handler import (
    map_korean_to_english_font,
    int_color_to_rgb,
)

logger = logging.getLogger(__name__)

# 한글 폰트 경로 (env에서 읽기, 없으면 기본값)
KOREAN_FONT_PATH = os.getenv("KOREAN_FONT_PATH", "C:/Windows/Fonts/malgun.ttf")
if not os.path.exists(KOREAN_FONT_PATH):
    # fallback 경로들
    fallback_paths = [
        "C:/Windows/Fonts/NanumGothic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in fallback_paths:
        if os.path.exists(path):
            KOREAN_FONT_PATH = path
            break

# 이미지 배경 감지 threshold
IMAGE_BG_VARIANCE_THRESHOLD = int(os.getenv("IMAGE_BG_VARIANCE_THRESHOLD", "150"))


def _render_multi_color_text(
    page,
    trans: dict,
    rect,
    font: str,
    size: float,
    bg_color: tuple
) -> float:
    """
    Term: Definition 전용 다중 색상 렌더러

    Fallback 순서 (Layout Plan 먼저, 성공 시에만 렌더링):
    A. 같은 줄 multi-color
    B. 두 줄 multi-color
    C. bbox 아래 확장 후 두 줄 multi-color
    D. 폰트 축소 후 재시도 (0.95, 0.9, 0.85)
    E. 단색 textbox fallback
    F. 그래도 안 되면 -1 반환 (review_needed)

    핵심: definition이 반드시 보여야 함. 색상은 그 다음 문제.
    """
    translated = trans.get('translated', '')
    line_colors = trans.get('line_colors', [])
    page_rect = page.rect

    # 색상 준비
    first_color = (0, 0, 0)
    second_color = (0, 0, 0)
    has_multi_color = False

    if line_colors and len(line_colors) >= 2:
        colors = []
        for c in line_colors:
            if isinstance(c, int):
                colors.append(int_color_to_rgb(c))
            elif isinstance(c, (list, tuple)) and len(c) == 3:
                colors.append(tuple(c))
            else:
                colors.append((0, 0, 0))

        first_color = colors[0]
        for c in colors[1:]:
            if c != first_color:
                second_color = c
                has_multi_color = True
                break

    # "Term[구분자] Definition" 패턴 감지
    # 구분자: 한글, 영문, 숫자, 공백을 제외한 모든 기호
    match = re.search(r'^([A-Za-z가-힣0-9\s]+?)([^A-Za-z가-힣0-9\s])\s*', translated)

    if not match:
        # 패턴 없으면 단색 textbox
        return page.insert_textbox(
            rect, translated, fontname=font, fontsize=size,
            color=first_color, align=fitz.TEXT_ALIGN_LEFT
        )

    term = match.group(1).strip() + match.group(2)
    definition = translated[match.end():].strip()

    if not definition:
        # definition 없으면 term만 렌더링
        page.insert_text(
            (rect.x0, rect.y0 + size), term,
            fontname=font, fontsize=size, color=first_color
        )
        return 0

    # ===== Fallback 전략들 (Layout Plan → 렌더링) =====
    term_color = first_color if has_multi_color else (0, 0, 0)
    def_color = second_color if has_multi_color else (0, 0, 0)

    # 시도할 폰트 스케일
    font_scales = [1.0, 0.95, 0.9, 0.85]
    # bbox 아래 확장 비율
    expand_ratios = [0, 0.3, 0.5, 0.8]

    for font_scale in font_scales:
        current_size = size * font_scale
        line_height = current_size * 1.2

        for expand_ratio in expand_ratios:
            # 확장된 rect 계산
            expanded_y1 = min(
                rect.y1 + rect.height * expand_ratio,
                page_rect.height - 5
            )
            expanded_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, expanded_y1)

            if expanded_rect.is_empty or expanded_rect.height < current_size:
                continue

            # === Strategy A: 같은 줄 multi-color ===
            term_with_space = term + " "
            term_width = fitz.get_text_length(term_with_space, fontname=font, fontsize=current_size)
            full_width = fitz.get_text_length(term_with_space + definition, fontname=font, fontsize=current_size)

            if full_width <= expanded_rect.width:
                # Layout Plan 성공 → 렌더링
                baseline_y = expanded_rect.y0 + current_size
                page.insert_text(
                    (expanded_rect.x0, baseline_y), term_with_space,
                    fontname=font, fontsize=current_size, color=term_color
                )
                page.insert_text(
                    (expanded_rect.x0 + term_width, baseline_y), definition,
                    fontname=font, fontsize=current_size, color=def_color
                )
                return 0  # 성공

            # === Strategy B/C: 두 줄 multi-color ===
            def_rect = fitz.Rect(
                expanded_rect.x0, expanded_rect.y0 + line_height,
                expanded_rect.x1, expanded_rect.y1
            )

            if def_rect.is_empty or def_rect.height < current_size:
                continue

            # Definition이 들어갈 수 있는지 시뮬레이션
            char_width = current_size * 0.55  # 보수적 추정
            chars_per_line = max(1, int(def_rect.width / char_width))
            lines_needed = (len(definition) + chars_per_line - 1) // chars_per_line
            height_needed = lines_needed * line_height

            # 여유 있게 체크 (약간의 overflow 허용)
            if height_needed <= def_rect.height + line_height * 0.3:
                # Layout Plan 성공 → 렌더링
                baseline_y = expanded_rect.y0 + current_size
                page.insert_text(
                    (expanded_rect.x0, baseline_y), term,
                    fontname=font, fontsize=current_size, color=term_color
                )
                page.insert_textbox(
                    def_rect, definition,
                    fontname=font, fontsize=current_size, color=def_color,
                    align=fitz.TEXT_ALIGN_LEFT
                )
                return 0  # 성공

    # === Strategy E: 단색 textbox fallback ===
    # multi-color 포기, 전체 문장을 단색으로
    for font_scale in [1.0, 0.9, 0.8, 0.7]:
        current_size = size * font_scale
        for expand_ratio in [0, 0.5, 1.0]:
            expanded_y1 = min(
                rect.y1 + rect.height * expand_ratio,
                page_rect.height - 5
            )
            expanded_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, expanded_y1)

            if expanded_rect.is_empty:
                continue

            result = page.insert_textbox(
                expanded_rect, translated,
                fontname=font, fontsize=current_size, color=(0, 0, 0),
                align=fitz.TEXT_ALIGN_LEFT
            )
            if result >= 0:
                return result  # 성공

    # === Strategy F: 최후의 수단 ===
    # 최대 확장 + 최소 폰트로 시도
    max_rect = fitz.Rect(
        rect.x0, rect.y0, rect.x1,
        min(rect.y1 + rect.height * 1.5, page_rect.height - 5)
    )
    result = page.insert_textbox(
        max_rect, translated,
        fontname=font, fontsize=size * 0.6, color=(0, 0, 0),
        align=fitz.TEXT_ALIGN_LEFT
    )
    if result >= 0:
        return result

    return -1  # review_needed (모든 전략 실패)



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


# Role별 최소 폰트 크기 (env에서 읽기)
MIN_FONT_SIZE = {
    "title": float(os.getenv("MIN_FONT_SIZE_TITLE", "14.0")),
    "heading": float(os.getenv("MIN_FONT_SIZE_HEADING", "12.0")),
    "body": float(os.getenv("MIN_FONT_SIZE_BODY", "10.0")),
    "bullet": float(os.getenv("MIN_FONT_SIZE_BODY", "10.0")),
    "caption": float(os.getenv("MIN_FONT_SIZE_CAPTION", "6.0")),
    "footer": float(os.getenv("MIN_FONT_SIZE_CAPTION", "6.0")),
    "source": float(os.getenv("MIN_FONT_SIZE_CAPTION", "6.0")),
    "default": float(os.getenv("MIN_FONT_SIZE_DEFAULT", "8.0")),
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

        # 1단계: redaction 준비 (VLM 분석 결과 반영)
        redaction_data = []  # redaction 적용할 블록
        overlay_data = []     # 이미지 위 텍스트 (redaction 없이 덮어쓰기)

        for trans in trans_list:
            bbox = trans.get("bbox", (0, 0, 0, 0))
            prefix_width = trans.get("prefix_width", 0.0)
            on_image = trans.get("on_image_background", False)
            keep_prefix = trans.get("keep_prefix", True)  # 기본: prefix 유지

            if len(bbox) == 4:
                x0, y0, x1, y1 = bbox
                # keep_prefix=True이고 prefix_width가 있을 때만 prefix 영역 보존
                x0_adjusted = x0 + prefix_width if (keep_prefix and prefix_width > 0) else x0
                rect = fitz.Rect(x0_adjusted, y0, x1, y1)

                if on_image:
                    # 이미지 위 텍스트: 배경색 샘플링 후 판단
                    bg_info = _analyze_background(page, rect)
                    bg_color = bg_info.get("color", (1, 1, 1))

                    # 안전장치: 배경이 흰색에 가까우면 on_image 무시
                    is_white_bg = (bg_color[0] > 0.9 and bg_color[1] > 0.9 and bg_color[2] > 0.9)

                    if is_white_bg:
                        # 배경이 흰색이면 일반 텍스트로 처리
                        page.add_redact_annot(rect, fill=(1, 1, 1))
                        redaction_data.append((trans, rect))
                    else:
                        # 실제 이미지/다이어그램 배경: 해당 색으로 redaction
                        page.add_redact_annot(rect, fill=bg_color)
                        trans["expand_allowed"] = False
                        redaction_data.append((trans, rect))
                else:
                    # 일반 텍스트: 흰색 배경으로 redaction
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    redaction_data.append((trans, rect))

        # 2단계: redaction 적용 (일반 배경만)
        if redaction_data:
            page.apply_redactions(images=0)  # 이미지 유지

        # 3단계: 번역된 텍스트 삽입
        # 3a: redaction된 영역
        for trans, _ in redaction_data:
            result = _replace_single_block(page, trans, page_rect, None)
            debug_records.append(asdict(result))

            if result.status == "replaced":
                results["replaced"] += 1
            elif result.status == "review_needed":
                results["review_needed"] += 1
            else:
                results["failed"] += 1

        # 3b: 이미지 위 텍스트 (redaction 없이 덮어쓰기)
        for trans, _ in overlay_data:
            # expand_allowed=False로 설정해서 bbox 확장 방지
            trans["expand_allowed"] = False
            result = _replace_single_block(page, trans, page_rect, None)
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
    expand_allowed = trans.get("expand_allowed", True)  # VLM 분석 결과
    keep_prefix = trans.get("keep_prefix", True)  # prefix 유지 여부

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
    # prefix area skip (only when keep_prefix=True and prefix_width > 0)
    x0_adjusted = x0 + prefix_width if (keep_prefix and prefix_width > 0) else x0
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
        original_rect, page_rect, role, min_size,
        allow_expansion=expand_allowed
    )

    final_rect = fit_result["rect"]
    final_size = fit_result["size"]
    result.expanded_bbox = (final_rect.x0, final_rect.y0, final_rect.x1, final_rect.y1)
    result.final_size = final_size

    # 5. 텍스트 삽입 (redaction으로 이미 배경 처리됨)
    if has_multi_color:
        # multi-color 렌더러가 모든 fallback을 내부적으로 처리
        # (같은 줄 → 두 줄 → bbox 확장 → 폰트 축소 → 단색 fallback)
        insert_result = _render_multi_color_text(
            page, trans, final_rect, english_font, final_size, bg_info["color"]
        )
    else:
        # 단색 텍스트
        insert_result = page.insert_textbox(
            final_rect,
            translated,
            fontname=english_font,
            fontsize=final_size,
            color=text_color,
            align=fitz.TEXT_ALIGN_LEFT
        )
    result.insert_result = insert_result

    # 단색 텍스트의 overflow 처리 (multi-color는 이미 내부에서 처리됨)
    if insert_result < 0 and not has_multi_color:
        retry_rect = final_rect

        if expand_allowed:
            orig_len = len(original) if original else 1
            trans_len = len(translated) if translated else 1
            expansion_factor = max(0.5, min(2.0, trans_len / orig_len - 1))

            retry_rect = fitz.Rect(
                final_rect.x0,
                final_rect.y0,
                min(final_rect.x1 + final_rect.width * expansion_factor, page_rect.width - 5),
                min(final_rect.y1 + final_rect.height * 0.3, page_rect.height - 5)
            )

            # 재시도 - 확장된 rect로 렌더링
            insert_result = page.insert_textbox(
                retry_rect,
                translated,
                fontname=english_font,
                fontsize=final_size,
                color=text_color,
                align=fitz.TEXT_ALIGN_LEFT
            )
            result.insert_result = insert_result
            result.expanded_bbox = (retry_rect.x0, retry_rect.y0, retry_rect.x1, retry_rect.y1)

            # 여전히 overflow면 폰트를 더 줄여서 시도
            if insert_result < 0 and final_size > 8.0:
                smaller_size = max(8.0, final_size * 0.7)
                insert_result = page.insert_textbox(
                    retry_rect,
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
    else:
        result.status = "review_needed"
        result.error = "insert_textbox_overflow"

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

        # variance 높으면 이미지 배경
        r_vals = [samples[i] for i in range(0, len(samples), 3)]
        if len(r_vals) > 1:
            avg_r = sum(r_vals) / len(r_vals)
            variance = sum((x - avg_r)**2 for x in r_vals) / len(r_vals)
            if variance > IMAGE_BG_VARIANCE_THRESHOLD:
                # 이미지 배경: 평균 색상 반환 (한글 위장용)
                return {"type": "image", "color": (r, g, b)}

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
    min_size: float,
    allow_expansion: bool = True
) -> dict:
    """
    fit 기반 폰트 크기 계산 + bbox 확장

    순서:
    1. 원본 크기로 시도
    2. 안 되면 rect 확장 (allow_expansion=True일 때만)
    3. 안 되면 폰트 축소
    4. min_size까지만 축소

    Args:
        allow_expansion: False면 bbox 확장 없이 폰트만 축소
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
    if allow_expansion:
        rects_to_try = [
            original_rect,
            fitz.Rect(original_rect.x0, original_rect.y0, max_right, original_rect.y1),
            fitz.Rect(original_rect.x0, original_rect.y0, max_right, max_bottom),
        ]
    else:
        # 확장 금지: 원본 rect만 사용
        rects_to_try = [original_rect]

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

    # 모두 실패 시 (확장 허용 여부에 따라 다른 결과)
    if allow_expansion:
        return {
            "rect": fitz.Rect(original_rect.x0, original_rect.y0, max_right, max_bottom),
            "size": min_size,
            "fit": -1
        }
    else:
        # 확장 금지: 원본 rect + 최소 크기
        return {
            "rect": original_rect,
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
