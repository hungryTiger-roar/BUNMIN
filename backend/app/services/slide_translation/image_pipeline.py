"""
이미지 기반 OCR 번역 파이프라인

[역할]
- 이미지/PDF(텍스트 레이어 없음)에 대한 OCR + VLM 번역
- Surya OCR로 텍스트 영역 감지
- VLM(Qwen2.5-VL)으로 번역
- OpenCV Inpainting으로 텍스트 오버레이

[호출 경로]
slides.py (router) → image_pipeline.py (이 파일)
mode.py (router) → image_pipeline.py (VLM 로드/언로드)
bbox_analyzer.py → image_pipeline.py (VLM 모델 공유)

[Public API]
이 모듈에서 외부로 노출하는 함수들:
- get_vlm_model(): VLM 모델 싱글톤 반환
- is_vlm_loaded(): VLM 로드 상태 확인
- unload_vlm_model(): VLM 메모리 해제 (slides.py에서 GPU 메모리 관리용으로 호출)
- stage_ocr_surya(): 단일 이미지 OCR
- stage_translate(): 단일 이미지 번역
- stage_overlay(): 단일 이미지 오버레이
- batch_ocr_surya(): 배치 OCR (Surya 한 번 로드)
- batch_translate_vlm(): 배치 번역 (VLM 한 번 로드)
- batch_overlay(): 배치 오버레이
- build_glossary_from_ocr_results(): 용어집 빌드
- clear_cache(): 캐시 삭제

[원본 파일]
teamRepo/translate_slide_v3.py에서 추출 (2091줄 → 주요 함수만)
"""

# =============================================================================
# Public API 명시
# =============================================================================
__all__ = [
    # VLM 모델 관리 (외부에서 GPU 메모리 관리용으로 호출 가능)
    "get_vlm_model",
    "is_vlm_loaded",
    "unload_vlm_model",
    # 단일 이미지 처리
    "stage_ocr_surya",
    "stage_translate",
    "stage_overlay",
    # 배치 처리 (slides.py에서 사용)
    "batch_ocr_surya",
    "batch_translate_vlm",
    "batch_overlay",
    # 유틸리티
    "build_glossary_from_ocr_results",
    "clear_cache",
]
import gc
import logging
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import torch
import yaml
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

from .term_corrections import get_terms_in_text

import sys as _sys_init
_BASE_DIR = Path(_sys_init.executable).parent if getattr(_sys_init, 'frozen', False) else Path(__file__).parent.parent.parent.parent.parent

# .env 로드
load_dotenv(_BASE_DIR / ".env")

# ============================================================
# 파일 로깅 설정
# ============================================================
LOG_DIR = _BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 로그 파일명: image_pipeline_YYYYMMDD.log
_log_date = datetime.now().strftime("%Y%m%d")
LOG_FILE = LOG_DIR / f"image_pipeline_{_log_date}.log"

# 로거 설정
_logger = logging.getLogger("image_pipeline")
_logger.setLevel(logging.DEBUG)

# 파일 핸들러 (상세 로그)
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(funcName)-25s | %(message)s",
    datefmt="%H:%M:%S"
)
_file_handler.setFormatter(_file_formatter)

# 콘솔 핸들러 (요약 로그)
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_formatter = logging.Formatter("%(message)s")
_console_handler.setFormatter(_console_formatter)

# 핸들러 중복 방지
if not _logger.handlers:
    _logger.addHandler(_file_handler)
    _logger.addHandler(_console_handler)

def log_debug(msg: str):
    """디버그 로그 (파일에만 기록)"""
    _logger.debug(msg)

def log_info(msg: str):
    """정보 로그 (파일 + 콘솔)"""
    _logger.info(msg)

def log_warning(msg: str):
    """경고 로그 (파일 + 콘솔)"""
    _logger.warning(msg)

def log_error(msg: str):
    """에러 로그 (파일 + 콘솔)"""
    _logger.error(msg)


# ============================================================
# 설정 관리
# ============================================================
_config = None

def get_config():
    """config.yaml 로드 (싱글톤)"""
    global _config
    if _config is not None:
        return _config

    config_path = _BASE_DIR / "backend" / "config.yaml"
    if not config_path.exists():
        config_path = _BASE_DIR / "config.yaml"

    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            _config = yaml.safe_load(f)
    else:
        _config = {}

    return _config


def cfg(key: str, default=None):
    """설정값 조회 (점 표기법 지원)"""
    config = get_config()
    keys = key.split('.')
    value = config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value


# ============================================================
# 용어집 빌더
# ============================================================
_glossary_builder = None

def get_glossary_builder():
    """GlossaryBuilder 싱글톤 반환"""
    global _glossary_builder
    if _glossary_builder is None:
        try:
            from backend.app.services.glossary_builder import GlossaryBuilder
            _glossary_builder = GlossaryBuilder()
        except Exception as e:
            print(f"[Glossary] GlossaryBuilder 로드 실패: {e}")
            _glossary_builder = False
    return _glossary_builder if _glossary_builder else None


def build_glossary_from_ocr_results(ocr_results: list, lecture_title: str = "Lecture") -> dict:
    """
    전체 슬라이드 OCR 결과에서 용어집 빌드

    Args:
        ocr_results: [(image_path, regions), ...] OCR 결과 리스트
        lecture_title: 강의 제목

    Returns:
        dict: {한글: 영어} 전문용어 매핑
    """
    builder = get_glossary_builder()
    if not builder:
        return {}

    all_texts = []
    for image_path, regions in ocr_results:
        if regions:
            for r in regions:
                text = r.get("ocr_text", "")
                if text:
                    all_texts.append(text)

    if not all_texts:
        return {}

    try:
        return builder.build_glossary(all_texts, lecture_title)
    except Exception as e:
        print(f"[Glossary] 빌드 실패: {e}")
        return {}


# VLM 프롬프트에 포함할 용어집 최대 항목 수
# - VLM 입력 토큰 길이 제한 (Qwen2.5-VL: 8192 tokens)
# - 용어집이 너무 길면 번역할 텍스트가 잘릴 수 있음
# - 25개 × ~30 chars ≈ 750 chars → 안전한 범위
MAX_GLOSSARY_ITEMS = 25


def select_glossary_items(
    glossary: dict,
    max_items: int = None,
    context_texts: list[str] = None
) -> list[tuple[str, str]]:
    """
    VLM 프롬프트에 포함할 용어집 항목 선택

    선택 전략 (우선순위):
    1. CSV 용어집에서 현재 페이지에 등장하는 용어 (최우선)
    2. 입력 glossary에서 현재 페이지에 등장하는 용어
    3. 나머지는 원래 순서대로 (빌드 시 빈도/중요도 순 정렬됨)

    Args:
        glossary: {한글: 영어} 용어집
        max_items: 최대 항목 수 (기본: MAX_GLOSSARY_ITEMS)
        context_texts: 현재 페이지의 OCR 텍스트 리스트 (우선순위 판단용)

    Returns:
        [(한글, 영어), ...] 선택된 항목 리스트
    """
    max_items = max_items or MAX_GLOSSARY_ITEMS

    # CSV 용어집에서 현재 페이지에 등장하는 용어 추출
    csv_terms = {}
    if context_texts:
        all_text = " ".join(context_texts)
        csv_terms = get_terms_in_text(all_text)

    # 입력 glossary와 CSV 용어 병합 (CSV가 우선)
    merged = dict(glossary) if glossary else {}
    merged.update(csv_terms)  # CSV 용어가 덮어씀

    if not merged:
        return []

    items = list(merged.items())

    if len(items) <= max_items:
        return items

    # context_texts가 제공되면 현재 페이지에 등장하는 용어 우선 선택
    if context_texts:
        # any() + generator로 short-circuit 평가 (대용량 텍스트 성능 최적화)
        in_context = []
        not_in_context = []

        for ko, en in items:
            if any(ko in text for text in context_texts):
                in_context.append((ko, en))
            else:
                not_in_context.append((ko, en))

        # 등장하는 용어 먼저, 나머지는 원래 순서
        prioritized = in_context + not_in_context
        return prioritized[:max_items]

    return items[:max_items]


