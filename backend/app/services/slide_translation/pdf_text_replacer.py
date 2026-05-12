"""
PDF 텍스트 교체 모듈 (Production Level)

[역할]
- PDF에서 원본 텍스트를 번역된 텍스트로 교체
- Multi-color Term: Definition 렌더링 (핵심!)
- bbox 확장, 폰트 축소 등 자동 fallback

[호출 경로]
pdf_layer_pipeline.py → pdf_text_replacer.py (이 파일)
                        └── pdf_font_handler.py

[핵심 전략]
1. bbox 확장: 영어가 안 들어가면 주변 여백으로 rect 확장
2. fit 기반 폰트: 실제 들어가는지 시뮬레이션
3. role별 정책: title/body/caption별 최소 폰트 크기
4. redaction 전략: 배경 유형에 따라 다른 처리

[주요 함수]
- replace_texts_in_pdf(): 메인 교체 함수
- _render_multi_color_text(): Term: Definition 다중 색상 렌더링
- _replace_single_block(): 단일 블록 교체

[Multi-color 렌더링 Fallback 순서]
A. 같은 줄 multi-color (term 빨강 + definition 검정)
B. 두 줄 multi-color (term 첫 줄, definition 둘째 줄)
C. bbox 아래 확장 후 재시도
D. 폰트 축소 (0.95, 0.9, 0.85)
E. 단색 textbox fallback
F. review_needed 처리

[주의]
- 이 파일의 multi-color 로직이 현재 가장 안정적
- translation.py와 독립적으로 동작
"""
import fitz
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
import logging
import json

from .pdf_font_handler import (
    map_korean_to_english_font,
    int_color_to_rgb,
)

logger = logging.getLogger(__name__)

# ============================================================
# 파일 로깅 설정 (디버깅용)
# ============================================================
_BASE_DIR = Path(__file__).parent.parent.parent.parent.parent
LOG_DIR = _BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_log_date = datetime.now().strftime("%Y%m%d")
LOG_FILE = LOG_DIR / f"pdf_replacer_{_log_date}.log"

_pdf_logger = logging.getLogger("pdf_replacer")
_pdf_logger.setLevel(logging.DEBUG)

if not _pdf_logger.handlers:
    _file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(funcName)-25s | %(message)s",
        datefmt="%H:%M:%S"
    )
    _file_handler.setFormatter(_file_formatter)
    _pdf_logger.addHandler(_file_handler)

def pdf_log_debug(msg: str):
    _pdf_logger.debug(msg)

def pdf_log_warning(msg: str):
    _pdf_logger.warning(msg)


def _get_min_font_size(role: str) -> float:
    """최소 폰트 크기 반환 (모든 role에 대해 6pt)"""
    return 6.0


# =============================================================================
# Invalid Output Gate (Final Rendering Gate)
# =============================================================================

# Invalid patterns that should NEVER be rendered to final PDF
INVALID_RENDER_PATTERNS = [
    r'\?{2,}',                          # Consecutive ?? or more
    r'[A-Za-z가-힣]\?+[A-Za-z가-힣]',   # Question marks between letters (device???OS)
    r'[\x00-\x1f\x7f-\x9f]',            # Control characters
    r'\bp\d+_b\d+\b',                   # Block IDs (p3_b4)
    r'[가-힣]+\?+[가-힣]+',              # Korean with embedded question marks
    r'\?{3,}',                          # Three or more question marks anywhere
]


