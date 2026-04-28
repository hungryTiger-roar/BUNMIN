"""
강의 슬라이드 번역 파이프라인 v3
- 서비스 통합용 (함수 호출 가능)
- 숫자/영어 전용 영역 스킵
- 텍스트 오버플로우 방지

사용법:
    python translate_slide_v3.py --image slide.png

서비스 통합:
    from translate_slide_v3 import translate_slide
    result = translate_slide("slide.png", "output.png")
"""

import argparse
import os
import gc
import json
import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np
import torch
import yaml
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# .env 로드
load_dotenv(Path(__file__).parent / ".env")

# ============================================================
# 설정 파일 로드
# ============================================================
_config = None

def get_config():
    """config.yaml 로드 (싱글톤)"""
    global _config
    if _config is not None:
        return _config

    config_path = Path(__file__).parent / "backend" / "config.yaml"
    if not config_path.exists():
        # 직접 실행 시 경로
        config_path = Path(__file__).parent / "config.yaml"

    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            _config = yaml.safe_load(f)
        print(f"[Config] 설정 로드됨: {config_path}")
    else:
        print(f"[Config] 설정 파일 없음, 기본값 사용")
        _config = {}

    return _config


def reload_config():
    """config 캐시 강제 리로드 (서버 재시작 없이 설정 변경 반영)"""
    global _config
    _config = None
    return get_config()


def cfg(key: str, default=None):
    """설정값 조회 (점 표기법 지원: 'layout.nearby_threshold')"""
    config = get_config()
    keys = key.split('.')
    value = config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value

# VLM 설정 (환경변수 또는 기본값)
VLM_BASE_MODEL = os.environ.get("VLM_BASE_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
VLM_LORA_PATH = Path(__file__).parent / os.environ.get("VLM_LORA_PATH", "models/qwen3/qwen3-vl-8b-lora-r64-e3-final")
VLM_DEVICE = os.environ.get("VLM_DEVICE", "cuda")
VLM_USE_4BIT = os.environ.get("VLM_USE_4BIT", "true").lower() == "true"
VLM_MAX_GPU_MEMORY = os.environ.get("VLM_MAX_GPU_MEMORY", "6GB")

# ============================================================
# OCR 엔진 선택 (환경변수)
# ============================================================
OCR_ENGINE = os.environ.get("AUNION_OCR_ENGINE", "surya")  # surya, easyocr, rapid

# ============================================================
# Prefix 기호 픽셀 보존 정책 (config.yaml 기반)
# - 번역 용어 glossary와 다름: 렌더링 fallback 정책
# - 코드에는 fallback 기본값만 두고 실제 정책은 config에서 읽음
# ============================================================

# Fallback 기본값 (config.yaml이 없을 때 사용)
DEFAULT_PIXEL_PRESERVE_PREFIXES = {
    "☑", "☐", "□", "■", "✓", "✔", "✗", "✘",
    "📦", "📌", "🔹", "🔸", "✅", "⚠️", "💡", "📍",
    "🔴", "🟢", "🔵", "⭐", "🎯", "📝", "📋", "🚀", "⚡", "🔥",
}

DEFAULT_FORCE_RENDER_PREFIXES = {
    "-", ">", "›", "•", "◦", "○", "●", "·", "ㆍ",
    "▶", "►", "※", "★", "☆",
}


def get_pixel_preserve_prefixes() -> set:
    """config에서 픽셀 보존 대상 prefix 목록 읽기"""
    configured = cfg("prefix_symbols.pixel_preserve_prefixes", None)
    if configured is None:
        return DEFAULT_PIXEL_PRESERVE_PREFIXES
    return set(configured)


def get_force_render_prefixes() -> set:
    """config에서 강제 폰트 렌더링 대상 prefix 목록 읽기"""
    configured = cfg("prefix_symbols.force_render_prefixes", None)
    if configured is None:
        return DEFAULT_FORCE_RENDER_PREFIXES
    return set(configured)


def get_prefix_policy(prefix: str) -> str:
    """
    prefix 기호의 처리 정책 결정.
    return:
    - "render": 전체 bbox 지우고 prefix 포함 영어를 새로 렌더링
    - "preserve": prefix 픽셀은 원본 유지, 뒤 텍스트만 렌더링
    - "none": prefix 없음
    """
    if not prefix:
        return "none"

    symbol = prefix.strip()
    if not symbol:
        return "none"

    force_render = get_force_render_prefixes()
    pixel_preserve = get_pixel_preserve_prefixes()

    # force render가 우선
    if any(symbol.startswith(p) for p in force_render):
        return "render"

    # pixel preserve
    if any(symbol.startswith(p) for p in pixel_preserve):
        return "preserve"

    # 기본 정책
    return cfg("prefix_symbols.default_policy", "render")


def estimate_prefix_split_from_image(img_np, bbox) -> int | None:
    """
    이미지 분석으로 prefix와 본문 사이 실제 경계 찾기.
    - ink(글자) 픽셀의 column-wise 분포 분석
    - 첫 번째 segment(prefix)와 두 번째 segment(본문) 사이 gap 찾기

    Returns: split 위치 (bbox 내 상대 x좌표) 또는 None (실패 시)
    """
    x1, y1, x2, y2 = map(int, bbox)

    # bbox 영역 crop
    if y2 <= y1 or x2 <= x1:
        return None
    crop = img_np[y1:y2, x1:x2]

    if crop.size == 0:
        return None

    # grayscale 변환
    if len(crop.shape) == 3:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    else:
        gray = crop

    # 배경색 추정 (중간값)
    bg = np.median(gray)
    diff = np.abs(gray.astype(np.int16) - int(bg))

    # ink 픽셀 감지 (배경과 차이가 큰 픽셀)
    ink_threshold = cfg("prefix_symbols.image_split.ink_threshold", 25)
    ink = diff > ink_threshold

    # column별 활성 픽셀 수 계산
    active_col_ratio = cfg("prefix_symbols.image_split.active_col_ratio", 0.08)
    col_threshold = max(1, int(crop.shape[0] * active_col_ratio))
    active = ink.sum(axis=0) > col_threshold

    # 연속된 활성 구간(segment) 찾기
    segments = []
    start = None
    for i, v in enumerate(active):
        if v and start is None:
            start = i
        elif not v and start is not None:
            segments.append((start, i - 1))
            start = None
    if start is not None:
        segments.append((start, len(active) - 1))

    # 너무 짧은 segment 필터링
    segments = [(s, e) for s, e in segments if e - s + 1 >= 2]

    # 최소 2개 segment 필요 (prefix + 본문)
    if len(segments) < 2:
        return None

    first_s, first_e = segments[0]
    second_s, second_e = segments[1]
    gap = second_s - first_e

    # gap이 너무 작으면 실패
    min_gap_px = cfg("prefix_symbols.image_split.min_gap_px", 3)
    if gap < min_gap_px:
        return None

    # split 위치 = gap 중간
    split = int((first_e + second_s) / 2)

    # split이 너무 크면 실패 (한글 잔존 방지)
    max_prefix_region_ratio = cfg("prefix_symbols.image_split.max_prefix_region_ratio", 0.35)
    max_split = int((x2 - x1) * max_prefix_region_ratio)

    if split > max_split:
        return None

    return split


def estimate_prefix_width_fallback(prefix: str, height: float, region_width: float) -> int:
    """
    Fallback: 이미지 분석 실패 시 높이 기반 추정.
    - 기호는 1개로 취급 (char_count 사용 안 함)
    - 정사각형 가정
    """
    if not prefix or not prefix.strip():
        return 0

    ratio = cfg("prefix_symbols.preserve_width.fallback_height_ratio", 0.9)
    min_px = cfg("prefix_symbols.preserve_width.min_px", 10)
    max_region_ratio = cfg("prefix_symbols.preserve_width.max_region_ratio", 0.25)

    estimated = int(height * ratio)
    estimated = max(min_px, estimated)
    estimated = min(estimated, int(region_width * max_region_ratio))

    return estimated


def estimate_prefix_pixel_width(prefix: str, bbox: list, img_np=None) -> int:
    """
    보존할 접두 기호의 픽셀 너비 추정.
    1순위: 이미지 분석으로 실제 prefix/본문 경계 찾기
    2순위: 실패하면 height 기반 fallback
    """
    if not prefix or not prefix.strip():
        return 0

    x1, y1, x2, y2 = bbox
    height = y2 - y1
    region_width = x2 - x1

    # 1. 이미지 분석 시도
    if img_np is not None and cfg("prefix_symbols.image_split.enabled", True):
        split = estimate_prefix_split_from_image(img_np, bbox)
        if split is not None:
            if cfg("prefix_symbols.debug_log", True):
                print(f"    [Image Split] prefix 경계 발견: {split}px")
            return split

    # 2. Fallback: 높이 기반 추정
    fallback = estimate_prefix_width_fallback(prefix, height, region_width)
    if cfg("prefix_symbols.debug_log", True):
        print(f"    [Fallback] height 기반 추정: {fallback}px")
    return fallback


# ============================================================
# 전역 모델 (싱글톤) - 한 번만 로드
# ============================================================
_vlm_model = None
_vlm_processor = None

# Surya OCR 모델 캐싱
_surya_det_model = None
_surya_det_processor = None
_surya_rec_model = None
_surya_rec_processor = None


def get_vlm_model():
    """VLM 모델 싱글톤 - 최초 1회만 로드"""
    global _vlm_model, _vlm_processor

    if _vlm_model is not None:
        return _vlm_model, _vlm_processor

    if not torch.cuda.is_available():
        raise RuntimeError(f"VLM 번역에는 NVIDIA GPU(CUDA)가 필요합니다. torch={torch.__version__}, cuda_built={torch.version.cuda}, nvidia-smi로 GPU를 확인하고, CUDA 버전 PyTorch(pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126)를 설치하세요.")

    from transformers import AutoProcessor, AutoModelForImageTextToText, BitsAndBytesConfig
    from peft import PeftModel

    print(f"[VLM] 모델 최초 로드 중... (4bit={VLM_USE_4BIT})")
    print(f"[VLM] Base: {VLM_BASE_MODEL}")
    print(f"[VLM] LoRA: {VLM_LORA_PATH}")

    if VLM_USE_4BIT:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            llm_int8_enable_fp32_cpu_offload=True,
        )
        model_kwargs = {
            "quantization_config": bnb_config,
            "device_map": "auto",
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
            "max_memory": {0: VLM_MAX_GPU_MEMORY, "cpu": "16GB"},
        }
    else:
        model_kwargs = {
            "torch_dtype": torch.float16,
            "device_map": "auto",
            "trust_remote_code": True,
        }

    _vlm_processor = AutoProcessor.from_pretrained(
        VLM_BASE_MODEL,  # Base 모델에서 processor 로드 (LoRA에는 processor 없음)
        trust_remote_code=True,
        min_pixels=128 * 28 * 28,
        max_pixels=256 * 28 * 28,
    )

    base_model = AutoModelForImageTextToText.from_pretrained(
        VLM_BASE_MODEL,
        **model_kwargs,
    )

    _vlm_model = PeftModel.from_pretrained(base_model, str(VLM_LORA_PATH))
    _vlm_model.eval()

    print("[VLM] 모델 로드 완료! (전역 캐시됨)")
    return _vlm_model, _vlm_processor