# ============================================================
# VLM 모델 관리
# ============================================================
_PROJECT_ROOT = _BASE_DIR
_VLM_WEIGHT_EXTS = (".safetensors", ".bin")


def _has_vlm_weights(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    for ext in _VLM_WEIGHT_EXTS:
        try:
            if next(directory.rglob(f"*{ext}"), None) is not None:
                return True
        except (OSError, PermissionError):
            continue
    return False


def _vlm_default() -> str:
    local = _PROJECT_ROOT / "models" / "qwen2.5-vl-7b-instruct"
    if _has_vlm_weights(local):
        return str(local)
    return "Qwen/Qwen2.5-VL-7B-Instruct"


def _resolve_vlm(value: str) -> str:
    p = Path(value)
    if p.is_absolute():
        if _has_vlm_weights(p):
            return value
        return _vlm_default()
    candidate = _PROJECT_ROOT / value
    if _has_vlm_weights(candidate):
        return str(candidate)
    if value.startswith(("models/", "models\\", "./", "../", ".\\", "..\\")):
        return _vlm_default()
    return value


VLM_BASE_MODEL = _resolve_vlm(os.environ.get("VLM_BASE_MODEL") or _vlm_default())
VLM_DEVICE = os.environ.get("VLM_DEVICE", "cuda")
VLM_USE_4BIT = os.environ.get("VLM_USE_4BIT", "true").lower() == "true"

_vlm_model = None
_vlm_processor = None


def get_vlm_model():
    """VLM 모델 싱글톤 - 최초 1회만 로드"""
    global _vlm_model, _vlm_processor

    if _vlm_model is not None:
        return _vlm_model, _vlm_processor

    if not torch.cuda.is_available():
        raise RuntimeError("VLM 번역에는 NVIDIA GPU(CUDA)가 필요합니다.")

    from transformers import AutoProcessor, AutoModelForImageTextToText, BitsAndBytesConfig

    print(f"[VLM] 모델 최초 로드 중... (4bit={VLM_USE_4BIT})")
    print(f"[VLM] Base: {VLM_BASE_MODEL}")

    if VLM_USE_4BIT:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        model_kwargs = {
            "quantization_config": bnb_config,
            "device_map": {"": 0},
            "trust_remote_code": True,
        }
    else:
        model_kwargs = {
            "torch_dtype": torch.float16,
            "device_map": {"": 0},
            "trust_remote_code": True,
        }

    _vlm_processor = AutoProcessor.from_pretrained(
        VLM_BASE_MODEL,
        trust_remote_code=True,
        min_pixels=128 * 28 * 28,
        max_pixels=256 * 28 * 28,
    )

    _vlm_model = AutoModelForImageTextToText.from_pretrained(
        VLM_BASE_MODEL,
        **model_kwargs,
    )
    _vlm_model.eval()

    print("[VLM] 모델 로드 완료!")
    return _vlm_model, _vlm_processor


def is_vlm_loaded() -> bool:
    """VLM 모델 로드 여부 확인"""
    return _vlm_model is not None


def unload_vlm_model():
    """VLM 모델 언로드 (GPU 메모리 해제)"""
    global _vlm_model, _vlm_processor

    if _vlm_model is None:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return

    print("[VLM] 모델 언로드 중...")
    del _vlm_model
    del _vlm_processor
    _vlm_model = None
    _vlm_processor = None

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("[VLM] VRAM 해제 완료")


# ============================================================
# 텍스트 필터링 유틸리티
# ============================================================
def is_number_or_english_only(text: str) -> bool:
    """숫자, 영어, 기호만 있는지 확인"""
    if re.search(r'[가-힣]', text):
        return False
    return bool(re.match(r'^[0-9a-zA-Z\s\.\,\-\_\:\;\!\?\@\#\$\%\&\*\(\)\[\]\{\}\/\\]+$', text))


def is_chinese_garbage(text: str) -> bool:
    """한자 오인식 감지"""
    if not cfg('ocr_filters.enable_hanja_filter', True):
        return False
    text = text.strip()
    if not text or re.search(r'[가-힣]', text):
        return False
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    if not chinese_chars:
        return False
    text_without_space = re.sub(r'\s+', '', text)
    if len(text_without_space) <= 3 and len(chinese_chars) >= 1:
        return True
    if len(text_without_space) <= 5 and len(chinese_chars) >= len(text_without_space) * 0.4:
        return True
    if len(chinese_chars) >= len(text_without_space) * 0.6:
        return True
    return False


def is_passthrough_content(text: str) -> bool:
    """번역 없이 유지할 콘텐츠 (이메일, URL 등)"""
    if re.search(r'[가-힣]', text):
        return False
    if re.search(r'[\w\.\-\+]+@[\w\.\-]+\.\w+', text):
        return True
    if re.search(r'https?://[\w\.\-/\?\=\&\#]+', text):
        return True
    if re.search(r'[A-Za-z]:\\[A-Za-z0-9_\s\\/\.]+|^/[A-Za-z0-9_/\.]+$', text):
        return True
    if re.search(r'^\s*[\d\+\-\*\/\=\(\)\^\s\.]+\s*$', text):
        return True
    return False


def contains_math_markup(text: str) -> bool:
    """수식 마크업 포함 여부"""
    return bool(re.search(r'<math|</math>|\\frac|\\sum|\\int|\\sqrt|display="', text))


def strip_math_markup(text: str) -> str:
    """수식 마크업 제거"""
    result = re.sub(r'<math>.*?</math>', ' → ', text, flags=re.DOTALL)
    result = re.sub(r'<math>[^<]*', ' → ', result)
    result = re.sub(r'\\(frac|sum|int|sqrt|rightarrow|leftarrow)\b[^a-zA-Z]*', ' ', result)
    result = re.sub(r'\s+', ' ', result)
    result = re.sub(r'(→\s*)+', '→ ', result)
    return result.strip()


def strip_html_tags(text: str) -> str:
    """HTML 태그 제거"""
    if not text:
        return text
    result = re.sub(r'</?(?:mark|b|i|em|strong|u|s|sub|sup|span|div|font)[^>]*>', '', text, flags=re.IGNORECASE)
    result = re.sub(r'</?(?!math)[a-zA-Z][^>]*>', '', result, flags=re.IGNORECASE)
    result = re.sub(r'<[^>]+/>', '', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def normalize_ocr_text(text: str) -> str:
    """OCR 출력 정규화"""
    if not text:
        return text
    text = strip_html_tags(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_code_block(text: str) -> bool:
    """프로그래밍 코드 영역 감지"""
    code_patterns = cfg('code_patterns', [
        r'#include\s*<', r'using\s+namespace', r'\bint\s+main\s*\(',
        r'\bcout\s*<<', r'\bcin\s*>>', r'\bprintf\s*\(', r'\bscanf\s*\(',
        r'\breturn\s+\d+;', r'%[dfsclx]', r'\\n["\']', r'<<\s*endl',
    ])
    for pattern in code_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def is_single_char_korean(text: str) -> bool:
    """1글자 한글만 있는지 확인"""
    text = text.strip()
    return len(text) == 1 and bool(re.match(r'^[가-힣]$', text))


def has_korean(text: str) -> bool:
    """한글 포함 여부"""
    return bool(re.search(r'[가-힣]', text))


def is_leaked_prompt(text: str) -> bool:
    """VLM이 프롬프트 지시문을 그대로 반환했는지 감지"""
    if not text:
        return False
    lower = text.lower()
    # VLM 프롬프트 지시문 패턴 감지
    prompt_patterns = [
        "output exactly",
        "format: ",
        "1. translation",
        "translate:",
        "rules:",
        "glossary:",
        "page context:",
        "[translate]",
        "[glossary]",
        "[rules]",
    ]
    return any(p in lower for p in prompt_patterns)


def is_vertical_text_region(bbox: list, text: str) -> bool:
    """세로 텍스트 영역 감지"""
    x_min, y_min, x_max, y_max = bbox
    width = x_max - x_min
    height = y_max - y_min
    clean_text = re.sub(r'\s+', '', strip_html_tags(text))
    if len(clean_text) < 2:
        return False
    korean_chars = re.findall(r'[가-힣]', clean_text)
    if not korean_chars:
        return False
    korean_ratio = len(korean_chars) / max(1, len(clean_text))
    if korean_ratio < 0.6:
        return False
    return height > width * 2.5 and width < 80


def split_br_lines(text: str) -> list:
    """<br> 태그로 분리"""
    if '<br>' in text.lower():
        lines = re.split(r'<br\s*/?>', text, flags=re.IGNORECASE)
        return [line.strip() for line in lines if line.strip()]
    return [text]


def extract_korean_in_quotes(text: str) -> list:
    """코드 내 따옴표 안의 한글 추출"""
    quote_chars = r'["\'\"\"\'\']'
    pattern = rf'{quote_chars}([^"\'\"\"\'\']*?[가-힣]+[^"\'\"\"\'\']*?){quote_chars}'
    return re.findall(pattern, text)


# ============================================================
# Prefix 기호 처리
# ============================================================
DEFAULT_PIXEL_PRESERVE_PREFIXES = {
    "☑", "☐", "□", "■", "✓", "✔", "✗", "✘",
    "📦", "📌", "🔹", "🔸", "✅", "⚠️", "💡", "📍",
    "🔴", "🟢", "🔵", "⭐", "🎯", "📝", "📋", "🚀", "⚡", "🔥",
}

DEFAULT_FORCE_RENDER_PREFIXES = {
    "-", ">", "›", "•", "◦", "○", "●", "·", "ㆍ",
    "▶", "►", "※", "★", "☆",
}

PREFIX_SYMBOLS = [
    '▶ ', '► ', '› ', '> ', '▶', '►', '›',
    '• ', '◦ ', '○ ', '● ', '· ', 'ㆍ ', '- ',
    '•', '◦', '○', '●', '·', 'ㆍ',
    '☐ ', '☑ ', '□ ', '■ ', '☐', '☑', '□', '■',
    '※ ', '★ ', '☆ ', '※', '★', '☆',
]


def get_pixel_preserve_prefixes() -> set:
    configured = cfg("prefix_symbols.pixel_preserve_prefixes", None)
    return set(configured) if configured else DEFAULT_PIXEL_PRESERVE_PREFIXES


def get_force_render_prefixes() -> set:
    configured = cfg("prefix_symbols.force_render_prefixes", None)
    return set(configured) if configured else DEFAULT_FORCE_RENDER_PREFIXES


def get_prefix_policy(prefix: str) -> str:
    """prefix 기호의 처리 정책 결정"""
    if not prefix:
        return "none"
    symbol = prefix.strip()
    if not symbol:
        return "none"
    force_render = get_force_render_prefixes()
    pixel_preserve = get_pixel_preserve_prefixes()
    if any(symbol.startswith(p) for p in force_render):
        return "render"
    if any(symbol.startswith(p) for p in pixel_preserve):
        return "preserve"
    return cfg("prefix_symbols.default_policy", "render")


def is_prefix_symbol_char(ch: str) -> bool:
    """불렛/체크박스/기호/이모지 prefix 판별"""
    if not ch:
        return False
    category = unicodedata.category(ch)
    if category in ("So", "Sm", "Sk"):
        return True
    code = ord(ch)
    emoji_ranges = [(0x2600, 0x27BF), (0x1F300, 0x1F9FF)]
    return any(start <= code <= end for start, end in emoji_ranges)


def extract_prefix_symbol(text: str) -> tuple:
    """텍스트에서 접두 기호 분리"""
    text_stripped = text.strip()
    if not text_stripped:
        return ('', text_stripped)
    for symbol in PREFIX_SYMBOLS:
        if text_stripped.startswith(symbol):
            content = text_stripped[len(symbol):].strip()
            prefix = symbol if symbol.endswith(' ') else symbol + ' '
            return (prefix, content)
    first_char = text_stripped[0]
    if is_prefix_symbol_char(first_char):
        content = text_stripped[1:].strip()
        if content:
            return (first_char + ' ', content)
    return ('', text_stripped)


def restore_prefix_symbol(prefix: str, translated: str) -> str:
    """번역된 텍스트에 원본 접두 기호 복원"""
    if not prefix:
        return translated
    translated_clean = translated.strip()
    for symbol in PREFIX_SYMBOLS:
        if translated_clean.startswith(symbol):
            translated_clean = translated_clean[len(symbol):].strip()
            break
    if translated_clean and is_prefix_symbol_char(translated_clean[0]):
        translated_clean = translated_clean[1:].strip()
    return prefix + translated_clean


def estimate_prefix_pixel_width(prefix: str, bbox: list, img_np=None) -> int:
    """보존할 접두 기호의 픽셀 너비 추정"""
    if not prefix or not prefix.strip():
        return 0
    x1, y1, x2, y2 = bbox
    height = y2 - y1
    region_width = x2 - x1
    ratio = cfg("prefix_symbols.preserve_width.fallback_height_ratio", 0.9)
    min_px = cfg("prefix_symbols.preserve_width.min_px", 10)
    max_region_ratio = cfg("prefix_symbols.preserve_width.max_region_ratio", 0.25)
    estimated = int(height * ratio)
    estimated = max(min_px, estimated)
    estimated = min(estimated, int(region_width * max_region_ratio))
    return estimated


# ============================================================
# 영역 병합 및 분류
# ============================================================
def is_incomplete_sentence(text: str) -> bool:
    """문장이 불완전하게 끝났는지 판단"""
    text = text.strip()
    if not text:
        return False
    if text[-1] in '.?!。':
        return False
    if text[-1] in ')）]】':
        return False
    if re.match(r'^\d+[\.\)]\s*.{1,15}$', text):
        return False
    if re.match(r'^[QA]\d+', text):
        return False
    if re.match(r'.*[A-Z]{2,}(\s*\([^)]+\))?\s*$', text):
        return False
    last_char = text[-1]
    if re.match(r'[가-힣]', last_char):
        if not re.search(r'(다|요|죠|음|함|임|됨|니다|세요|습니다|입니다)$', text):
            return True
    return False


def merge_adjacent_regions(regions: list, threshold_y: int = 20) -> list:
    """인접한 불완전 문장 영역 병합"""
    if not regions:
        return regions
    sorted_regions = sorted(regions, key=lambda r: (r['bbox'][1], r['bbox'][0]))
    merged = []
    current = None

    for region in sorted_regions:
        if current is None:
            current = region.copy()
            continue
        curr_bbox = region['bbox']
        prev_bbox = current['bbox']
        y_gap = curr_bbox[1] - prev_bbox[3]
        y_adjacent = 0 <= y_gap <= threshold_y
        x_diff = abs(curr_bbox[0] - prev_bbox[0])
        x_aligned = x_diff < 50
        prev_incomplete = is_incomplete_sentence(current['ocr_text'])
        curr_text = region['ocr_text'].strip()
        starts_with_bullet = bool(re.match(r'^[•●▶☐◦○■□※★☆\-]\s*', curr_text))
        starts_with_number = bool(re.match(r'^\d+[\.\)]\s+', curr_text))
        starts_with_section = bool(re.match(r'^[QA]\d+|^\d{2}\s+[가-힣A-Z]', curr_text))
        should_merge = (
            y_adjacent and x_aligned and prev_incomplete and
            not starts_with_bullet and not starts_with_number and not starts_with_section and
            not current.get('skip_translate', False) and not region.get('skip_translate', False)
        )
        if should_merge:
            current['ocr_text'] = current['ocr_text'].rstrip() + ' ' + region['ocr_text'].lstrip()
            current['bbox'] = [
                min(prev_bbox[0], curr_bbox[0]), prev_bbox[1],
                max(prev_bbox[2], curr_bbox[2]), curr_bbox[3]
            ]
            current['confidence'] = min(current.get('confidence', 1.0), region.get('confidence', 1.0))
        else:
            merged.append(current)
            current = region.copy()

    if current:
        merged.append(current)
    return merged


def classify_text_regions(regions: list, image_size: tuple) -> list:
    """텍스트 영역을 레이아웃 특성에 따라 분류"""
    if not regions:
        return regions
    image_width, image_height = image_size
    all_bboxes = [r["bbox"] for r in regions if "bbox" in r]

    def has_nearby_regions(bbox, threshold=50):
        x_min, y_min, x_max, y_max = bbox
        center_x = (x_min + x_max) / 2
        center_y = (y_min + y_max) / 2
        nearby_count = 0
        for other_bbox in all_bboxes:
            if other_bbox == bbox:
                continue
            ox_min, oy_min, ox_max, oy_max = other_bbox
            other_center_x = (ox_min + ox_max) / 2
            other_center_y = (oy_min + oy_max) / 2
            distance = ((center_x - other_center_x) ** 2 + (center_y - other_center_y) ** 2) ** 0.5
            if distance < threshold:
                nearby_count += 1
        return nearby_count > 0

    nearby_threshold = cfg("layout.nearby_threshold", 50)
    for region in regions:
        if "bbox" not in region:
            continue
        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min
        area = width * height
        text = region.get("ocr_text", "")
        char_count = len(re.sub(r'\s+', '', text))
        density = char_count / max(1, area) * 10000
        is_isolated = not has_nearby_regions(bbox, nearby_threshold)
        is_small = area < 3000
        is_short = char_count < 5
        if is_isolated and is_small and is_short:
            region["text_class"] = "STRICT_LITERAL"
        else:
            region["text_class"] = "CONTEXT_AWARE"
    return regions


# ============================================================
# 1단계: OCR (Surya)
# ============================================================
def stage_ocr_surya(image_path: str) -> list:
    """Surya OCR로 텍스트 영역 추출"""
    print("\n" + "=" * 60)
    print("[1/3] OCR: 텍스트 영역 감지 (Surya OCR)")
    print("=" * 60)

    # GPU 메모리 정리 (VLM 등 이전 모델 해제)
    print("  GPU 메모리 정리 중...")
    unload_vlm_model()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()

    from surya.foundation import FoundationPredictor
    from surya.detection import DetectionPredictor
    from surya.recognition import RecognitionPredictor

    image = Image.open(image_path).convert("RGB")
    print(f"  이미지 크기: {image.size[0]}x{image.size[1]}px")

    print("  Surya 모델 로드 중...")
    foundation_predictor = FoundationPredictor()
    det_predictor = DetectionPredictor()
    rec_predictor = RecognitionPredictor(foundation_predictor)

    print("  텍스트 영역 감지 중...")
    rec_results = rec_predictor([image], det_predictor=det_predictor)

    regions = []
    skipped_low_conf = 0

    for page_result in rec_results:
        for line in page_result.text_lines:
            text = normalize_ocr_text(line.text.strip())
            confidence = line.confidence

            if not text or confidence < 0.2:
                if confidence < 0.2:
                    skipped_low_conf += 1
                continue

            bbox = [float(line.bbox[0]), float(line.bbox[1]), float(line.bbox[2]), float(line.bbox[3])]
            skip_translate = is_number_or_english_only(text)
            passthrough = is_passthrough_content(text)
            has_math = contains_math_markup(text)
            is_code = is_code_block(text)
            is_single_char = is_single_char_korean(text)
            is_chinese = is_chinese_garbage(text)
            text_has_korean = has_korean(text)
            math_skip = has_math and not text_has_korean

            regions.append({
                "bbox": bbox,
                "ocr_text": text,
                "confidence": float(confidence),
                "skip_translate": skip_translate or passthrough or math_skip or is_code or is_chinese,
                "passthrough": passthrough,
                "has_math": has_math,
                "is_code": is_code,
                "is_single_char": is_single_char,
                "is_chinese": is_chinese,
            })

    print(f"\n  총 {len(regions)}개 영역 감지")

    # Surya 모델 메모리 해제 (VLM 로드 준비)
    del foundation_predictor, det_predictor, rec_predictor
    del image
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    print("  Surya 모델 메모리 해제 완료")

    return regions


# ============================================================
# 2단계: 번역 (VLM)
# ============================================================
def stage_translate(image_path: str, regions: list, glossary: dict = None) -> list:
    """VLM으로 번역"""
    log_info("\n" + "=" * 60)
    log_info("[2/3] 번역: VLM")
    log_info("=" * 60)
    log_debug(f"[stage_translate] 시작: {image_path}")
    log_debug(f"  입력 regions: {len(regions)}개, glossary: {len(glossary) if glossary else 0}개")

    original_image = Image.open(image_path).convert("RGB")
    image_size = original_image.size
    regions = merge_adjacent_regions(regions)
    regions = classify_text_regions(regions, image_size)

    to_translate = []
    for i, region in enumerate(regions):
        if region.get("skip_translate", False):
            region["english"] = region["ocr_text"]
            log_debug(f"  [Region {i}] 스킵 (skip_translate): {region['ocr_text'][:30]}...")
            continue
        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min
        min_area = cfg('ocr.min_area', 500)
        if width * height < min_area:
            region["english"] = region["ocr_text"]
            log_debug(f"  [Region {i}] 스킵 (영역 작음 {width*height:.0f}px²): {region['ocr_text'][:30]}...")
            continue
        br_lines = split_br_lines(region["ocr_text"])
        if len(br_lines) > 1:
            region["br_lines"] = br_lines
        to_translate.append((i, region))
        log_debug(f"  [Region {i}] 번역 대상: {region['ocr_text'][:50]}...")

    if not to_translate:
        log_info("  번역할 텍스트 없음")
        return regions

    log_info(f"\n  번역 대상: {len(to_translate)}개")

    model, processor = get_vlm_model()

    text_lines = []
    line_mapping = []
    prefix_mapping = {}

    for idx, (orig_idx, region) in enumerate(to_translate):
        br_lines = region.get('br_lines')
        region_has_math = region.get('has_math', False)
        if br_lines and len(br_lines) > 1:
            for br_idx, br_line in enumerate(br_lines):
                line_num = len(text_lines) + 1
                br_line = strip_html_tags(br_line)
                clean_line = strip_math_markup(br_line) if region_has_math else br_line
                prefix, content = extract_prefix_symbol(clean_line)
                if prefix:
                    prefix_mapping[line_num] = prefix
                text_lines.append(f"{line_num}. {content}")
                line_mapping.append((orig_idx, br_idx, None))
        else:
            line_num = len(text_lines) + 1
            ocr_text = strip_html_tags(region['ocr_text'])
            clean_text = strip_math_markup(ocr_text) if region_has_math else ocr_text
            prefix, content = extract_prefix_symbol(clean_text)
            if prefix:
                prefix_mapping[line_num] = prefix
            text_lines.append(f"{line_num}. {content}")
            line_mapping.append((orig_idx, None, None))

    text_list = "\n".join(text_lines)
    total_lines = len(text_lines)
    page_context_items = [r["ocr_text"] for r in regions if r.get("ocr_text")]
    page_context = ", ".join(page_context_items[:20])

    glossary_section = ""
    if glossary:
        selected_glossary = select_glossary_items(glossary, context_texts=page_context_items)
        glossary_lines = [f'  "{ko}": "{en}"' for ko, en in selected_glossary]
        glossary_section = "\n[GLOSSARY]\n" + "\n".join(glossary_lines) + "\n"

    PROMPT = f"""Translate Korean to English for a lecture slide.

[PAGE CONTEXT]
{page_context}
{glossary_section}
[TRANSLATE]
{text_list}

RULES:
1. Output EXACTLY {total_lines} lines, format: "1. translation"
2. Use PAGE CONTEXT to disambiguate ambiguous/short terms
3. Use GLOSSARY translations for technical terms if provided
4. Standard academic terminology
5. Never romanize - translate to English
6. KEEP: emails, URLs, filenames, code syntax
7. SHORT labels → CONCISE translation

Translate:"""

    messages = [{"role": "user", "content": [{"type": "text", "text": PROMPT}]}]

    try:
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(**inputs, max_new_tokens=2048, temperature=0.3, do_sample=True)

    input_len = inputs["input_ids"].shape[1]
    output_len = outputs[0].shape[0] - input_len
    response = processor.decode(outputs[0][input_len:], skip_special_tokens=True).strip()

    # 로그: VLM 응답 원본
    log_debug(f"[VLM Response] 원본 응답 ({len(response)} chars, {output_len} tokens):\n{response}")

    # 텍스트 잘림 감지 (출력 토큰이 max_new_tokens에 가까우면 경고)
    MAX_NEW_TOKENS = 2048
    if output_len >= MAX_NEW_TOKENS - 10:
        log_warning(f"[VLM] 응답이 잘렸을 수 있음! output_tokens={output_len}/{MAX_NEW_TOKENS}")

    # 프롬프트 유출 감지
    if is_leaked_prompt(response):
        log_warning(f"[VLM] 프롬프트 유출 감지! 원본 텍스트 유지")
        for _, (orig_idx, region) in enumerate(to_translate):
            region["english"] = region["ocr_text"]
        return regions

    # 응답 파싱 (다양한 형식 지원)
    lines = response.strip().split("\n")
    translation_map = {}
    unparsed_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 패턴 1: "1. translation" 또는 "1) translation" 또는 "1: translation"
        match = re.match(r'^(\d+)\s*[\.:\)\-]\s*(.+)$', line)
        if match:
            try:
                num = int(match.group(1))
                trans = match.group(2).strip().strip('"\'')
                if trans:
                    translation_map[num] = trans
                    log_debug(f"  [Parse] Line {num}: {trans[:50]}...")
            except ValueError:
                unparsed_lines.append(line)
        else:
            unparsed_lines.append(line)

    # 파싱 실패한 라인 로그
    if unparsed_lines:
        log_warning(f"[VLM] 파싱 실패 라인 {len(unparsed_lines)}개:")
        for ul in unparsed_lines[:5]:  # 최대 5개만 로그
            log_warning(f"  → {ul[:80]}...")

    valid_map = {k: v for k, v in translation_map.items() if 1 <= k <= total_lines}
    log_debug(f"[VLM] 파싱 결과: {len(valid_map)}/{total_lines} 라인 매핑됨")

    # 매핑 누락 경고
    missing_lines = [i for i in range(1, total_lines + 1) if i not in valid_map]
    if missing_lines:
        log_warning(f"[VLM] 번역 누락된 라인: {missing_lines}")

    region_translations = {}
    for line_num, (region_idx, br_idx, code_string) in enumerate(line_mapping, start=1):
        if line_num in valid_map:
            trans = valid_map[line_num]
            trans = re.sub(r'^\d+\s*[\.:\)\-]\s*', '', trans)
            trans = re.sub(r'<br\s*/?>', ' ', trans)
            trans = re.sub(r'\s+', ' ', trans).strip()

            # 개별 번역 결과도 프롬프트 유출 체크
            if is_leaked_prompt(trans):
                log_warning(f"  [Line {line_num}] 프롬프트 유출 감지, 스킵")
                continue

            if code_string is None and line_num in prefix_mapping:
                trans = restore_prefix_symbol(prefix_mapping[line_num], trans)
            if br_idx is not None:
                if region_idx not in region_translations:
                    region_translations[region_idx] = []
                region_translations[region_idx].append(trans)
            else:
                region_translations[region_idx] = trans

    for idx, (region_idx, region) in enumerate(to_translate):
        if region_idx in region_translations:
            trans_result = region_translations[region_idx]
            if isinstance(trans_result, list):
                english = " / ".join(trans_result)
            else:
                english = trans_result
            final_english = strip_html_tags(english.strip())
            region["english"] = final_english
            log_debug(f"  [Region {region_idx}] '{region['ocr_text'][:30]}...' → '{final_english[:30]}...'")
        else:
            region["english"] = region["ocr_text"]
            log_debug(f"  [Region {region_idx}] 번역 없음, 원본 유지: '{region['ocr_text'][:30]}...'")

    # 세로 텍스트 감지
    for region in regions:
        if region.get("skip_translate"):
            continue
        bbox = region.get("bbox", [0, 0, 0, 0])
        ocr_text = region.get("ocr_text", "")
        if is_vertical_text_region(bbox, ocr_text):
            region["is_vertical"] = True
            region["render_skip"] = True

    del original_image
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return regions


# ============================================================
# 3단계: 오버레이
# ============================================================
def stage_overlay(image_path: str, regions: list, output_path: str):
    """번역된 텍스트 오버레이"""
    log_info("\n" + "=" * 60)
    log_info("[3/3] 오버레이: Inpainting + 텍스트 렌더링")
    log_info("=" * 60)
    log_debug(f"[stage_overlay] 시작: {image_path} → {output_path}")
    log_debug(f"  입력 regions: {len(regions)}개")

    img = Image.open(image_path).convert("RGB")
    img_np = np.array(img)
    mask = np.zeros(img_np.shape[:2], dtype=np.uint8)
    translate_regions = []

    def get_font(size):
        font_paths = [
            "C:/Windows/Fonts/NotoSansKR-Regular.ttf",
            "C:/Windows/Fonts/malgun.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for font_path in font_paths:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def wrap_text_words_only(text: str, max_width: float, font, draw) -> list:
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip() if current_line else word
            test_width = draw.textbbox((0, 0), test_line, font=font)[2]
            if test_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines if lines else [text]

    def fit_text_to_box(text: str, max_width: float, max_height: float, font_size: int, draw) -> tuple:
        MIN_FONT_SIZE = 8
        for size in range(font_size, MIN_FONT_SIZE - 1, -1):
            font = get_font(size)
            lines = wrap_text_words_only(text, max_width, font, draw)
            line_height = size + 2
            total_height = line_height * len(lines)
            all_fit = True
            for line in lines:
                for word in line.split():
                    word_width = draw.textbbox((0, 0), word, font=font)[2]
                    if word_width > max_width:
                        all_fit = False
                        break
                if not all_fit:
                    break
            if total_height <= max_height and all_fit:
                return lines, font, size, line_height
        font = get_font(MIN_FONT_SIZE)
        lines = wrap_text_words_only(text, max_width, font, draw)
        line_height = MIN_FONT_SIZE + 2
        max_lines = max(1, int(max_height / line_height))
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            if len(lines[-1]) > 1:
                lines[-1] = lines[-1][:-1] + "…"
        return lines, font, MIN_FONT_SIZE, line_height

    # 번역 대상 영역 수집
    for region in regions:
        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min
        if width * height < 500:
            continue
        if region.get("skip_translate", False) or region.get("render_skip", False):
            continue
        english = region.get("english", region["ocr_text"])
        english = english.replace("ㆍ", "•").replace("·", "•").replace("●", "•")
        if english.strip() == region["ocr_text"].strip():
            continue

        clean_ocr = strip_html_tags(region["ocr_text"])
        prefix_symbol, _ = extract_prefix_symbol(clean_ocr)
        _, english_content = extract_prefix_symbol(english)
        policy = get_prefix_policy(prefix_symbol)

        if policy == "preserve":
            symbol_width = estimate_prefix_pixel_width(prefix_symbol, bbox, img_np)
            render_bbox = [x_min + symbol_width, y_min, x_max, y_max]
            render_text = english_content.strip() if english_content.strip() else english.strip()
        else:
            symbol_width = 0
            render_bbox = bbox
            if prefix_symbol:
                render_text = restore_prefix_symbol(prefix_symbol, english)
            else:
                render_text = english

        x_min_int, y_min_int = int(x_min + symbol_width), int(y_min)
        x_max_int, y_max_int = int(x_max), int(y_max)
        if x_min_int < x_max_int:
            mask[y_min_int:y_max_int, x_min_int:x_max_int] = 255

        translate_regions.append({
            "bbox": render_bbox,
            "english": render_text,
            "ocr_text": region["ocr_text"]
        })

    # 배경 복원
    def is_solid_background(img_np, bbox, threshold=15):
        x_min, y_min, x_max, y_max = [int(v) for v in bbox]
        h, w = img_np.shape[:2]
        samples = []
        margin = 5
        positions = [
            (max(0, x_min - margin), y_min + (y_max - y_min) // 2),
            (min(w - 1, x_max + margin), y_min + (y_max - y_min) // 2),
            (x_min + (x_max - x_min) // 2, max(0, y_min - margin)),
            (x_min + (x_max - x_min) // 2, min(h - 1, y_max + margin)),
        ]
        for px, py in positions:
            if 0 <= px < w and 0 <= py < h:
                samples.append(img_np[py, px])
        if len(samples) < 2:
            return True, (255, 255, 255)
        samples = np.array(samples)
        std = np.std(samples, axis=0).mean()
        avg_color = tuple(samples.mean(axis=0).astype(int))
        return std < threshold, avg_color

    img_pil = Image.fromarray(img_np)
    draw_temp = ImageDraw.Draw(img_pil)

    for region in translate_regions:
        bbox = region["bbox"]
        is_solid, bg_color = is_solid_background(img_np, bbox)
        # 텍스트 색상 결정용으로 배경색 저장
        region["fill_color"] = bg_color
        if is_solid:
            x_min, y_min, x_max, y_max = [int(v) for v in bbox]
            draw_temp.rectangle([x_min, y_min, x_max, y_max], fill=bg_color)
        else:
            x_min, y_min, x_max, y_max = [int(v) for v in bbox]
            region_mask = np.zeros(img_np.shape[:2], dtype=np.uint8)
            region_mask[y_min:y_max, x_min:x_max] = 255
            img_bgr = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
            inpainted_bgr = cv2.inpaint(img_bgr, region_mask, inpaintRadius=2, flags=cv2.INPAINT_TELEA)
            img_pil = Image.fromarray(cv2.cvtColor(inpainted_bgr, cv2.COLOR_BGR2RGB))
            draw_temp = ImageDraw.Draw(img_pil)

    img_np = np.array(img_pil)
    img = Image.fromarray(img_np)
    draw = ImageDraw.Draw(img)

    # 텍스트 렌더링
    for region in translate_regions:
        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min
        english = region["english"]

        # 저장된 배경색 사용 (없으면 픽셀에서 읽기)
        bg_color = region.get("fill_color")
        if not bg_color:
            try:
                cx, cy = int((x_min + x_max) / 2), int((y_min + y_max) / 2)
                cx = max(0, min(cx, img.width - 1))
                cy = max(0, min(cy, img.height - 1))
                pixel = img.getpixel((cx, cy))
                if isinstance(pixel, int):
                    bg_color = (pixel, pixel, pixel)
                else:
                    bg_color = pixel[:3]
            except Exception:
                bg_color = (255, 255, 255)

        initial_font_size = max(12, int(height * 0.7))
        lines, font, final_font_size, line_height = fit_text_to_box(english, width - 4, height - 4, initial_font_size, draw)

        # 가중치 기반 명도 계산 (인간 시각 특성 반영)
        r, g, b = int(bg_color[0]), int(bg_color[1]), int(bg_color[2])
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        text_color = (0, 0, 0) if brightness > 128 else (255, 255, 255)
        log_debug(f"  [Render] bbox=({x_min:.0f},{y_min:.0f},{x_max:.0f},{y_max:.0f}), bg={bg_color}, brightness={brightness:.1f}, text_color={text_color}")
        log_debug(f"    text='{english[:50]}...' → {len(lines)} lines, font_size={final_font_size}")
        total_text_height = line_height * len(lines)
        start_y = y_min + (height - total_text_height) / 2

        for i, line in enumerate(lines):
            text_x = x_min + 2
            text_y = start_y + (i * line_height)
            draw.text((text_x, text_y), line, font=font, fill=text_color)

    img.save(output_path)
    img.close()
    log_info(f"\n  저장됨: {output_path}")
    log_debug(f"[stage_overlay] 완료: {len(translate_regions)}개 영역 렌더링")


# ============================================================
# 배치 처리 설정
# ============================================================
# OCR_CHUNK_SIZE: Surya OCR 한 번 로드로 처리할 페이지 수
#   - Surya 모델은 약 4GB VRAM 사용
#   - 값이 너무 크면: 메모리 누적으로 OOM 위험, 중간 실패 시 재처리 범위 증가
#   - 값이 너무 작으면: 모델 로드/언로드 오버헤드 증가 (청크당 ~2초)
#   - 권장: 3-10 (8GB VRAM 기준 5가 적정)
OCR_CHUNK_SIZE = int(os.environ.get("OCR_CHUNK_SIZE", "5"))

# VLM_CHUNK_SIZE: VLM 한 번 로드로 처리할 페이지 수
#   - VLM 모델(Qwen2.5-VL-7B, 4bit)은 약 6GB VRAM 사용 → Surya보다 메모리 사용량이 큼
#   - 값이 너무 크면: OOM 위험, 번역 실패 시 재처리 범위 증가
#   - 값이 너무 작으면: 모델 로드/언로드 오버헤드 증가 (청크당 ~8초)
#   - 권장: 1-5 (8GB VRAM 기준 2가 적정, OCR보다 작게 설정)
VLM_CHUNK_SIZE = int(os.environ.get("VLM_CHUNK_SIZE", "2"))


# ============================================================
# 중간 결과 캐시 (재시작 지원)
# ============================================================
def get_cache_dir(slide_id: str) -> Path:
    """슬라이드별 캐시 디렉토리"""
    cache_dir = Path(os.environ.get("CACHE_DIR", "uploads/cache")) / slide_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def save_ocr_cache(slide_id: str, page_idx: int, regions: list) -> Path:
    """OCR 결과 캐시 저장"""
    import json
    cache_path = get_cache_dir(slide_id) / f"ocr_{page_idx:03d}.json"
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(regions, f, ensure_ascii=False, indent=2)
    return cache_path


def load_ocr_cache(slide_id: str, page_idx: int) -> list | None:
    """OCR 결과 캐시 로드"""
    import json
    cache_path = get_cache_dir(slide_id) / f"ocr_{page_idx:03d}.json"
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_translate_cache(slide_id: str, page_idx: int, regions: list) -> Path:
    """번역 결과 캐시 저장"""
    import json
    cache_path = get_cache_dir(slide_id) / f"translate_{page_idx:03d}.json"
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(regions, f, ensure_ascii=False, indent=2)
    return cache_path


def load_translate_cache(slide_id: str, page_idx: int) -> list | None:
    """번역 결과 캐시 로드"""
    import json
    cache_path = get_cache_dir(slide_id) / f"translate_{page_idx:03d}.json"
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def clear_cache(slide_id: str):
    """슬라이드 캐시 삭제"""
    import shutil
    cache_dir = get_cache_dir(slide_id)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


# ============================================================
# 배치 OCR (Surya 한 번 로드)
# ============================================================
def batch_ocr_surya(
    image_paths: list[tuple[int, str]],
    slide_id: str = None,
    chunk_size: int = None,
    is_cancelled_callback: callable = None
) -> dict[int, list]:
    """
    여러 이미지를 배치로 OCR 처리

    Args:
        image_paths: [(page_idx, image_path), ...]
        slide_id: 캐시 저장용 슬라이드 ID
        chunk_size: 청크 크기 (None이면 전체를 한 번에)
        is_cancelled_callback: 취소 여부 확인 콜백 (페이지 처리 전 호출)

    Returns:
        {page_idx: regions, ...}
    """
    if not image_paths:
        return {}

    chunk_size = chunk_size or OCR_CHUNK_SIZE
    results = {}

    # 캐시된 결과 먼저 로드
    pending_pages = []
    for page_idx, img_path in image_paths:
        if slide_id:
            cached = load_ocr_cache(slide_id, page_idx)
            if cached is not None:
                log_info(f"  [OCR] 페이지 {page_idx+1}: 캐시 사용")
                log_debug(f"    캐시 로드: {len(cached)}개 영역")
                results[page_idx] = cached
                continue
        pending_pages.append((page_idx, img_path))

    if not pending_pages:
        log_info("[OCR Batch] 모든 페이지 캐시 히트")
        return results

    log_info("\n" + "=" * 60)
    log_info(f"[OCR Batch] {len(pending_pages)}개 페이지 처리 (Surya)")
    log_info("=" * 60)
    log_debug(f"[batch_ocr_surya] slide_id={slide_id}, chunk_size={chunk_size}")

    # GPU 메모리 정리 (VLM 등 이전 모델 해제)
    log_info("  GPU 메모리 정리 중...")
    unload_vlm_model()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()

    # Surya 모델 로드 (한 번만)
    from surya.foundation import FoundationPredictor
    from surya.detection import DetectionPredictor
    from surya.recognition import RecognitionPredictor

    log_info("  Surya 모델 로드 중...")
    foundation_predictor = FoundationPredictor()
    det_predictor = DetectionPredictor()
    rec_predictor = RecognitionPredictor(foundation_predictor)
    log_info("  Surya 모델 로드 완료")

    # 청크 단위로 처리
    for chunk_start in range(0, len(pending_pages), chunk_size):
        chunk = pending_pages[chunk_start:chunk_start + chunk_size]
        chunk_end = min(chunk_start + chunk_size, len(pending_pages))
        log_info(f"\n  [Chunk {chunk_start//chunk_size + 1}] 페이지 {chunk_start+1}-{chunk_end}/{len(pending_pages)}")

        for page_idx, img_path in chunk:
            # 페이지 처리 전 취소 체크
            if is_cancelled_callback and is_cancelled_callback():
                log_warning(f"  [OCR Batch] 취소됨 - 처리 중단")
                del foundation_predictor, det_predictor, rec_predictor
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                return results

            try:
                image = Image.open(img_path).convert("RGB")
                log_info(f"    페이지 {page_idx+1}: {image.size[0]}x{image.size[1]}px")
                log_debug(f"    이미지 경로: {img_path}")

                rec_results = rec_predictor([image], det_predictor=det_predictor)

                regions = []
                for page_result in rec_results:
                    for line in page_result.text_lines:
                        text = normalize_ocr_text(line.text.strip())
                        confidence = line.confidence

                        if not text or confidence < 0.2:
                            continue

                        bbox = [float(line.bbox[0]), float(line.bbox[1]),
                                float(line.bbox[2]), float(line.bbox[3])]

                        regions.append({
                            "bbox": bbox,
                            "ocr_text": text,
                            "confidence": float(confidence),
                            "skip_translate": is_number_or_english_only(text),
                            "has_math": contains_math_markup(text),
                            "is_code": is_code_block(text),
                            "is_chinese": is_chinese_garbage(text),
                        })

                image.close()
                results[page_idx] = regions
                log_info(f"    → {len(regions)}개 영역 감지")
                # 상세 로그: 각 영역의 텍스트
                for idx, r in enumerate(regions):
                    log_debug(f"      [{idx}] conf={r['confidence']:.2f}, skip={r.get('skip_translate', False)}: {r['ocr_text'][:50]}...")

                # 캐시 저장
                if slide_id:
                    save_ocr_cache(slide_id, page_idx, regions)
                    log_debug(f"    캐시 저장됨")

            except Exception as e:
                log_error(f"    페이지 {page_idx+1} OCR 실패: {e}")
                results[page_idx] = []

    # Surya 모델 해제
    log_info("\n  Surya 모델 메모리 해제 중...")
    del foundation_predictor, det_predictor, rec_predictor
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    log_info("  Surya 모델 메모리 해제 완료")
    log_debug(f"[batch_ocr_surya] 완료: {len(results)}개 페이지 처리됨")

    return results


# ============================================================
# 배치 번역 (VLM 한 번 로드)
# ============================================================
def batch_translate_vlm(
    ocr_results: dict[int, list],
    image_paths: dict[int, str],
    slide_id: str = None,
    glossary: dict = None,
    chunk_size: int = None,
    is_cancelled_callback: callable = None
) -> dict[int, list]:
    """
    여러 페이지를 배치로 VLM 번역

    Args:
        ocr_results: {page_idx: regions, ...}
        image_paths: {page_idx: image_path, ...}
        slide_id: 캐시 저장용 슬라이드 ID
        glossary: 용어집
        chunk_size: 청크 크기
        is_cancelled_callback: 취소 여부 확인 콜백 (페이지 처리 전 호출)

    Returns:
        {page_idx: translated_regions, ...}
    """
    if not ocr_results:
        return {}

    chunk_size = chunk_size or VLM_CHUNK_SIZE
    glossary = glossary or {}
    results = {}

    # 캐시된 결과 먼저 로드
    pending_pages = []
    for page_idx, regions in ocr_results.items():
        if slide_id:
            cached = load_translate_cache(slide_id, page_idx)
            if cached is not None:
                log_info(f"  [VLM] 페이지 {page_idx+1}: 캐시 사용")
                log_debug(f"    캐시 로드: {len(cached)}개 영역")
                results[page_idx] = cached
                continue
        if regions:  # OCR 결과가 있는 경우만
            pending_pages.append((page_idx, regions))

    if not pending_pages:
        log_info("[VLM Batch] 모든 페이지 캐시 히트 또는 OCR 결과 없음")
        return results

    log_info("\n" + "=" * 60)
    log_info(f"[VLM Batch] {len(pending_pages)}개 페이지 번역")
    log_info("=" * 60)
    log_debug(f"[batch_translate_vlm] slide_id={slide_id}, glossary={len(glossary)}개, chunk_size={chunk_size}")

    # VLM 모델 로드 (한 번만)
    log_info("  VLM 모델 로드 중...")
    model, processor = get_vlm_model()
    log_info("  VLM 모델 로드 완료")

    # 청크 단위로 처리
    for chunk_start in range(0, len(pending_pages), chunk_size):
        chunk = pending_pages[chunk_start:chunk_start + chunk_size]
        chunk_end = min(chunk_start + chunk_size, len(pending_pages))
        log_info(f"\n  [Chunk {chunk_start//chunk_size + 1}] 페이지 {chunk_start+1}-{chunk_end}/{len(pending_pages)}")

        for page_idx, regions in chunk:
            # 페이지 처리 전 취소 체크
            if is_cancelled_callback and is_cancelled_callback():
                log_warning(f"  [VLM Batch] 취소됨 - 처리 중단")
                return results

            try:
                img_path = image_paths.get(page_idx)
                if not img_path:
                    log_warning(f"    페이지 {page_idx+1}: 이미지 경로 없음")
                    results[page_idx] = regions
                    continue

                log_info(f"    페이지 {page_idx+1}: {len(regions)}개 영역 번역 중...")
                log_debug(f"    이미지 경로: {img_path}")

                # 기존 stage_translate 로직 재사용 (모델 로드 제외)
                translated = _translate_regions_with_vlm(
                    regions, img_path, model, processor, glossary
                )

                results[page_idx] = translated
                log_info(f"    → 번역 완료")
                # 상세 로그: 번역 결과
                for idx, r in enumerate(translated):
                    if r.get("english") and r.get("english") != r.get("ocr_text"):
                        log_debug(f"      [{idx}] '{r.get('ocr_text', '')[:30]}...' → '{r.get('english', '')[:30]}...'")

                # 캐시 저장
                if slide_id:
                    save_translate_cache(slide_id, page_idx, translated)
                    log_debug(f"    캐시 저장됨")

            except Exception as e:
                log_error(f"    페이지 {page_idx+1} 번역 실패: {e}")
                results[page_idx] = regions  # 원본 유지

    log_info("\n[VLM Batch] 번역 완료")
    log_debug(f"[batch_translate_vlm] 완료: {len(results)}개 페이지 처리됨")
    return results


def _translate_regions_with_vlm(
    regions: list,
    image_path: str,
    model,
    processor,
    glossary: dict
) -> list:
    """VLM으로 영역 번역 (내부 함수)"""
    original_image = Image.open(image_path).convert("RGB")
    image_size = original_image.size
    regions = merge_adjacent_regions(regions)
    regions = classify_text_regions(regions, image_size)

    to_translate = []
    for i, region in enumerate(regions):
        if region.get("skip_translate", False):
            region["english"] = region["ocr_text"]
            continue
        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min
        min_area = cfg('ocr.min_area', 500)
        if width * height < min_area:
            region["english"] = region["ocr_text"]
            continue
        to_translate.append((i, region))

    if not to_translate:
        original_image.close()
        return regions

    # 번역 대상 텍스트 수집
    text_lines = []
    line_mapping = []
    prefix_mapping = {}

    for idx, (orig_idx, region) in enumerate(to_translate):
        line_num = len(text_lines) + 1
        ocr_text = strip_html_tags(region['ocr_text'])
        prefix, content = extract_prefix_symbol(ocr_text)
        if prefix:
            prefix_mapping[line_num] = prefix
        text_lines.append(f"{line_num}. {content}")
        line_mapping.append(orig_idx)

    text_list = "\n".join(text_lines)
    total_lines = len(text_lines)
    page_context_items = [r["ocr_text"] for r in regions if r.get("ocr_text")]
    page_context = ", ".join(page_context_items[:20])

    glossary_section = ""
    if glossary:
        selected_glossary = select_glossary_items(glossary, context_texts=page_context_items)
        glossary_lines = [f'  "{ko}": "{en}"' for ko, en in selected_glossary]
        glossary_section = "\n[GLOSSARY]\n" + "\n".join(glossary_lines) + "\n"

    PROMPT = f"""Translate Korean to English for a lecture slide.

[PAGE CONTEXT]
{page_context}
{glossary_section}
[TRANSLATE]
{text_list}

RULES:
1. Output EXACTLY {total_lines} lines, format: "1. translation"
2. Use PAGE CONTEXT to disambiguate ambiguous/short terms
3. Use GLOSSARY translations for technical terms if provided
4. Standard academic terminology
5. Never romanize - translate to English
6. KEEP: emails, URLs, filenames, code syntax
7. SHORT labels → CONCISE translation

Translate:"""

    messages = [{"role": "user", "content": [{"type": "text", "text": PROMPT}]}]

    try:
        text_input = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text_input], return_tensors="pt").to(model.device)

        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=2048,
                do_sample=False,
                pad_token_id=processor.tokenizer.pad_token_id,
            )

        input_len = inputs.input_ids.shape[1]
        output_len = output_ids[0].shape[0] - input_len
        response = processor.batch_decode(output_ids[:, input_len:], skip_special_tokens=True)[0]

        # 로그: VLM 응답 원본
        log_debug(f"[VLM Batch Response] 원본 응답 ({len(response)} chars, {output_len} tokens):\n{response}")

        # 텍스트 잘림 감지
        MAX_NEW_TOKENS = 2048
        if output_len >= MAX_NEW_TOKENS - 10:
            log_warning(f"[VLM Batch] 응답이 잘렸을 수 있음! output_tokens={output_len}/{MAX_NEW_TOKENS}")

        # 프롬프트 유출 감지
        if is_leaked_prompt(response):
            log_warning(f"[VLM Batch] 프롬프트 유출 감지! 원본 텍스트 유지")
            for _, (orig_idx, region) in enumerate(to_translate):
                regions[orig_idx]["english"] = region["ocr_text"]
            original_image.close()
            return regions

        # 응답 파싱 (다양한 형식 지원)
        translated_lines = {}
        unparsed_lines = []

        for line in response.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # 패턴: "1. translation" 또는 "1) translation" 또는 "1: translation"
            match = re.match(r'^(\d+)\s*[\.:\)\-]\s*(.+)$', line)
            if match:
                line_num = int(match.group(1))
                translation = match.group(2).strip().strip('"\'')
                translated_lines[line_num] = translation
                log_debug(f"  [Parse] Line {line_num}: {translation[:50]}...")
            else:
                unparsed_lines.append(line)

        # 파싱 실패한 라인 로그
        if unparsed_lines:
            log_warning(f"[VLM Batch] 파싱 실패 라인 {len(unparsed_lines)}개:")
            for ul in unparsed_lines[:5]:
                log_warning(f"  → {ul[:80]}...")

        log_debug(f"[VLM Batch] 파싱 결과: {len(translated_lines)}/{total_lines} 라인 매핑됨")

        # 매핑 누락 경고
        missing_lines = [i for i in range(1, total_lines + 1) if i not in translated_lines]
        if missing_lines:
            log_warning(f"[VLM Batch] 번역 누락된 라인: {missing_lines}")

        # 결과 매핑
        for idx, (orig_idx, region) in enumerate(to_translate):
            line_num = idx + 1
            if line_num in translated_lines:
                prefix = prefix_mapping.get(line_num, "")
                translation = translated_lines[line_num]

                # 개별 번역 결과도 프롬프트 유출 체크
                if is_leaked_prompt(translation):
                    log_warning(f"  [Line {line_num}] 프롬프트 유출 감지, 원본 유지")
                    regions[orig_idx]["english"] = region["ocr_text"]
                    continue

                if prefix:
                    regions[orig_idx]["english"] = f"{prefix} {translation}"
                else:
                    regions[orig_idx]["english"] = translation
                log_debug(f"  [Region {orig_idx}] '{region['ocr_text'][:30]}...' → '{translation[:30]}...'")
            else:
                regions[orig_idx]["english"] = region["ocr_text"]
                log_debug(f"  [Region {orig_idx}] 번역 없음, 원본 유지")

    except Exception as e:
        log_error(f"VLM 번역 오류: {e}")
        for _, (orig_idx, region) in enumerate(to_translate):
            regions[orig_idx]["english"] = region["ocr_text"]

    original_image.close()
    return regions


# ============================================================
# 배치 오버레이 (CPU)
# ============================================================
def batch_overlay(
    translate_results: dict[int, list],
    image_paths: dict[int, str],
    output_dir: str,
    slide_id: str
) -> dict[int, str]:
    """
    여러 페이지를 배치로 오버레이

    Args:
        translate_results: {page_idx: regions, ...}
        image_paths: {page_idx: image_path, ...}
        output_dir: 출력 디렉토리
        slide_id: 슬라이드 ID

    Returns:
        {page_idx: output_path, ...}
    """
    log_info("\n" + "=" * 60)
    log_info(f"[Overlay Batch] {len(translate_results)}개 페이지 렌더링")
    log_info("=" * 60)
    log_debug(f"[batch_overlay] output_dir={output_dir}, slide_id={slide_id}")

    output_paths = {}

    for page_idx, regions in translate_results.items():
        img_path = image_paths.get(page_idx)
        if not img_path:
            log_warning(f"  페이지 {page_idx}: 이미지 경로 없음, 스킵")
            continue

        output_path = os.path.join(output_dir, f"{slide_id}_{page_idx}.png")

        try:
            stage_overlay(img_path, regions, output_path)
            output_paths[page_idx] = output_path
            log_info(f"  페이지 {page_idx+1}: 완료")
        except Exception as e:
            log_error(f"  페이지 {page_idx+1}: 실패 - {e}")

    log_debug(f"[batch_overlay] 완료: {len(output_paths)}개 이미지 생성됨")
    return output_paths