def _is_invalid_for_rendering(text: str, target_lang: str = "en") -> tuple[bool, str]:
    """
    Check if text contains invalid patterns that should NOT be rendered.

    This is the FINAL gate before rendering to PDF.
    Returns (is_invalid, reason)
    """
    if not text:
        return True, "empty_text"

    for pattern in INVALID_RENDER_PATTERNS:
        if re.search(pattern, text):
            return True, f"matched_pattern: {pattern}"

    # 영어 번역인데 한글 잔존 → invalid
    if target_lang == "en" and re.search(r'[가-힣]', text):
        return True, "korean_remaining_in_english"

    return False, ""

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

    term_definition role 색상 정책:
    - term_color: 원본 term 색상 (보통 빨강)
    - definition_color: 원본 definition 색상, 없으면 black (NEVER term_color)
    - 의미 구조 보존이 색상 보존보다 우선
    """
    translated = trans.get('translated', '')
    line_colors = trans.get('line_colors', [])
    role = trans.get('role', 'body')
    page_rect = page.rect

    # DEBUG: 함수 진입 확인
    block_id = trans.get('block_id', 'unknown')
    pdf_log_debug(f"[MultiColor-ENTER] {block_id}: translated='{translated}', line_colors={line_colors}")

    # 색상 준비
    first_color = (0, 0, 0)
    second_color = None  # None = not found

    if line_colors:
        colors = []
        for c in line_colors:
            if isinstance(c, int):
                colors.append(int_color_to_rgb(c))
            elif isinstance(c, (list, tuple)) and len(c) == 3:
                colors.append(tuple(c))
            else:
                colors.append((0, 0, 0))

        if colors:
            first_color = colors[0]
            # 두 번째 색상 찾기 (first_color와 다른 첫 번째 색상)
            for c in colors[1:]:
                if c != first_color:
                    second_color = c
                    break

    # "Term[구분자] Definition" 패턴 감지
    # 구분자로 인식할 문자: : ; → 등
    # 구분자로 인식하지 않을 문자 (제외):
    #   - (하이픈): decision-making, cost-benefit
    #   . (마침표): Dr., U.S.A., 3.14
    #   , (쉼표): 1,000, A, B, C
    #   ' (아포스트로피): don't, it's
    #   " (따옴표): "quoted"
    #   / (슬래시): and/or, I/O
    #   ( ) (괄호): (example)
    #   & (앰퍼샌드): Q&A, R&D
    #   @ # % + = _ (기타 일반 기호)
    excluded_chars = r'\-\.\,\'\"\/\(\)\&\@\#\%\+\=\_'
    match = re.search(rf'^([A-Za-z가-힣0-9\s{excluded_chars}]+?)([^A-Za-z가-힣0-9\s{excluded_chars}])\s*', translated)

    if not match:
        # 패턴 없으면 단색 textbox (배경과 대비 체크 + 폰트 축소로 bbox 내 맞춤)
        pdf_log_debug(f"[MultiColor] {block_id}: Term:Def 패턴 미감지, 단색 렌더링")
        bg_brightness = (bg_color[0] * 299 + bg_color[1] * 587 + bg_color[2] * 114) / 1000
        color_brightness = (first_color[0] * 299 + first_color[1] * 587 + first_color[2] * 114) / 1000
        if abs(bg_brightness - color_brightness) < 0.3:
            adjusted_color = (0, 0, 0) if bg_brightness > 0.5 else (1, 1, 1)
        else:
            adjusted_color = first_color

        # bbox 확장 없이 폰트 축소만으로 맞춤 (줄바꿈은 insert_textbox가 자동 처리)
        min_size = _get_min_font_size(role)
        for font_scale in [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.5, 0.4]:
            current_size = size * font_scale
            if current_size < min_size:
                current_size = min_size

            result = page.insert_textbox(
                rect, translated, fontname=font, fontsize=current_size,
                color=adjusted_color, align=fitz.TEXT_ALIGN_LEFT
            )
            if result >= 0:
                return result

        # 최후의 수단: 최소 크기로 시도
        return page.insert_textbox(
            rect, translated, fontname=font, fontsize=min_size,
            color=adjusted_color, align=fitz.TEXT_ALIGN_LEFT
        )

    term = match.group(1).strip() + match.group(2)  # Term + 구분자
    definition = translated[match.end():].strip()

    pdf_log_debug(f"[MultiColor] {block_id}: 패턴 감지 - term='{term}', definition='{definition}'")

    if not definition:
        # definition 없으면 term만 렌더링 (배경과 대비 체크)
        pdf_log_warning(f"[MultiColor] {block_id}: Definition 없음! term만 렌더링: '{term}'")
        bg_brightness = (bg_color[0] * 299 + bg_color[1] * 587 + bg_color[2] * 114) / 1000
        color_brightness = (first_color[0] * 299 + first_color[1] * 587 + first_color[2] * 114) / 1000
        if abs(bg_brightness - color_brightness) < 0.3:
            adjusted_color = (0, 0, 0) if bg_brightness > 0.5 else (1, 1, 1)
        else:
            adjusted_color = first_color
        page.insert_text(
            (rect.x0, rect.y0 + size), term,
            fontname=font, fontsize=size, color=adjusted_color
        )
        return 0

    # ===== 색상 정책 결정 =====
    # Term: Definition 패턴이 감지되면 (match가 존재하면):
    # - term: 원본 색상 (first_color, 보통 빨강)
    # - definition: 두 번째 색상이 있고 term과 다르면 사용, 없으면 black
    # - 의미 구조 보존이 색상 보존보다 우선 (role과 무관하게 적용)
    #
    # Term: Definition이 아닌 일반 multi-color:
    # - 기존 로직 유지

    # 배경 밝기 계산 (대비 체크용)
    bg_brightness = (bg_color[0] * 299 + bg_color[1] * 587 + bg_color[2] * 114) / 1000

    def ensure_contrast(color, bg_brightness):
        """배경과 대비가 충분하지 않으면 색상 조정"""
        color_brightness = (color[0] * 299 + color[1] * 587 + color[2] * 114) / 1000
        if abs(bg_brightness - color_brightness) < 0.3:
            return (0, 0, 0) if bg_brightness > 0.5 else (1, 1, 1)
        return color

    # 패턴이 매치되었으므로 Term: Definition 구조임
    # → definition은 반드시 term과 다른 색상 (없으면 black)
    term_color = ensure_contrast(first_color, bg_brightness)  # 대비 체크 후 색상

    # definition 색상 결정: second_color가 있고 term과 다르면 사용, 아니면 black
    if second_color is not None and second_color != first_color:
        def_color = ensure_contrast(second_color, bg_brightness)
    else:
        def_color = (0, 0, 0) if bg_brightness > 0.5 else (1, 1, 1)  # 배경에 맞는 기본색

    # DEBUG: 색상 결정 로그
    pdf_log_debug(f"[MultiColor] {block_id}: term='{term}', def='{definition[:50] if len(definition) > 50 else definition}'")
    pdf_log_debug(f"[MultiColor] {block_id}: line_colors={line_colors}, first_color={first_color}, second_color={second_color}")
    pdf_log_debug(f"[MultiColor] {block_id}: term_color={term_color}, def_color={def_color}")

    # Role 기반 최소 폰트 크기
    min_size = _get_min_font_size(role)

    # term > 40자 → 단색 textbox (안정적)
    if len(term) > 40:
        pdf_log_debug(f"[MultiColor] {block_id}: term {len(term)}자 > 40, 단색 fallback")
        for font_scale in [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4]:
            current_size = max(min_size, size * font_scale)
            result = page.insert_textbox(
                rect, translated,
                fontname=font, fontsize=current_size, color=term_color,
                align=fitz.TEXT_ALIGN_LEFT
            )
            if result >= 0:
                return result
        return page.insert_textbox(rect, translated, fontname=font, fontsize=min_size, color=term_color, align=fitz.TEXT_ALIGN_LEFT)

    # term ≤ 40자 → multi-color 시도
    font_scales = [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.5, 0.4]

    for font_scale in font_scales:
        current_size = max(min_size, size * font_scale)
        line_height = current_size * 1.2

        term_with_space = term + " "
        term_width = fitz.get_text_length(term_with_space, fontname=font, fontsize=current_size)
        full_width = fitz.get_text_length(term_with_space + definition, fontname=font, fontsize=current_size)

        # Strategy A: 같은 줄 multi-color (term + definition이 한 줄에 들어갈 때만)
        if full_width <= rect.width and line_height <= rect.height:
            baseline_y = rect.y0 + current_size
            page.insert_text((rect.x0, baseline_y), term_with_space, fontname=font, fontsize=current_size, color=term_color)
            page.insert_text((rect.x0 + term_width, baseline_y), definition, fontname=font, fontsize=current_size, color=def_color)
            pdf_log_debug(f"[MultiColor] {block_id}: Strategy A 성공, font_scale={font_scale}")
            return 0

        # Strategy B 비활성화: definition이 제대로 렌더링되지 않는 문제로 인해 비활성화
        # 대신 바로 Strategy C (단색 textbox)로 넘어감

    # Strategy C: 단색 fallback
    pdf_log_debug(f"[MultiColor] {block_id}: Strategy C fallback")
    for font_scale in [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4]:
        current_size = max(min_size, size * font_scale)

        result = page.insert_textbox(
            rect, translated,
            fontname=font, fontsize=current_size, color=(0, 0, 0),
            align=fitz.TEXT_ALIGN_LEFT
        )
        if result >= 0:
            pdf_log_debug(f"[MultiColor] {block_id}: Strategy C 성공, font_scale={font_scale}")
            return result

    # 최후의 수단: 최소 크기로 시도
    pdf_log_debug(f"[MultiColor] {block_id}: 최후 수단 {min_size}pt")
    return page.insert_textbox(
        rect, translated,
        fontname=font, fontsize=min_size, color=(0, 0, 0),
        align=fitz.TEXT_ALIGN_LEFT
    )



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
        "skipped_invalid": 0,  # Blocked by final rendering gate
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
                        trans["redaction_fill_color"] = (1, 1, 1)  # 저장
                        redaction_data.append((trans, rect))
                    else:
                        # 실제 이미지/다이어그램 배경: 해당 색으로 redaction
                        page.add_redact_annot(rect, fill=bg_color)
                        trans["redaction_fill_color"] = bg_color  # 저장
                        trans["expand_allowed"] = False
                        redaction_data.append((trans, rect))
                else:
                    # 일반 텍스트: 흰색 배경으로 redaction
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    trans["redaction_fill_color"] = (1, 1, 1)  # 저장
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
            elif result.status == "skipped_invalid":
                results["skipped_invalid"] += 1
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
            elif result.status == "skipped_invalid":
                results["skipped_invalid"] += 1
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

    # === FINAL RENDERING GATE ===
    # Check if translation contains invalid patterns (???, control chars, etc.)
    # If invalid, skip rendering entirely - do NOT render broken text to PDF
    is_invalid, invalid_reason = _is_invalid_for_rendering(translated)
    if is_invalid:
        result.status = "skipped_invalid"
        result.error = f"Invalid translation blocked: {invalid_reason}"
        logger.warning(f"[RENDER GATE] Blocked invalid text for {block_id}: '{translated[:50]}...' - {invalid_reason}")
        # Return without inserting any text - the redacted area will remain blank
        # This is intentional: blank is better than ???
        return result

    x0, y0, x1, y1 = bbox
    # prefix area skip (only when keep_prefix=True and prefix_width > 0)
    x0_adjusted = x0 + prefix_width if (keep_prefix and prefix_width > 0) else x0
    original_rect = fitz.Rect(x0_adjusted, y0, x1, y1)

    # 1. 배경 정보: redaction fill color 사용 (정확한 대비 체크를 위해)
    redaction_fill = trans.get("redaction_fill_color", (1, 1, 1))
    result.redaction_fill_color = redaction_fill

    # 이미지 위 텍스트 확인
    on_image = trans.get("on_image_background", False)
    if on_image:
        result.error = "Text on image background - may need review"

    # 2. 영어 폰트 및 색상 설정
    english_font = map_korean_to_english_font(original_font)
    original_text_color = int_color_to_rgb(color_int) if isinstance(color_int, int) else (0, 0, 0)

    # 배경색(redaction fill)과 텍스트색의 대비 확인 후 조정
    # 핵심: redaction fill color와 원본 텍스트 색상을 비교해야 함!
    bg_color = redaction_fill  # redaction 적용된 실제 배경색
    bg_brightness = (bg_color[0] * 299 + bg_color[1] * 587 + bg_color[2] * 114) / 1000
    text_brightness = (original_text_color[0] * 299 + original_text_color[1] * 587 + original_text_color[2] * 114) / 1000

    # 배경과 텍스트 밝기 차이가 0.3 미만이면 대비 부족 → 색상 조정
    if abs(bg_brightness - text_brightness) < 0.3:
        # 배경이 밝으면 검정, 어두우면 흰색
        text_color = (0, 0, 0) if bg_brightness > 0.5 else (1, 1, 1)
        pdf_log_debug(f"[Replace] {block_id}: 텍스트 색상 조정 (redaction_fill 기준): bg={bg_brightness:.2f}, text={text_brightness:.2f} → {text_color}")
    else:
        text_color = original_text_color
        pdf_log_debug(f"[Replace] {block_id}: 텍스트 색상 유지: bg={bg_brightness:.2f}, text={text_brightness:.2f}, color={text_color}")
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
    # multi-color 렌더러 사용 조건:
    # 1. has_multi_color=True (여러 색상 감지)
    # 2. role == "term_definition"
    # 3. 번역문에 "Term[구분자] Definition" 패턴이 있음
    # Term: 40자 이하, Definition: 5자 이상
    # 제외 문자: - . , ' " / ( ) & @ # % + = _
    _excluded = r'\-\.\,\'\"\/\(\)\&\@\#\%\+\=\_'
    has_term_definition_pattern = bool(re.match(rf'^[A-Za-z가-힣0-9\s{_excluded}]{{1,40}}[^A-Za-z가-힣0-9\s{_excluded}]\s*.{{5,}}', translated))
    use_multi_color_renderer = has_multi_color or role == "term_definition" or has_term_definition_pattern

    # DEBUG: multi-color 렌더러 호출 여부 확인
    pdf_log_debug(f"[Replace] {block_id}: original='{original[:30]}...' → translated='{translated[:50]}...'")
    pdf_log_debug(f"[Replace] {block_id}: has_multi_color={has_multi_color}, role={role}, has_pattern={has_term_definition_pattern}, use_renderer={use_multi_color_renderer}")

    if use_multi_color_renderer:
        # multi-color 렌더러가 모든 fallback을 내부적으로 처리
        # (같은 줄 → 두 줄 → bbox 확장 → 폰트 축소 → 단색 fallback)
        insert_result = _render_multi_color_text(
            page, trans, final_rect, english_font, final_size, redaction_fill
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

    # 단색 텍스트의 overflow 처리 (bbox 확장 없이 폰트 축소만)
    if insert_result < 0 and not use_multi_color_renderer:
        # 폰트 축소로 bbox 내에 맞춤 (확장 X)
        for font_scale in [0.9, 0.8, 0.7, 0.6, 0.5, 0.4]:
            smaller_size = max(6, final_size * font_scale)
            insert_result = page.insert_textbox(
                final_rect,
                translated,
                fontname=english_font,
                fontsize=smaller_size,
                color=text_color,
                align=fitz.TEXT_ALIGN_LEFT
            )
            if insert_result >= 0:
                result.insert_result = insert_result
                result.final_size = smaller_size
                break
        else:
            # 최후: 6pt로 시도
            insert_result = page.insert_textbox(
                final_rect, translated,
                fontname=english_font, fontsize=6,
                color=text_color, align=fitz.TEXT_ALIGN_LEFT
            )
            result.insert_result = insert_result
            result.final_size = 6

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