def is_vlm_loaded() -> bool:
    """VLM 모델 로드 여부 확인"""
    return _vlm_model is not None


def unload_vlm_model():
    """VLM 모델 언로드 (GPU 메모리 해제)"""
    global _vlm_model, _vlm_processor

    if _vlm_model is None:
        print("[VLM] 언로드할 모델 없음")
        return

    cuda_available = torch.cuda.is_available()
    vram_before = torch.cuda.memory_allocated() / 1024 ** 3 if cuda_available else 0

    print("[VLM] 모델 언로드 중...")
    del _vlm_model
    del _vlm_processor
    _vlm_model = None
    _vlm_processor = None

    gc.collect()
    if cuda_available:
        torch.cuda.empty_cache()
        vram_after = torch.cuda.memory_allocated() / 1024 ** 3
        freed = vram_before - vram_after
        print(
            f"[VLM] VRAM 해제 완료 | "
            f"해제 전: {vram_before:.2f}GB → 해제 후: {vram_after:.2f}GB "
            f"(해제량: {freed:.2f}GB)",
            flush=True,
        )
    else:
        print("[VLM] 모델 언로드 완료 (CPU 모드)", flush=True)


def is_number_or_english_only(text: str) -> bool:
    """숫자, 영어, 기호만 있는지 확인 (번역 불필요)"""
    # 한글이 하나라도 있으면 False
    if re.search(r'[가-힣]', text):
        return False
    # 숫자, 영어, 공백, 기호만 있으면 True
    return bool(re.match(r'^[0-9a-zA-Z\s\.\,\-\_\:\;\!\?\@\#\$\%\&\*\(\)\[\]\{\}\/\\]+$', text))


def is_chinese_garbage(text: str) -> bool:
    """
    한자 오인식 감지 - OCR이 스타일화된 한글 그래픽을 한자로 오인식한 경우
    예: "수한" → "赤些", "유기질" → "命沙登"

    config.yaml의 ocr_filters.enable_hanja_filter 플래그로 제어됨.
    중국어 원본 슬라이드 번역 시 false로 설정하면 이 필터가 비활성화됨.
    """
    # 설정에서 한자 필터가 비활성화되어 있으면 즉시 패스
    if not cfg('ocr_filters.enable_hanja_filter', True):
        return False

    text = text.strip()
    if not text:
        return False

    # 한글이 있으면 한자 오인식 아님 (정상 텍스트)
    if re.search(r'[가-힣]', text):
        return False

    # 한자 범위: CJK Unified Ideographs (U+4E00-U+9FFF)
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    if not chinese_chars:
        return False

    text_without_space = re.sub(r'\s+', '', text)

    # 1-3글자 짧은 텍스트: 한자 1개라도 있으면 오인식 (공격적 필터링)
    if len(text_without_space) <= 3 and len(chinese_chars) >= 1:
        return True

    # 4-5글자 텍스트: 한자 비율 40% 이상이면 오인식
    if len(text_without_space) <= 5 and len(chinese_chars) >= len(text_without_space) * 0.4:
        return True

    # 그 외: 한자 비율이 60% 이상이면 오인식
    if len(chinese_chars) >= len(text_without_space) * 0.6:
        return True

    return False


def is_passthrough_content(text: str) -> bool:
    """번역 없이 그대로 유지해야 하는 콘텐츠 감지 (이메일, URL, 수식 등)"""
    # 한글이 포함되어 있으면 무조건 번역 대상 (passthrough 아님)
    if re.search(r'[가-힣]', text):
        return False
    # 이메일 패턴
    if re.search(r'[\w\.\-\+]+@[\w\.\-]+\.\w+', text):
        return True
    # URL 패턴
    if re.search(r'https?://[\w\.\-/\?\=\&\#]+', text):
        return True
    # 파일 경로 패턴 (Windows/Unix) - ASCII만 매칭
    if re.search(r'[A-Za-z]:\\[A-Za-z0-9_\s\\/\.]+|^/[A-Za-z0-9_/\.]+$', text):
        return True
    # 수식 패턴 (간단한 수학 표현)
    if re.search(r'^\s*[\d\+\-\*\/\=\(\)\^\s\.]+\s*$', text):
        return True
    return False


def contains_math_markup(text: str) -> bool:
    """수식 마크업(<math>, LaTeX 등) 포함 여부"""
    return bool(re.search(r'<math|</math>|\\frac|\\sum|\\int|\\sqrt|display="', text))


def strip_math_markup(text: str) -> str:
    """수식 마크업 제거 - 한글 번역을 위해 수식 부분만 제거"""
    # <math>...</math> 태그 전체 제거 (화살표 등은 → 로 대체)
    result = re.sub(r'<math>.*?</math>', ' → ', text, flags=re.DOTALL)
    result = re.sub(r'<math>[^<]*', ' → ', result)  # 닫히지 않은 <math> 태그
    # LaTeX 명령어 제거
    result = re.sub(r'\\(frac|sum|int|sqrt|rightarrow|leftarrow)\b[^a-zA-Z]*', ' ', result)
    # 연속 공백/화살표 정리
    result = re.sub(r'\s+', ' ', result)
    result = re.sub(r'(→\s*)+', '→ ', result)
    return result.strip()


def strip_html_tags(text: str) -> str:
    """OCR/VLM 결과에 섞인 HTML 스타일 태그 제거 (<mark>, <b>, <i> 등)"""
    if not text:
        return text
    # <tag>...</tag> 형태의 태그 제거 (내용은 보존)
    # 예: <mark>functional</mark> → functional
    result = re.sub(r'</?(?:mark|b|i|em|strong|u|s|sub|sup|span|div|font)[^>]*>', '', text, flags=re.IGNORECASE)
    # 남은 일반 HTML 태그도 제거 (단, <math>는 수식 처리용으로 보존)
    result = re.sub(r'</?(?!math)[a-zA-Z][^>]*>', '', result, flags=re.IGNORECASE)
    # 남은 빈 태그/self-closing 태그 정리
    result = re.sub(r'<[^>]+/>', '', result)
    # 연속 공백 정리
    result = re.sub(r'\s+', ' ', result).strip()
    return result


