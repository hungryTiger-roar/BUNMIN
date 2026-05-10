"""
PDF 폰트 핸들러

[역할]
- 한글 폰트 → 영어 폰트 매핑
- 색상 변환 (int → RGB tuple)

[호출 경로]
pdf_text_replacer.py → pdf_font_handler.py (이 파일)

[주요 함수]
- map_korean_to_english_font(): 한글 폰트명을 영어 폰트로 매핑
- int_color_to_rgb(): 정수 색상을 RGB tuple로 변환
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class FontInfo:
    """폰트 정보"""
    name: str
    size: float
    color: tuple  # (r, g, b) 0-1 범위
    is_bold: bool = False
    is_italic: bool = False


# 한글 폰트 → 영어 폰트 매핑
KOREAN_TO_ENGLISH_FONT = {
    # 고딕 계열 → Sans-serif
    "맑은고딕": "helvetica",
    "malgun gothic": "helvetica",
    "나눔고딕": "helvetica",
    "nanumgothic": "helvetica",
    "돋움": "helvetica",
    "dotum": "helvetica",
    "굴림": "helvetica",
    "gulim": "helvetica",
    "애플고딕": "helvetica",
    "applegothic": "helvetica",
    "고딕": "helvetica",
    "gothic": "helvetica",

    # 명조 계열 → Serif
    "바탕": "times-roman",
    "batang": "times-roman",
    "나눔명조": "times-roman",
    "nanummyeongjo": "times-roman",
    "명조": "times-roman",
    "myeongjo": "times-roman",

    # 기타
    "arial": "helvetica",
    "verdana": "helvetica",
    "tahoma": "helvetica",
}

# PyMuPDF 기본 폰트
PYMUPDF_FONTS = {
    "helvetica": "helv",
    "helvetica-bold": "hebo",
    "times-roman": "tiro",
    "times-bold": "tibo",
    "courier": "cour",
    "courier-bold": "cobo",
}


def map_korean_to_english_font(korean_font: str) -> str:
    """
    한글 폰트명을 영어 폰트로 매핑

    Args:
        korean_font: 원본 폰트명

    Returns:
        매핑된 영어 폰트명 (PyMuPDF용)
    """
    if not korean_font:
        return "helvetica"

    font_lower = korean_font.lower()

    # 직접 매핑 확인
    for korean, english in KOREAN_TO_ENGLISH_FONT.items():
        if korean in font_lower:
            return english

    # 키워드 기반 판단
    if any(x in font_lower for x in ["sans", "gothic", "돋움", "굴림", "고딕"]):
        return "helvetica"

    if any(x in font_lower for x in ["serif", "roman", "명조", "바탕"]):
        return "times-roman"

    if "mono" in font_lower or "courier" in font_lower:
        return "courier"

    # 기본값
    return "helvetica"


def get_pymupdf_fontname(font: str, bold: bool = False) -> str:
    """
    PyMuPDF에서 사용할 폰트명 반환

    Args:
        font: 폰트명 (helvetica, times-roman 등)
        bold: 볼드 여부

    Returns:
        PyMuPDF 폰트명
    """
    if bold and f"{font}-bold" in PYMUPDF_FONTS:
        return PYMUPDF_FONTS[f"{font}-bold"]

    return PYMUPDF_FONTS.get(font, "helv")


def calculate_adjusted_font_size(
    original_text: str,
    translated_text: str,
    original_size: float,
    bbox_width: float,
    min_size: float = 6.0,
    max_size: float = 72.0
) -> float:
    """
    번역된 텍스트에 맞는 폰트 크기 계산

    영어는 한글보다 평균적으로 1.3~1.5배 길어짐
    bbox 너비에 맞게 조정

    Args:
        original_text: 원본 한글 텍스트
        translated_text: 번역된 영어 텍스트
        original_size: 원본 폰트 크기
        bbox_width: 텍스트 박스 너비
        min_size: 최소 폰트 크기
        max_size: 최대 폰트 크기

    Returns:
        조정된 폰트 크기
    """
    if not original_text or not translated_text:
        return original_size

    # 글자당 평균 너비 비율 (경험적 수치)
    # 한글: 정사각형에 가까움 (비율 1.0)
    # 영어: 평균 0.5~0.6 (소문자 기준)
    KOREAN_CHAR_WIDTH = 1.0
    ENGLISH_CHAR_WIDTH = 0.55

    # 예상 너비 계산
    korean_width = len(original_text) * KOREAN_CHAR_WIDTH * original_size
    english_width = len(translated_text) * ENGLISH_CHAR_WIDTH * original_size

    # 조정이 필요없으면 원본 크기 유지
    if english_width <= korean_width:
        return min(original_size, max_size)

    # 비율에 맞게 축소
    ratio = korean_width / english_width
    adjusted_size = original_size * ratio

    # bbox 기반 추가 조정
    if bbox_width > 0:
        # bbox에 맞는 최대 크기 계산
        max_for_bbox = (bbox_width / (len(translated_text) * ENGLISH_CHAR_WIDTH)) * 0.9
        adjusted_size = min(adjusted_size, max_for_bbox)

    return max(min(adjusted_size, max_size), min_size)


def int_color_to_rgb(color_int: int) -> tuple:
    """
    정수 색상값을 RGB 튜플로 변환 (0-1 범위)

    Args:
        color_int: 정수 색상값 (예: 0xFF0000 = 빨강)

    Returns:
        (r, g, b) 튜플, 각 값은 0-1 범위
    """
    if not isinstance(color_int, int):
        return (0, 0, 0)

    r = ((color_int >> 16) & 0xFF) / 255.0
    g = ((color_int >> 8) & 0xFF) / 255.0
    b = (color_int & 0xFF) / 255.0

    return (r, g, b)


def rgb_to_int_color(r: float, g: float, b: float) -> int:
    """
    RGB 튜플을 정수 색상값으로 변환

    Args:
        r, g, b: 0-1 범위의 RGB 값

    Returns:
        정수 색상값
    """
    ri = int(min(max(r, 0), 1) * 255)
    gi = int(min(max(g, 0), 1) * 255)
    bi = int(min(max(b, 0), 1) * 255)

    return (ri << 16) | (gi << 8) | bi


def estimate_text_width(text: str, font_size: float, is_korean: bool = False) -> float:
    """
    텍스트 너비 추정

    Args:
        text: 텍스트
        font_size: 폰트 크기
        is_korean: 한글 여부

    Returns:
        추정 너비 (포인트)
    """
    char_width = 1.0 if is_korean else 0.55
    return len(text) * char_width * font_size


def estimate_text_height(font_size: float, line_count: int = 1) -> float:
    """
    텍스트 높이 추정

    Args:
        font_size: 폰트 크기
        line_count: 줄 수

    Returns:
        추정 높이 (포인트)
    """
    line_height = font_size * 1.2  # 기본 행간
    return line_height * line_count
