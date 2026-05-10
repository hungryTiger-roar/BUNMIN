"""
파이프라인 설정
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OCRConfig:
    """OCR 정규화 설정"""
    min_confidence: float = 0.60
    min_text_height_ratio: float = 0.006
    min_korean_chars: int = 2


@dataclass
class ImageTextConfig:
    """이미지 텍스트 처리 설정"""
    enabled: bool = True
    detection_min_area: int = 10000
    extraction_min_confidence: float = 0.5
    overlap_threshold: float = 0.7


@dataclass
class CandidateConfig:
    """후보 추출 설정"""
    min_frequency: int = 1
    short_korean_min_len: int = 2
    short_korean_max_len: int = 4


@dataclass
class GlossaryConfig:
    """Glossary 설정"""
    fuzzy_threshold_short: float = 0.90  # 3글자 이하
    fuzzy_threshold_medium: float = 0.85  # 4-5글자
    fuzzy_threshold_long: float = 0.80  # 6글자 이상


@dataclass
class BlockConfig:
    """Translation Block 설정"""
    merge_threshold: int = 5
    max_union_area_ratio: float = 0.15
    max_union_height_ratio: float = 0.25
    max_y_gap_ratio: float = 0.05
    intervening_overlap_ratio: float = 0.3
    bullet_confirm_threshold: int = 4
    bullet_candidate_threshold: int = 2


@dataclass
class ValidationConfig:
    """검증 설정"""
    max_retry: int = 2
    blocking_issues: list = field(default_factory=lambda: [
        "TOKEN_MISSING",
        "TOKEN_DUPLICATE",
        "TOKEN_ORDER_CHANGED",
        "GLOSSARY_FORCE_VIOLATION"
    ])


@dataclass
class RenderingConfig:
    """렌더링 설정"""
    font_path: str = "fonts/NotoSans-Regular.ttf"
    min_font_size: int = 8
    max_font_size: int = 48


@dataclass
class PipelineConfig:
    """전체 파이프라인 설정"""
    ocr: OCRConfig = field(default_factory=OCRConfig)
    image_text: ImageTextConfig = field(default_factory=ImageTextConfig)
    candidate: CandidateConfig = field(default_factory=CandidateConfig)
    glossary: GlossaryConfig = field(default_factory=GlossaryConfig)
    block: BlockConfig = field(default_factory=BlockConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    rendering: RenderingConfig = field(default_factory=RenderingConfig)

    # 디버그 모드
    debug: bool = False
    save_intermediate: bool = True
    output_dir: str = "output"


# 전역 설정 인스턴스
_config: Optional[PipelineConfig] = None


def get_config() -> PipelineConfig:
    """전역 설정 가져오기"""
    global _config
    if _config is None:
        _config = PipelineConfig()
    return _config


def set_config(config: PipelineConfig):
    """전역 설정 변경"""
    global _config
    _config = config


def cfg(key: str, default=None):
    """설정값 조회 (dot notation 지원)

    예: cfg("ocr.min_confidence", 0.6)
    """
    config = get_config()
    parts = key.split(".")
    value = config

    for part in parts:
        if hasattr(value, part):
            value = getattr(value, part)
        else:
            return default

    return value