def normalize_ocr_text(text: str) -> str:
    """
    OCR 출력 정규화 - OCR 직후 즉시 적용

    1. HTML 태그 제거 (<b>HANSUNG</b> → HANSUNG)
    2. 연속 공백 정리
    3. 앞뒤 공백 제거
    """
    if not text:
        return text
    text = strip_html_tags(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_code_block(text: str) -> bool:
    """프로그래밍 코드 영역 감지 - 번역 스킵 대상"""
    # config.yaml에서 패턴 로드 (없으면 기본값)
    code_patterns = cfg('code_patterns', [
        r'#include\s*<',
        r'using\s+namespace',
        r'\bint\s+main\s*\(',
        r'\bcout\s*<<',
        r'\bcin\s*>>',
        r'\bprintf\s*\(',
        r'\bscanf\s*\(',
        r'\breturn\s+\d+;',
        r'%[dfsclx]',
        r'\\n["\']',
        r'<<\s*endl',
    ])
    for pattern in code_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def is_single_char_korean(text: str) -> bool:
    """1글자 한글만 있는지 확인 - 맥락 없이 번역 불가"""
    text = text.strip()
    # 1글자 한글만 (예: "동", "수", "값")
    if len(text) == 1 and re.match(r'^[가-힣]$', text):
        return True
    return False


def is_vertical_text_region(bbox: list, text: str) -> bool:
    """
    세로 텍스트 영역 감지

    오탐 방지를 위한 조건:
    - 극단적 세로 비율 (height > width * 2.5)
    - 좁은 너비 (width < 80px)
    - 한글이 60% 이상
    - 텍스트 2자 이상
    """
    x_min, y_min, x_max, y_max = bbox
    width = x_max - x_min
    height = y_max - y_min

    # HTML 태그 제거 및 공백 제거
    clean_text = re.sub(r'\s+', '', strip_html_tags(text))

    # 최소 조건: 2자 이상
    if len(clean_text) < 2:
        return False

    # 한글 비율 체크 (60% 이상이어야 함)
    korean_chars = re.findall(r'[가-힣]', clean_text)
    if not korean_chars:
        return False
    korean_ratio = len(korean_chars) / max(1, len(clean_text))
    if korean_ratio < 0.6:
        return False

    # 세로 비율 조건 (height > width * 2.5)
    aspect_vertical = height > width * 2.5

    # 좁은 너비 조건 (width < 80px)
    narrow_width = width < 80

    # 두 조건 모두 만족해야 세로 텍스트로 판단
    return aspect_vertical and narrow_width


def split_br_lines(text: str) -> list:
    """<br> 태그로 연결된 텍스트를 개별 라인으로 분리"""
    if '<br>' in text.lower():
        # <br>, <br/>, <br /> 등 다양한 형태 지원
        lines = re.split(r'<br\s*/?>', text, flags=re.IGNORECASE)
        return [line.strip() for line in lines if line.strip()]
    return [text]


def extract_korean_in_quotes(text: str) -> list:
    """코드 내 따옴표 안의 한글 문자열 추출 (OCR 변형 고려)"""
    # OCR이 인식할 수 있는 다양한 따옴표 변형 고려
    # ", ', ", ", ', ' 등
    quote_chars = r'["\'\"\"\'\']'
    pattern = rf'{quote_chars}([^"\'\"\"\'\']*?[가-힣]+[^"\'\"\"\'\']*?){quote_chars}'
    matches = re.findall(pattern, text)
    return matches


# 보존할 접두 기호 목록 (순서 중요 - 긴 패턴 먼저)
PREFIX_SYMBOLS = [
    # 화살표/삼각형
    '▶ ', '► ', '› ', '> ',
    '▶', '►', '›',
    # 불렛 포인트
    '• ', '◦ ', '○ ', '● ', '· ', 'ㆍ ', '- ',
    '•', '◦', '○', '●', '·', 'ㆍ',
    # 체크박스
    '☐ ', '☑ ', '□ ', '■ ',
    '☐', '☑', '□', '■',
    # 기타
    '※ ', '★ ', '☆ ',
    '※', '★', '☆',
]


def is_prefix_symbol_char(ch: str) -> bool:
    """
    불렛/체크박스/기호/이모지 prefix 판별 (유니코드 기반)

    예: ☑, ★, ▶, 📦, 📌, 🔹, ✅, ➤ 등
    """
    if not ch:
        return False

    category = unicodedata.category(ch)

    # Unicode Symbol 계열
    # So: Symbol, other      예: ☑, ★, ▶, 일부 이모지
    # Sm: Symbol, math       예: →, ×, ±
    # Sk: Symbol, modifier
    # Sc: Currency symbol    예: $, €, ₩
    if category in ("So", "Sm", "Sk"):
        return True

    code = ord(ch)

    # Dingbats / Misc Symbols / Emojis 주요 범위
    emoji_ranges = [
        (0x2600, 0x27BF),    # Misc symbols, Dingbats: ☑, ★, ➤, ✓
        (0x1F300, 0x1F9FF),  # Emoji blocks: 📦, 📌, 🔹
    ]

    return any(start <= code <= end for start, end in emoji_ranges)


def extract_prefix_symbol(text: str) -> tuple:
    """
    텍스트에서 접두 기호/이모지 분리 (유니코드 자동 감지)

    예:
    '☑ 얼굴 각 부분' -> ('☑ ', '얼굴 각 부분')
    '📦 이상적인 얼굴' -> ('📦 ', '이상적인 얼굴')
    '▶ 이상적인 얼굴' -> ('▶ ', '이상적인 얼굴')

    Returns: (prefix, content)
    """
    text_stripped = text.strip()
    if not text_stripped:
        return ('', text_stripped)

    # 1. 기존 명시 목록 먼저 처리 (공백 포함 패턴 우선)
    for symbol in PREFIX_SYMBOLS:
        if text_stripped.startswith(symbol):
            content = text_stripped[len(symbol):].strip()
            prefix = symbol if symbol.endswith(' ') else symbol + ' '
            return (prefix, content)

    # 2. 유니코드 기호/이모지 자동 감지 (첫 글자만)
    first_char = text_stripped[0]
    if is_prefix_symbol_char(first_char):
        content = text_stripped[1:].strip()
        if content:  # 기호 뒤에 내용이 있을 때만
            return (first_char + ' ', content)

    return ('', text_stripped)  # 접두 기호 없음


def restore_prefix_symbol(prefix: str, translated: str) -> str:
    """번역된 텍스트에 원본 접두 기호 복원"""
    if not prefix:
        return translated

    # 번역 결과에서 잘못 추가된 기호 제거
    translated_clean = translated.strip()

    # 1. 명시 목록에서 제거
    for symbol in PREFIX_SYMBOLS:
        if translated_clean.startswith(symbol):
            translated_clean = translated_clean[len(symbol):].strip()
            break

    # 2. 유니코드 기호/이모지도 제거 (첫 글자가 기호면)
    if translated_clean and is_prefix_symbol_char(translated_clean[0]):
        translated_clean = translated_clean[1:].strip()

    return prefix + translated_clean


def post_process_symbols(text: str) -> str:
    """VLM/OCR 오류로 변형된 기호를 config 기준으로 복원"""
    symbol_mapping = cfg('symbol_mapping', {})
    if not symbol_mapping:
        return text

    result = text
    for wrong_sym, correct_sym in symbol_mapping.items():
        result = result.replace(wrong_sym, correct_sym)
    return result


def is_incomplete_sentence(text: str) -> bool:
    """문장이 불완전하게 끝났는지 판단 (다음 줄과 병합 필요)"""
    text = text.strip()
    if not text:
        return False

    # 완전 종결 패턴 (병합 안 함)
    # 1. 마침표/물음표/느낌표로 끝남
    if text[-1] in '.?!。':
        return False
    # 2. 괄호로 끝남 (설명 완료)
    if text[-1] in ')）]】':
        return False
    # 3. 제목 패턴 (숫자로 시작하고 짧음)
    if re.match(r'^\d+[\.\)]\s*.{1,15}$', text):
        return False
    if re.match(r'^[QA]\d+', text):  # Q1, A1 등
        return False
    # 4. 영어 약어로 끝남 (ASR, NMT, TTS 등)
    if re.match(r'.*[A-Z]{2,}(\s*\([^)]+\))?\s*$', text):
        return False

    # 불완전 종결 패턴 (병합 대상)
    # 1. 한글 조사/어미 중간에서 끊김 (공백 뒤 자음으로 끝남)
    # 2. 단어 중간에서 끊김 (마지막 글자가 한글이고 종결어미 아님)
    last_char = text[-1]
    if re.match(r'[가-힣]', last_char):
        # 종결어미 패턴이 아니면 불완전
        if not re.search(r'(다|요|죠|음|함|임|됨|니다|세요|습니다|입니다)$', text):
            return True

    return False


def merge_adjacent_regions(regions: list, threshold_y: int = 20) -> list:
    """
    인접한 불완전 문장 영역을 병합 (VLM 매핑 밀림 방지)

    조건:
    1. Y축 인접 (threshold_y 픽셀 이내)
    2. X축 정렬 (같은 문단)
    3. 앞 문장이 불완전 종결
    4. 뒷 문장이 불렛/번호로 시작하지 않음
    """
    if not regions:
        return regions

    # Y좌표 기준 정렬
    sorted_regions = sorted(regions, key=lambda r: (r['bbox'][1], r['bbox'][0]))

    merged = []
    current = None

    for region in sorted_regions:
        if current is None:
            current = region.copy()
            continue

        # 병합 조건 검사
        curr_bbox = region['bbox']
        prev_bbox = current['bbox']

        # 1. Y축 인접성 (이전 박스 하단 ~ 현재 박스 상단)
        y_gap = curr_bbox[1] - prev_bbox[3]
        y_adjacent = 0 <= y_gap <= threshold_y

        # 2. X축 정렬 (시작점 차이)
        x_diff = abs(curr_bbox[0] - prev_bbox[0])
        x_aligned = x_diff < 50  # 50px 허용

        # 3. 앞 문장 불완전 종결
        prev_incomplete = is_incomplete_sentence(current['ocr_text'])

        # 4. 뒷 문장이 불렛/번호로 시작하지 않음
        curr_text = region['ocr_text'].strip()
        starts_with_bullet = bool(re.match(r'^[•●▶☐◦○■□※★☆\-]\s*', curr_text))
        starts_with_number = bool(re.match(r'^\d+[\.\)]\s+', curr_text))
        starts_with_section = bool(re.match(r'^[QA]\d+|^\d{2}\s+[가-힣A-Z]', curr_text))

        # 모든 조건 충족 시 병합
        should_merge = (
            y_adjacent and
            x_aligned and
            prev_incomplete and
            not starts_with_bullet and
            not starts_with_number and
            not starts_with_section and
            not current.get('skip_translate', False) and
            not region.get('skip_translate', False)
        )

        if should_merge:
            # 텍스트 병합
            current['ocr_text'] = current['ocr_text'].rstrip() + ' ' + region['ocr_text'].lstrip()
            # Bbox 확장
            current['bbox'] = [
                min(prev_bbox[0], curr_bbox[0]),  # x_min
                prev_bbox[1],                      # y_min (이전 유지)
                max(prev_bbox[2], curr_bbox[2]),  # x_max
                curr_bbox[3]                       # y_max (현재로 확장)
            ]
            # confidence는 낮은 값 사용 (보수적)
            current['confidence'] = min(current.get('confidence', 1.0), region.get('confidence', 1.0))
            print(f"  [병합] '{current['ocr_text'][:30]}...'")
        else:
            merged.append(current)
            current = region.copy()

    # 마지막 영역 추가
    if current:
        merged.append(current)

    if len(merged) < len(regions):
        print(f"\n  영역 병합: {len(regions)}개 → {len(merged)}개 ({len(regions) - len(merged)}개 병합됨)")

    return merged


def has_korean(text: str) -> bool:
    """텍스트에 한글이 포함되어 있는지 확인"""
    return bool(re.search(r'[가-힣]', text))


def extract_email_url(text: str) -> list:
    """텍스트에서 이메일/URL 패턴 추출"""
    patterns = []
    # 이메일
    emails = re.findall(r'[\w\.\-\+]+@[\w\.\-]+\.\w+', text)
    patterns.extend(emails)
    # URL
    urls = re.findall(r'https?://[\w\.\-/\?\=\&\#]+', text)
    patterns.extend(urls)
    return patterns


# ============================================================
# 레이아웃 기반 텍스트 분류
# ============================================================
def classify_text_regions(regions: list, image_size: tuple) -> list:
    """
    각 텍스트 영역을 레이아웃 특성에 따라 분류
    - STRICT_LITERAL: 독립된 라벨 (이미지 맥락 무시, 직역)
    - CONTEXT_AWARE: 문장/문단 (이미지 맥락 활용, OCR 교정 허용)
    """
    if not regions:
        return regions

    image_width, image_height = image_size
    image_area = image_width * image_height

    # 모든 bbox 수집 (근접성 계산용)
    all_bboxes = [r["bbox"] for r in regions if "bbox" in r]

    def has_nearby_regions(bbox, threshold=50):
        """주변에 다른 텍스트 영역이 있는지 확인"""
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

            # 중심점 간 거리
            distance = ((center_x - other_center_x) ** 2 + (center_y - other_center_y) ** 2) ** 0.5
            if distance < threshold:
                nearby_count += 1

        return nearby_count > 0

    def is_aligned_with_others(bbox, threshold=20):
        """다른 텍스트와 수평/수직 정렬되어 있는지 (문장의 일부일 가능성)"""
        x_min, y_min, x_max, y_max = bbox

        for other_bbox in all_bboxes:
            if other_bbox == bbox:
                continue
            ox_min, oy_min, ox_max, oy_max = other_bbox

            # 수평 정렬 (y 좌표 유사)
            if abs(y_min - oy_min) < threshold or abs(y_max - oy_max) < threshold:
                # x 방향으로 인접
                if abs(x_max - ox_min) < threshold * 2 or abs(ox_max - x_min) < threshold * 2:
                    return True

            # 수직 정렬 (x 좌표 유사) - 불렛 리스트
            if abs(x_min - ox_min) < threshold:
                if abs(y_max - oy_min) < threshold * 3 or abs(oy_max - y_min) < threshold * 3:
                    return True

        return False

    for region in regions:
        if "bbox" not in region:
            region["constraint"] = "CONTEXT_AWARE"
            continue

        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min
        area = width * height
        text = region.get("ocr_text", "")
        text_len = len(text)

        # config에서 임계값 로드
        nearby_threshold = cfg('layout.nearby_threshold', 80)
        alignment_threshold = cfg('layout.alignment_threshold', 25)
        area_ratio_limit = cfg('layout.area_ratio_limit', 0.015)
        max_label_length = cfg('layout.max_label_length', 15)
        base_aspect = cfg('layout.base_aspect_threshold', 3)
        aspect_per_char = cfg('layout.aspect_per_char', 0.5)

        # 기준 1: 공간적 고립도
        is_isolated = not has_nearby_regions(bbox, threshold=nearby_threshold)

        # 기준 2: 정렬 여부 (문장의 일부인지)
        is_aligned = is_aligned_with_others(bbox, threshold=alignment_threshold)

        # 기준 3: 크기 비율 (전체 이미지 대비)
        area_ratio = area / image_area if image_area > 0 else 0
        is_small = area_ratio < area_ratio_limit

        # 기준 4: 종횡비 (동적 - 텍스트 길이 고려)
        aspect_ratio = width / height if height > 0 else 1
        dynamic_threshold = base_aspect + (text_len * aspect_per_char)
        is_label_like = aspect_ratio < dynamic_threshold

        # 기준 5: 텍스트 특성
        has_punctuation = any(c in text for c in ".,;:!?")
        starts_with_bullet = text.startswith(("-", "•", "·", "ㆍ", "●"))

        # 종합 판단
        if is_isolated and is_small and is_label_like and text_len < max_label_length and not has_punctuation and not starts_with_bullet and not is_aligned:
            region["constraint"] = "STRICT_LITERAL"
        else:
            region["constraint"] = "CONTEXT_AWARE"

    return regions


# ============================================================
# Surya OCR 모델 싱글톤
# ============================================================
def get_surya_models():
    """Surya OCR 모델 싱글톤 - 최초 1회만 로드"""
    global _surya_det_model, _surya_det_processor, _surya_rec_model, _surya_rec_processor

    if _surya_det_model is not None:
        return (_surya_det_model, _surya_det_processor, _surya_rec_model, _surya_rec_processor)

    print("[Surya] OCR 모델 최초 로드 중...")

    from surya.detection import DetectionPredictor
    from surya.recognition import RecognitionPredictor

    # Detection 모델 로드
    print("  Detection 모델 로드...")
    _surya_det_processor = DetectionPredictor()

    # Recognition 모델 로드
    print("  Recognition 모델 로드...")
    _surya_rec_processor = RecognitionPredictor()

    print("[Surya] 모델 로드 완료! (전역 캐시됨)")
    return (_surya_det_model, _surya_det_processor, _surya_rec_model, _surya_rec_processor)


def unload_surya_models():
    """Surya OCR 모델 언로드 (메모리 해제)"""
    global _surya_det_model, _surya_det_processor, _surya_rec_model, _surya_rec_processor

    if _surya_det_processor is None:
        print("[Surya] 언로드할 모델 없음")
        return

    print("[Surya] 모델 언로드 중...")
    del _surya_det_model, _surya_det_processor, _surya_rec_model, _surya_rec_processor
    _surya_det_model = None
    _surya_det_processor = None
    _surya_rec_model = None
    _surya_rec_processor = None

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print("[Surya] 모델 언로드 완료")


# ============================================================
# 1단계: OCR - Surya OCR (Transformer 기반, 한글 정확도 향상)
# ============================================================
def stage_ocr_surya(image_path: str) -> list:
    """Surya OCR로 텍스트 영역 추출 (Transformer 기반, 레이아웃 인식 포함)"""
    print("\n" + "=" * 60)
    print("[1/3] OCR: 텍스트 영역 감지 (Surya OCR - Transformer)")
    print("=" * 60)

    from surya.foundation import FoundationPredictor
    from surya.detection import DetectionPredictor
    from surya.recognition import RecognitionPredictor

    # 이미지 로드
    image = Image.open(image_path).convert("RGB")

    # 모델 로드 (v0.17+ API: FoundationPredictor 필요)
    print("  Surya 모델 로드 중... (캐시 확인)")
    foundation_predictor = FoundationPredictor()
    det_predictor = DetectionPredictor()
    rec_predictor = RecognitionPredictor(foundation_predictor)

    # Detection + Recognition 실행 (v0.17+: 언어 자동 감지)
    print("  텍스트 영역 감지 및 인식 중...")
    rec_results = rec_predictor([image], det_predictor=det_predictor)

    regions = []
    skipped_low_conf = 0

    # 결과 처리
    for page_result in rec_results:
        for line in page_result.text_lines:
            # OCR 직후 즉시 정규화 (HTML 태그 제거 등)
            text = normalize_ocr_text(line.text.strip())
            confidence = line.confidence

            if not text:
                continue

            # 낮은 신뢰도 필터링 (0.2 미만)
            if confidence < 0.2:
                skipped_low_conf += 1
                continue

            # bbox: [x1, y1, x2, y2]
            bbox = [
                float(line.bbox[0]),
                float(line.bbox[1]),
                float(line.bbox[2]),
                float(line.bbox[3])
            ]

            # 스킵 조건 확인
            skip_translate = is_number_or_english_only(text)
            passthrough = is_passthrough_content(text)
            has_math = contains_math_markup(text)
            is_code = is_code_block(text)
            is_single_char = is_single_char_korean(text)
            is_chinese = is_chinese_garbage(text)  # 한자 오인식 필터
            text_has_korean = has_korean(text)

            # 수식이 있어도 한글이 있으면 스킵하지 않음 (수식 제거 후 번역)
            math_skip = has_math and not text_has_korean

            regions.append({
                "bbox": bbox,
                "ocr_text": text,
                "confidence": float(confidence),
                "skip_translate": skip_translate or passthrough or math_skip or is_code or is_chinese,  # 1글자 한글은 스킵 안 함 (맥락 번역)
                "passthrough": passthrough,  # 이메일/URL 등 보존 필요
                "has_math": has_math,  # 수식 마크업 포함
                "is_code": is_code,  # 프로그래밍 코드
                "is_single_char": is_single_char,  # 1글자 한글 (맥락과 함께 번역)
                "is_chinese": is_chinese,  # 한자 오인식
            })

            if is_chinese:
                status = "(한자스킵)"
            elif is_code:
                status = "(코드스킵)"
            elif is_single_char:
                status = "(1글자)"  # 스킵 안 함, 맥락과 함께 번역
            elif math_skip:
                status = "(수식스킵)"
            elif has_math and text_has_korean:
                status = "(수식+한글)"  # 수식 제거 후 번역 예정
            elif passthrough:
                status = "(Pass-through)"
            elif skip_translate:
                status = "(스킵)"
            else:
                status = ""
            conf_str = f"[{confidence:.2f}]"
            print(f"  영역 {len(regions)}: '{text[:25]}' {conf_str} {status}")

    print(f"\n  총 {len(regions)}개 영역 감지 (저신뢰 {skipped_low_conf}개 제외)")

    # 메모리 해제 (foundation_predictor 포함)
    del foundation_predictor, det_predictor, rec_predictor
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("  메모리 해제 완료")

    return regions


# ============================================================
# 1단계 (대안): EasyOCR - 텍스트 영역(박스) 추출
# ============================================================
def stage_ocr(image_path: str) -> list:
    """EasyOCR로 텍스트 영역 좌표 추출 (한국어 최적화)"""
    print("\n" + "=" * 60)
    print("[1/3] OCR: 텍스트 영역 감지 (EasyOCR)")
    print("=" * 60)

    import easyocr

    # GPU는 VLM이 사용하므로 EasyOCR은 CPU에서 실행 (메모리 충돌 방지)
    print("  EasyOCR 모델 로드 중... (한국어+영어, CPU)")
    reader = easyocr.Reader(['ko', 'en'], gpu=False)

    print("  텍스트 영역 추출 중...")
    result = reader.readtext(image_path)

    regions = []
    skipped_low_conf = 0

    for detection in result:
        box = detection[0]
        # OCR 직후 즉시 정규화 (HTML 태그 제거 등)
        text = normalize_ocr_text(detection[1])
        confidence = detection[2]

        if not text:
            continue

        # 강의 PDF는 깨끗하므로 낮은 신뢰도도 허용 (0.2 미만만 제외)
        if confidence < 0.2:
            skipped_low_conf += 1
            continue

        x_coords = [float(p[0]) for p in box]
        y_coords = [float(p[1]) for p in box]
        bbox = [min(x_coords), min(y_coords), max(x_coords), max(y_coords)]

        # 스킵 조건 확인
        skip_translate = is_number_or_english_only(text)
        has_math = contains_math_markup(text)
        is_code = is_code_block(text)
        is_single_char = is_single_char_korean(text)
        is_chinese = is_chinese_garbage(text)  # 한자 오인식 필터
        text_has_korean = has_korean(text)

        # 수식이 있어도 한글이 있으면 스킵하지 않음
        math_skip = has_math and not text_has_korean

        regions.append({
            "bbox": bbox,
            "ocr_text": text,
            "confidence": float(confidence),
            "skip_translate": skip_translate or math_skip or is_code or is_chinese,  # 1글자 한글은 스킵 안 함 (맥락 번역)
            "has_math": has_math,
            "is_code": is_code,
            "is_single_char": is_single_char,  # 1글자 한글 (맥락과 함께 번역)
            "is_chinese": is_chinese,  # 한자 오인식
        })

        if is_chinese:
            status = "(한자스킵)"
        elif is_code:
            status = "(코드스킵)"
        elif is_single_char:
            status = "(1글자)"  # 스킵 안 함, 맥락과 함께 번역
        elif math_skip:
            status = "(수식스킵)"
        elif has_math and text_has_korean:
            status = "(수식+한글)"
        elif skip_translate:
            status = "(스킵)"
        else:
            status = ""
        conf_str = f"[{confidence:.2f}]"
        print(f"  영역 {len(regions)}: '{text[:20]}' {conf_str} {status}")

    print(f"\n  총 {len(regions)}개 영역 감지 (저신뢰 {skipped_low_conf}개 제외)")

    del reader
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("  GPU 메모리 해제 완료")

    return regions


# ============================================================
# 1단계 (대안): RapidOCR - 텍스트 영역(박스) 추출
# ============================================================
def stage_ocr_rapid(image_path: str) -> list:
    """RapidOCR로 텍스트 영역 좌표 추출 (PaddleOCR 모델 기반, ONNX 런타임)"""
    print("\n" + "=" * 60)
    print("[1/3] OCR: 텍스트 영역 감지 (RapidOCR)")
    print("=" * 60)

    from rapidocr_onnxruntime import RapidOCR

    print("  RapidOCR 모델 로드 중... (한국어)")

    # 한국어 모델 경로 (npm run setup에서 다운로드됨)
    models_dir = Path(__file__).parent / "models" / "rapidocr_korean"
    det_model = models_dir / "detection" / "v3" / "det.onnx"
    rec_model = models_dir / "languages" / "korean" / "rec.onnx"
    rec_keys = models_dir / "languages" / "korean" / "dict.txt"

    # 한국어 모델이 있으면 사용, 없으면 기본 모델
    if det_model.exists() and rec_model.exists() and rec_keys.exists():
        print(f"  한국어 모델 사용: {models_dir}")
        ocr = RapidOCR(
            det_model_path=str(det_model),
            rec_model_path=str(rec_model),
            rec_keys_path=str(rec_keys),
        )
    else:
        print("  [경고] 한국어 모델 없음, 기본 모델 사용 (npm run setup 필요)")
        ocr = RapidOCR()

    print("  텍스트 영역 추출 중...")
    result, elapse_info = ocr(image_path)
    # elapse_info는 (det_time, cls_time, rec_time) 튜플 또는 총 시간
    if isinstance(elapse_info, (list, tuple)):
        elapse = sum(elapse_info) if elapse_info else 0
    else:
        elapse = elapse_info or 0

    regions = []

    # RapidOCR 결과: [[box, text, confidence], ...]
    # box = [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    if result:
        for detection in result:
            box = detection[0]
            # OCR 직후 즉시 정규화 (HTML 태그 제거 등)
            text = normalize_ocr_text(detection[1])
            confidence = detection[2]

            if not text:
                continue

            # box 좌표를 [x_min, y_min, x_max, y_max] 형태로 변환
            x_coords = [point[0] for point in box]
            y_coords = [point[1] for point in box]
            bbox = [
                float(min(x_coords)),
                float(min(y_coords)),
                float(max(x_coords)),
                float(max(y_coords))
            ]

            # 스킵 조건 확인
            skip_translate = is_number_or_english_only(text)
            has_math = contains_math_markup(text)
            is_code = is_code_block(text)
            is_single_char = is_single_char_korean(text)
            is_chinese = is_chinese_garbage(text)  # 한자 오인식 필터
            text_has_korean = has_korean(text)

            # 수식이 있어도 한글이 있으면 스킵하지 않음
            math_skip = has_math and not text_has_korean

            regions.append({
                "bbox": bbox,
                "ocr_text": text,
                "confidence": float(confidence),
                "skip_translate": skip_translate or math_skip or is_code or is_chinese,  # 1글자 한글은 스킵 안 함 (맥락 번역)
                "has_math": has_math,
                "is_code": is_code,
                "is_single_char": is_single_char,  # 1글자 한글 (맥락과 함께 번역)
                "is_chinese": is_chinese,  # 한자 오인식
            })

            if is_chinese:
                status = "(한자스킵)"
            elif is_code:
                status = "(코드스킵)"
            elif is_single_char:
                status = "(1글자)"  # 스킵 안 함, 맥락과 함께 번역
            elif math_skip:
                status = "(수식스킵)"
            elif has_math and text_has_korean:
                status = "(수식+한글)"
            elif skip_translate:
                status = "(스킵)"
            else:
                status = ""
            print(f"  영역 {len(regions)}: '{text[:20]}' {status}")

    print(f"\n  총 {len(regions)}개 영역 감지 (소요: {elapse:.2f}초)")

    # 메모리 해제
    del ocr
    gc.collect()

    return regions


# ============================================================
# 2단계: 번역 - 전체 이미지 + OCR 텍스트 활용
# ============================================================
def stage_translate(image_path: str, regions: list) -> list:
    """전체 슬라이드 맥락 + OCR 텍스트로 번역 (환각 방지)"""
    print("\n" + "=" * 60)
    print("[2/3] 번역: 전체 슬라이드 맥락 + OCR 텍스트 (Qwen3-VL)")
    print("=" * 60)

    # 이미지 크기 가져오기 (레이아웃 분류용)
    original_image = Image.open(image_path).convert("RGB")
    image_size = original_image.size

    # 인접한 불완전 문장 병합 (VLM 매핑 밀림 방지)
    regions = merge_adjacent_regions(regions)

    # 레이아웃 기반 분류 적용
    regions = classify_text_regions(regions, image_size)

    # 번역할 텍스트 필터링
    to_translate = []
    code_korean_strings = []  # 코드 내 한글 문자열 (region_idx, 원본문자열)

    for i, region in enumerate(regions):
        if region.get("skip_translate", False):
            # 코드 영역이면서 따옴표 안에 한글이 있는 경우 추출
            if region.get("is_code", False):
                korean_strings = extract_korean_in_quotes(region["ocr_text"])
                if korean_strings:
                    for ks in korean_strings:
                        code_korean_strings.append((i, ks))
                    print(f"  [{i+1}] 코드 (한글 {len(korean_strings)}개): '{region['ocr_text'][:20]}'")
                else:
                    print(f"  [{i+1}] 스킵 (코드): '{region['ocr_text'][:20]}'")
            elif region.get("is_chinese", False):
                print(f"  [{i+1}] 스킵 (한자오인식): '{region['ocr_text'][:20]}'")
            else:
                print(f"  [{i+1}] 스킵 (영어/숫자): '{region['ocr_text'][:20]}'")
            region["english"] = region["ocr_text"]
            continue

        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min

        min_area = cfg('ocr.min_area', 500)
        if width * height < min_area:
            region["english"] = region["ocr_text"]
            print(f"  [{i+1}] 스킵 (작음): '{region['ocr_text'][:20]}'")
            continue

        # <br>로 연결된 텍스트 분리 처리
        br_lines = split_br_lines(region["ocr_text"])
        if len(br_lines) > 1:
            region["br_lines"] = br_lines  # 나중에 개별 번역용
            print(f"  [{i+1}] '{region['ocr_text'][:25]}' (<br> {len(br_lines)}줄)")
        else:
            print(f"  [{i+1}] '{region['ocr_text'][:25]}'")

        to_translate.append((i, region))

    if not to_translate:
        print("  번역할 텍스트 없음")
        return regions

    print(f"\n  번역 대상: {len(to_translate)}개")

    # 전역 모델 사용
    model, processor = get_vlm_model()
    print("  모델 준비 완료 (캐시됨)")

    # 번역할 텍스트 리스트 생성 (<br> 분리 + 코드 내 한글 포함)
    text_lines = []
    line_mapping = []  # (원래_region_idx, br_line_idx 또는 None, code_string 또는 None)
    prefix_mapping = {}  # {line_num: prefix} - 접두 기호 보존용

    for idx, (orig_idx, region) in enumerate(to_translate):
        br_lines = region.get('br_lines')
        region_has_math = region.get('has_math', False)

        if br_lines and len(br_lines) > 1:
            # <br>로 분리된 텍스트는 개별적으로 번역
            for br_idx, br_line in enumerate(br_lines):
                line_num = len(text_lines) + 1
                # HTML 태그 제거 (OCR이 <b>, <i> 등을 포함할 수 있음)
                br_line = strip_html_tags(br_line)
                # 수식 마크업 제거 (수식+한글인 경우)
                clean_line = strip_math_markup(br_line) if region_has_math else br_line
                # 접두 기호 분리
                prefix, content = extract_prefix_symbol(clean_line)
                if prefix:
                    prefix_mapping[line_num] = prefix
                text_lines.append(f"{line_num}. {content}")
                line_mapping.append((orig_idx, br_idx, None))
        else:
            # 일반 텍스트
            line_num = len(text_lines) + 1
            ocr_text = region['ocr_text']
            # HTML 태그 제거 (OCR이 <b>, <i> 등을 포함할 수 있음)
            ocr_text = strip_html_tags(ocr_text)
            # 수식 마크업 제거 (수식+한글인 경우)
            clean_text = strip_math_markup(ocr_text) if region_has_math else ocr_text
            # 접두 기호 분리
            prefix, content = extract_prefix_symbol(clean_text)
            if prefix:
                prefix_mapping[line_num] = prefix
            text_lines.append(f"{line_num}. {content}")
            line_mapping.append((orig_idx, None, None))

    # 코드 내 한글 문자열도 번역 대상에 추가 (기호 분리 불필요)
    for region_idx, korean_string in code_korean_strings:
        line_num = len(text_lines) + 1
        text_lines.append(f"{line_num}. {korean_string}")
        line_mapping.append((region_idx, None, korean_string))  # code_string 마커

    if prefix_mapping:
        print(f"\n  접두 기호 감지: {len(prefix_mapping)}개 (▶, •, ◦ 등)")

    text_list = "\n".join(text_lines)
    total_lines = len(text_lines)

    # 페이지 전체 맥락 수집 (다의어 번역 정확도 향상)
    page_context_items = [r["ocr_text"] for r in regions if r.get("ocr_text")]
    page_context = ", ".join(page_context_items[:20])  # 최대 20개 (토큰 제한)
    print(f"\n  페이지 맥락: {len(page_context_items)}개 텍스트 영역")

    def call_vlm_and_parse(text_list: str, total_lines: int, attempt: int = 1) -> dict:
        """VLM 호출 + 응답 파싱 (재시도 지원)"""
        PROMPT = f"""Translate Korean to English for a lecture slide.

[PAGE CONTEXT]
{page_context}

[TRANSLATE]
{text_list}

RULES:
1. Output EXACTLY {total_lines} lines, format: "1. translation"
2. Use PAGE CONTEXT to disambiguate ambiguous/short terms
3. Standard academic terminology (supervised, regression, etc.)
4. Never romanize - translate to English
5. KEEP: emails, URLs, filenames, code syntax (printf, cout, %d, <<, >>)
6. SHORT labels (1-3 words) → CONCISE translation (1-3 words)
7. No extra words, no HTML tags, no [OCR] tags

Translate:"""

        # 이미지 없이 텍스트만 전달 (시각적 간섭 방지, 텍스트 맥락만 활용)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                ],
            },
        ]

        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=None, return_tensors="pt").to(model.device)

        # 재시도 시 temperature 약간 높임
        temp = 0.3 if attempt == 1 else 0.5

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=2048,  # 텍스트 영역이 많을 때 잘림 방지
                temperature=temp,
                do_sample=True,
            )

        input_len = inputs["input_ids"].shape[1]
        response = processor.decode(outputs[0][input_len:], skip_special_tokens=True).strip()

        if attempt > 1:
            print(f"\n  [재시도 {attempt}] VLM 응답:\n{response[:300]}...")
        else:
            print(f"\n  VLM 응답:\n{response[:300]}...")

        # 응답 파싱 (번호 기반 또는 순서 기반)
        lines = response.strip().split("\n")
        translation_map = {}  # {번호: 번역}
        plain_translations = []  # 번호 없는 번역들

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 다양한 포맷 지원: "1. text", "1: text", "1) text", "1 - text"
            match = re.match(r'^(\d+)\s*[\.:\)\-]\s*(.+)$', line)
            if match:
                try:
                    num = int(match.group(1))
                    trans = match.group(2).strip().strip('"\'')
                    if trans:
                        translation_map[num] = trans
                except ValueError:
                    pass
            else:
                # 번호 없는 응답 (plain text)
                plain_translations.append(line.strip('"\''))

        # 번호 기반 Dictionary 매핑만 사용 (순서 기반 폴백 제거 - 밀림 방지)
        # 유효 범위 내 번호만 유지 (1 ~ total_lines)
        valid_map = {k: v for k, v in translation_map.items() if 1 <= k <= total_lines}

        matched = len(valid_map)
        extra = len(translation_map) - matched
        missing = total_lines - matched

        if matched == total_lines:
            print(f"\n  번호 기반 매핑 완료 ({matched}/{total_lines}개)")
        elif matched > 0:
            print(f"\n  번호 기반 부분 매핑 ({matched}/{total_lines}개, 미매칭 {missing}개)")
            if extra > 0:
                print(f"    범위 외 응답 {extra}개 무시됨")
        else:
            # 번호 없이 응답한 경우에만 순서 기반 시도 (최후 수단)
            if plain_translations and len(plain_translations) == total_lines:
                print(f"\n  [경고] 번호 없음 - 순서 기반 매핑 ({len(plain_translations)}개)")
                valid_map = {i + 1: plain_translations[i] for i in range(len(plain_translations))}
            else:
                print(f"\n  [경고] 매핑 실패 (번호 {matched}개, plain {len(plain_translations)}개)")

        return valid_map

    # VLM 호출 (재시도 로직 포함)
    MAX_RETRIES = 2
    translation_map = {}

    for attempt in range(1, MAX_RETRIES + 1):
        translation_map = call_vlm_and_parse(text_list, total_lines, attempt)

        # 번역 충분한지 확인
        if len(translation_map) >= total_lines:
            break
        elif len(translation_map) >= total_lines * 0.8:
            # 80% 이상이면 OK
            print(f"\n  [경고] 번역 부족하지만 진행 ({len(translation_map)}/{total_lines}개, {len(translation_map)/total_lines*100:.0f}%)")
            break
        elif attempt < MAX_RETRIES:
            print(f"\n  [경고] 번역 부족 ({len(translation_map)}/{total_lines}개) - 재시도 중...")
        else:
            print(f"\n  [경고] 번역 부족 ({len(translation_map)}/{total_lines}개) - 최대 재시도 도달")

    # 개별 번역 폴백: 배치 번역 실패한 항목에 대해 하나씩 번역 시도
    missing_lines = [i for i in range(1, total_lines + 1) if i not in translation_map]
    if missing_lines and len(missing_lines) <= 5:  # 최대 5개까지만 개별 번역 (성능 고려)
        print(f"\n  [개별 번역 폴백] {len(missing_lines)}개 항목 개별 번역 시도...")

        for line_num in missing_lines:
            korean_text = text_lines[line_num - 1].split('. ', 1)[-1]  # "1. 텍스트" → "텍스트"

            # 간결한 개별 번역 프롬프트
            individual_prompt = f"""Translate this Korean text to English. Return ONLY the English translation, nothing else.

Korean: {korean_text}

English:"""

            messages = [{"role": "user", "content": [{"type": "text", "text": individual_prompt}]}]
            text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = processor(text=[text], images=None, return_tensors="pt").to(model.device)

            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=256,
                    temperature=0.3,
                    do_sample=True,
                )

            input_len = inputs["input_ids"].shape[1]
            individual_result = processor.decode(outputs[0][input_len:], skip_special_tokens=True).strip()

            # 결과 정리 (번호 제거, 따옴표 제거)
            individual_result = re.sub(r'^\d+\s*[\.:\)\-]\s*', '', individual_result)
            individual_result = individual_result.strip().strip('"\'')

            if individual_result and not re.search(r'[가-힣]', individual_result):  # 한글이 없으면 성공
                translation_map[line_num] = individual_result
                print(f"    [{line_num}] '{korean_text[:20]}' → '{individual_result[:30]}'")
            else:
                print(f"    [{line_num}] '{korean_text[:20]}' → (개별 번역 실패)")

    print(f"\n  파싱된 번역: {len(translation_map)}개")

    # line_mapping을 사용하여 region별 번역 재조합
    region_translations = {}  # {region_idx: [번역1, 번역2, ...] 또는 단일 번역}
    code_string_translations = {}  # {(region_idx, korean_string): english_string}

    for line_num, (region_idx, br_idx, code_string) in enumerate(line_mapping, start=1):
        if line_num in translation_map:
            trans = translation_map[line_num]
            # 불필요한 태그 제거
            trans = re.sub(r'^\d+\s*[\.:\)\-]\s*', '', trans)
            trans = re.sub(r'\s*\[OCR[^\]]*\]?\s*$', '', trans)
            trans = re.sub(r'\s*\[OCR\s*$', '', trans)
            trans = re.sub(r'<br\s*/?>', ' ', trans)
            trans = re.sub(r'\s+', ' ', trans).strip()

            # 접두 기호 복원 (코드 문자열 제외)
            if code_string is None and line_num in prefix_mapping:
                trans = restore_prefix_symbol(prefix_mapping[line_num], trans)

            if code_string is not None:
                # 코드 내 한글 문자열 번역
                code_string_translations[(region_idx, code_string)] = trans
            elif br_idx is not None:
                # <br> 분리된 텍스트
                if region_idx not in region_translations:
                    region_translations[region_idx] = []
                region_translations[region_idx].append(trans)
            else:
                # 일반 텍스트
                region_translations[region_idx] = trans

    # region에 번역 결과 적용 (기호 후처리 포함)
    for idx, (region_idx, region) in enumerate(to_translate):
        if region_idx in region_translations:
            trans_result = region_translations[region_idx]
            if isinstance(trans_result, list):
                # <br> 분리된 텍스트 → " / "로 연결
                english = " / ".join(trans_result)
                print(f"  [{region_idx+1}] '{region['ocr_text'][:15]}' → '{english[:30]}' (<br> {len(trans_result)}줄)")
            else:
                english = trans_result
                print(f"  [{region_idx+1}] '{region['ocr_text'][:15]}' → '{english[:30]}'")

            # HTML 태그 제거 (기호 변환은 비활성화 - 원본 기호 유지)
            english = strip_html_tags(english.strip())
            # post_process_symbols 제거: 원본 기호 보존 (☑, ▼ 등)
            region["english"] = english
        else:
            # 번역 실패 시 원본 유지
            region["english"] = region["ocr_text"]
            print(f"  [{region_idx+1}] '{region['ocr_text'][:15]}' → (번역 없음, 원본 유지)")

    # 코드 영역 내 한글 문자열은 번역하지 않음 (코드 무결성 유지)
    # System.out.print("안녕하세요") 같은 문자열 리터럴은 원본 유지

    print(f"\n  {len(to_translate)}개 영역 번역 완료")

    # 세로 텍스트 감지 및 render_skip 설정 (JSON 저장 전에 미리 표시)
    vertical_count = 0
    for region in regions:
        if region.get("skip_translate"):
            continue
        bbox = region.get("bbox", [0, 0, 0, 0])
        ocr_text = region.get("ocr_text", "")
        if is_vertical_text_region(bbox, ocr_text):
            region["is_vertical"] = True
            region["render_skip"] = True
            vertical_count += 1
    if vertical_count > 0:
        print(f"  세로 텍스트 감지: {vertical_count}개 (render_skip=True)")

    # 메모리 해제 (original_image만 - inputs/outputs는 nested function 내부)
    del original_image
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("  GPU 메모리 해제 완료")

    return regions


# ============================================================
# 3단계: 오버레이 (OpenCV Inpainting + 텍스트 렌더링)
# ============================================================
def stage_overlay(image_path: str, regions: list, output_path: str):
    """번역된 텍스트 오버레이 (Inpainting으로 자연스러운 배경 복원)"""
    print("\n" + "=" * 60)
    print("[3/3] 오버레이: Inpainting + 텍스트 렌더링")
    print("=" * 60)

    img = Image.open(image_path).convert("RGB")
    img_np = np.array(img)

    # 1단계: 번역 대상 영역 수집 및 마스크 생성
    mask = np.zeros(img_np.shape[:2], dtype=np.uint8)
    translate_regions = []

    def get_font(size):
        # 유니코드 기호 지원 폰트 (☑, ▶, 📦 등)
        # Noto Sans KR이 유니코드 기호 커버리지가 가장 좋음
        font_paths = [
            "C:/Windows/Fonts/NotoSansKR-Regular.ttf",  # Noto - 유니코드 기호 지원 best
            "C:/Windows/Fonts/malgun.ttf",     # 맑은 고딕 (한글)
            "C:/Windows/Fonts/segoeui.ttf",    # Segoe UI
            "C:/Windows/Fonts/arial.ttf",      # Arial
            "arial.ttf",
        ]
        for font_path in font_paths:
            try:
                return ImageFont.truetype(font_path, size)
            except:
                continue
        return ImageFont.load_default()

    def smart_break_word(word: str, max_width: float, font, draw) -> list:
        """
        긴 단어를 하이픈으로 분리 (10자 이상만 대상)

        우선순위:
        1. 영어 접미사 경계 (-tion, -ing, -ness, -ment 등)
        2. 중간점 분리 (최소 3글자 보장)
        """
        # 10자 미만은 분리하지 않음
        if len(word) < 10:
            return [word]

        # 영어 접미사 패턴
        SUFFIX_PATTERNS = [
            'tion', 'sion', 'ness', 'ment', 'able', 'ible',
            'ful', 'less', 'ing', 'ous', 'ive', 'ence', 'ance'
        ]

        # 접미사 경계에서 분리 시도
        for suffix in SUFFIX_PATTERNS:
            if word.lower().endswith(suffix) and len(word) > len(suffix) + 3:
                prefix = word[:-len(suffix)]
                test_width = draw.textbbox((0, 0), prefix + "-", font=font)[2]
                if test_width <= max_width:
                    # 원래 대소문자 유지
                    original_suffix = word[-len(suffix):]
                    print(f"    [Hyphenate] '{word}' → '{prefix}-' + '{original_suffix}'")
                    return [prefix + "-", original_suffix]

        # 중간점 분리 (최소 3글자 보장)
        for i in range(len(word) // 2, len(word) - 3):
            part1 = word[:i] + "-"
            test_width = draw.textbbox((0, 0), part1, font=font)[2]
            if test_width <= max_width:
                print(f"    [Hyphenate] '{word}' → '{part1}' + '{word[i:]}'")
                return [part1, word[i:]]

        # 분리 불가 → 원본 유지
        return [word]

    def wrap_text_words_only(text: str, max_width: float, font, draw) -> list:
        """단어 단위로만 줄바꿈 (글자 분리 없음)"""
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

    def wrap_text_with_hyphen(text: str, max_width: float, font, draw) -> list:
        """단어 단위 줄바꿈 + 긴 단어는 하이픈 분리"""
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

                # 단어 자체가 박스보다 넓으면 하이픈 분리
                word_width = draw.textbbox((0, 0), word, font=font)[2]
                if word_width > max_width:
                    word_parts = smart_break_word(word, max_width, font, draw)
                    for i, part in enumerate(word_parts):
                        if i < len(word_parts) - 1:
                            lines.append(part)
                        else:
                            current_line = part
                else:
                    current_line = word

        if current_line:
            lines.append(current_line)

        return lines if lines else [text]

    def fit_text_to_box(text: str, max_width: float, max_height: float, font_size: int, draw) -> tuple:
        """
        개선된 텍스트 피팅

        1. 폰트 축소 우선 (최소 8pt)
        2. 단어 단위 줄바꿈
        3. 긴 단어만 하이픈 분리
        4. 그래도 안 맞으면 ellipsis
        """
        MIN_FONT_SIZE = 8  # 기존 6pt → 8pt (가독성)
        initial_font_size = font_size

        # 1단계: 폰트 축소로 해결 시도 (단어 분리 없이)
        for size in range(font_size, MIN_FONT_SIZE - 1, -1):
            font = get_font(size)
            lines = wrap_text_words_only(text, max_width, font, draw)

            line_height = size + 2
            total_height = line_height * len(lines)

            # 모든 단어가 박스에 맞는지 확인
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
                if size < initial_font_size:
                    print(f"    [FitText] font {initial_font_size} → {size}, {len(lines)} line(s)")
                return lines, font, size, line_height

        # 2단계: 최소 폰트에서 하이픈 분리 적용
        font = get_font(MIN_FONT_SIZE)
        lines = wrap_text_with_hyphen(text, max_width, font, draw)
        line_height = MIN_FONT_SIZE + 2

        # 줄 수 제한 (오버플로우 방지)
        max_lines = max(1, int(max_height / line_height))
        if len(lines) > max_lines:
            original_count = len(lines)
            lines = lines[:max_lines]
            if len(lines[-1]) > 1:
                lines[-1] = lines[-1][:-1] + "…"
            print(f"    [Ellipsis] {original_count} lines → {max_lines} lines")

        return lines, font, MIN_FONT_SIZE, line_height

    # 1단계: 번역 대상 영역 수집 및 마스크 생성
    print("  [1/2] 마스크 생성 중...")
    for region in regions:
        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min

        # 너무 작은 영역 스킵
        if width * height < 500:
            continue

        # 스킵 조건 (숫자/영어/한자오인식): 원본 유지
        if region.get("skip_translate", False):
            if region.get("is_chinese", False):
                print(f"    원본 유지 (한자오인식): '{region['ocr_text'][:15]}'")
            else:
                print(f"    원본 유지 (숫자/영어): '{region['ocr_text'][:15]}'")
            continue

        # 세로 텍스트: 이미지에는 렌더링하지 않음 (원본 유지)
        # render_skip 플래그는 stage_translate에서 이미 설정됨
        if region.get("render_skip", False):
            print(f"    [Vertical Skip] '{region['ocr_text'][:15]}' (w={int(width)}, h={int(height)})")
            continue

        english = region.get("english", region["ocr_text"])
        english = english.replace("ㆍ", "•").replace("·", "•").replace("●", "•")

        # 번역이 원본과 같으면 스킵
        if english.strip() == region["ocr_text"].strip():
            continue

        # Prefix 기호 감지 및 정책 결정
        clean_ocr = strip_html_tags(region["ocr_text"])
        prefix_symbol, _ = extract_prefix_symbol(clean_ocr)
        _, english_content = extract_prefix_symbol(english)

        # config 기반 prefix 정책 결정
        policy = get_prefix_policy(prefix_symbol)

        if policy == "preserve":
            # 픽셀 보존: prefix 영역은 원본 유지, 뒤 텍스트만 렌더링
            # 이미지 분석으로 실제 경계 찾기, 실패 시 fallback
            symbol_width = estimate_prefix_pixel_width(prefix_symbol, bbox, img_np)
            render_bbox = [x_min + symbol_width, y_min, x_max, y_max]
            render_text = english_content.strip() if english_content.strip() else english.strip()

            if cfg("prefix_symbols.debug_log", True):
                print(f"    [Prefix Preserve] '{prefix_symbol.strip()}' w={symbol_width}px")
        else:
            # 폰트 렌더링: 전체 bbox 지우고 prefix 포함 영어를 새로 렌더링
            symbol_width = 0
            render_bbox = bbox

            if prefix_symbol:
                render_text = restore_prefix_symbol(prefix_symbol, english)
            else:
                render_text = english

            if cfg("prefix_symbols.debug_log", True) and prefix_symbol:
                print(f"    [Prefix Render] '{prefix_symbol.strip()}' 폰트 렌더링")

        # 마스크에 영역 추가 (기호 영역 제외)
        x_min_int, y_min_int = int(x_min + symbol_width), int(y_min)
        x_max_int, y_max_int = int(x_max), int(y_max)
        if x_min_int < x_max_int:
            mask[y_min_int:y_max_int, x_min_int:x_max_int] = 255

        # 번역 대상 목록에 추가
        translate_regions.append({
            "bbox": render_bbox,
            "english": render_text,
            "ocr_text": region["ocr_text"]
        })

    print(f"    {len(translate_regions)}개 영역 마스크 완료")

    # 2단계: 배경 복원 (단색 → 단색 채우기, 복잡한 배경 → Inpainting)
    def is_solid_background(img_np, bbox, threshold=15):
        """bbox 주변 배경이 단색인지 확인"""
        x_min, y_min, x_max, y_max = [int(v) for v in bbox]
        h, w = img_np.shape[:2]

        # bbox 주변 샘플링 (상하좌우 5px 바깥)
        samples = []
        margin = 5
        positions = [
            (max(0, x_min - margin), y_min + (y_max - y_min) // 2),  # 왼쪽
            (min(w - 1, x_max + margin), y_min + (y_max - y_min) // 2),  # 오른쪽
            (x_min + (x_max - x_min) // 2, max(0, y_min - margin)),  # 위
            (x_min + (x_max - x_min) // 2, min(h - 1, y_max + margin)),  # 아래
        ]
        for px, py in positions:
            if 0 <= px < w and 0 <= py < h:
                samples.append(img_np[py, px])

        if len(samples) < 2:
            return True, (255, 255, 255)

        # 샘플 색상의 표준편차 계산
        samples = np.array(samples)
        std = np.std(samples, axis=0).mean()
        avg_color = tuple(samples.mean(axis=0).astype(int))

        return std < threshold, avg_color

    print("  [2/2] 배경 복원 중...")
    img_pil = Image.fromarray(img_np)
    draw_temp = ImageDraw.Draw(img_pil)

    solid_count = 0
    inpaint_count = 0

    for region in translate_regions:
        bbox = region["bbox"]
        is_solid, bg_color = is_solid_background(img_np, bbox)

        if is_solid:
            # 단색 배경: 직접 채우기 (깔끔함)
            x_min, y_min, x_max, y_max = [int(v) for v in bbox]
            draw_temp.rectangle([x_min, y_min, x_max, y_max], fill=bg_color)
            solid_count += 1
        else:
            # 복잡한 배경: Inpainting 필요 (개별 처리)
            x_min, y_min, x_max, y_max = [int(v) for v in bbox]
            region_mask = np.zeros(img_np.shape[:2], dtype=np.uint8)
            region_mask[y_min:y_max, x_min:x_max] = 255

            img_bgr = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
            inpainted_bgr = cv2.inpaint(img_bgr, region_mask, inpaintRadius=2, flags=cv2.INPAINT_TELEA)
            img_pil = Image.fromarray(cv2.cvtColor(inpainted_bgr, cv2.COLOR_BGR2RGB))
            draw_temp = ImageDraw.Draw(img_pil)
            inpaint_count += 1

    img_np = np.array(img_pil)
    print(f"    단색 채우기: {solid_count}개, Inpainting: {inpaint_count}개")

    # 3단계: PIL 이미지로 변환 후 텍스트 렌더링
    img = Image.fromarray(img_np)
    draw = ImageDraw.Draw(img)

    print("  텍스트 렌더링 중...")
    for region in translate_regions:
        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min
        english = region["english"]

        # 배경색 샘플링 (inpaint된 이미지에서 - bbox 중앙)
        try:
            cx, cy = int((x_min + x_max) / 2), int((y_min + y_max) / 2)
            cx = max(0, min(cx, img.width - 1))
            cy = max(0, min(cy, img.height - 1))
            pixel = img.getpixel((cx, cy))
            if isinstance(pixel, int):
                bg_color = (pixel, pixel, pixel)
            else:
                bg_color = pixel[:3]
        except:
            bg_color = (255, 255, 255)

        # 텍스트 맞추기 (줄바꿈 + 폰트 축소)
        initial_font_size = max(12, int(height * 0.7))
        lines, font, final_font_size, line_height = fit_text_to_box(
            english, width - 4, height - 4, initial_font_size, draw
        )

        # 텍스트 색상 (배경 밝기 기반)
        brightness = sum(bg_color) / 3
        text_color = (0, 0, 0) if brightness > 127 else (255, 255, 255)

        # 텍스트 그리기 (왼쪽 정렬, 세로 중앙)
        total_text_height = line_height * len(lines)
        start_y = y_min + (height - total_text_height) / 2

        for i, line in enumerate(lines):
            text_x = x_min + 2
            text_y = start_y + (i * line_height)
            draw.text((text_x, text_y), line, font=font, fill=text_color)

        fitted_text = " ".join(lines)
        if len(lines) > 1:
            print(f"    '{region['ocr_text'][:15]}' → '{fitted_text[:25]}' ({len(lines)}줄)")
        else:
            print(f"    '{region['ocr_text'][:15]}' → '{fitted_text[:25]}'")

    img.save(output_path)
    img.close()
    print(f"\n  저장됨: {output_path}")

    return output_path


# ============================================================
# 서비스 통합용 함수
# ============================================================
def translate_slide(image_path: str, output_path: str = None, ocr_engine: str = None) -> dict:
    """
    슬라이드 번역 (서비스 통합용)

    Args:
        image_path: 입력 이미지 경로
        output_path: 출력 이미지 경로 (기본: {이름}_translated_v3.png)
        ocr_engine: OCR 엔진 선택 ("surya" 기본값, "easyocr", "rapid" 가능)
                    환경변수 AUNION_OCR_ENGINE 으로도 설정 가능

    Returns:
        dict: {
            "input": 입력 경로,
            "output": 출력 경로,
            "regions": 번역된 영역 리스트,
            "ocr_engine": 사용된 OCR 엔진,
            "success": 성공 여부
        }
    """
    try:
        # OCR 엔진 결정 (인자 > 환경변수 > 기본값)
        if ocr_engine is None:
            ocr_engine = OCR_ENGINE  # 환경변수 또는 기본값 "surya"

        if output_path is None:
            p = Path(image_path)
            output_path = str(p.parent / f"{p.stem}_translated_v3{p.suffix}")

        # 파이프라인 실행 (OCR 엔진 선택)
        if ocr_engine == "surya":
            regions = stage_ocr_surya(image_path)
            # Surya 모델 언로드 (VLM 로드 전 GPU 메모리 확보)
            unload_surya_models()
        elif ocr_engine == "rapid":
            regions = stage_ocr_rapid(image_path)
        else:
            regions = stage_ocr(image_path)  # easyocr (fallback)

        regions = stage_translate(image_path, regions)
        stage_overlay(image_path, regions, output_path)

        return {
            "input": image_path,
            "output": output_path,
            "regions": regions,
            "ocr_engine": ocr_engine,
            "success": True,
        }

    except Exception as e:
        return {
            "input": image_path,
            "output": None,
            "ocr_engine": ocr_engine,
            "error": str(e),
            "success": False,
        }


# ============================================================
# 메인
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="강의 슬라이드 번역 v3")
    parser.add_argument("--image", type=str, required=True, help="입력 이미지")
    parser.add_argument("--output", type=str, default=None, help="출력 이미지")
    parser.add_argument("--ocr", type=str, default=None, choices=["surya", "easyocr", "rapid"],
                        help="OCR 엔진 선택 (surya 기본값 - Transformer, easyocr, rapid 선택 가능)")
    args = parser.parse_args()

    image_path = args.image
    ocr_engine = args.ocr if args.ocr else OCR_ENGINE  # 환경변수 또는 기본값

    if args.output:
        output_path = args.output
    else:
        p = Path(image_path)
        output_path = str(p.parent / f"{p.stem}_translated_v3{p.suffix}")

    print("=" * 60)
    print("강의 슬라이드 번역 파이프라인 v3")
    print("=" * 60)
    print(f"입력: {image_path}")
    print(f"출력: {output_path}")
    print(f"OCR 엔진: {ocr_engine}")

    # 1단계: OCR (엔진 선택)
    if ocr_engine == "surya":
        regions = stage_ocr_surya(image_path)
    elif ocr_engine == "rapid":
        regions = stage_ocr_rapid(image_path)
    else:
        regions = stage_ocr(image_path)  # easyocr

    with open(Path(image_path).stem + "_regions.json", "w", encoding="utf-8") as f:
        json.dump(regions, f, ensure_ascii=False, indent=2)

    # 2단계: 번역
    regions = stage_translate(image_path, regions)

    with open(Path(image_path).stem + "_translated_v3.json", "w", encoding="utf-8") as f:
        json.dump(regions, f, ensure_ascii=False, indent=2)

    # 3단계: 오버레이
    stage_overlay(image_path, regions, output_path)

    print("\n" + "=" * 60)
    print("완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
