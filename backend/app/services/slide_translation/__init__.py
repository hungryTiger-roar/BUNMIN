"""
슬라이드 번역 파이프라인

[파이프라인 구조]
1. PDF Layer 파이프라인: pdf_pipeline.py
   - 텍스트 레이어가 있는 PDF 처리
   - VLM 번역

2. Image OCR 파이프라인: image_pipeline.py
   - 텍스트 레이어가 없는 PDF/이미지 처리
   - Surya OCR → VLM 번역 → Overlay

[용어집]
- config/term_corrections.csv에서 한국어-영어 용어 매핑 로드
- VLM 번역 프롬프트에 자동 포함

[파일 구조 (10개)]
- models.py: 공통 데이터 모델 (TextBlock, FontInfo)
- translator.py: 공통 번역 함수 (translate_blocks)
- pdf_pipeline.py: PDF Layer 파이프라인
- image_pipeline.py: Image OCR 파이프라인 + VLM 모델 관리
- pdf_text_extractor.py: PDF 텍스트 추출
- pdf_text_replacer.py: PDF 텍스트 교체
- pdf_font_handler.py: 폰트 매핑
- bbox_analyzer.py: 레이아웃 분석
- term_corrections.py: CSV 용어집
- __init__.py: 모듈 export
"""

# Data Models
from .models import TextBlock, FontInfo, TranslationResult

# Common Translator
from .translator import translate_blocks

# PDF Layer Pipeline
from .pdf_pipeline import PDFLayerPipeline

# Image Pipeline + VLM
from .image_pipeline import (
    get_vlm_model,
    is_vlm_loaded,
    unload_vlm_model,
    translate_text_vlm,
    stage_ocr_surya,
    stage_translate,
    stage_overlay,
    batch_ocr_surya,
    batch_translate_vlm,
    batch_overlay,
    clear_cache,
    OCRPipeline,
)

# PDF Text Processing
from .pdf_text_extractor import (
    check_pdf_has_text_layer,
    extract_korean_texts_for_translation,
)
from .pdf_text_replacer import replace_texts_in_pdf
from .pdf_font_handler import (
    map_korean_to_english_font,
    int_color_to_rgb,
    rgb_to_int_color,
    estimate_text_width,
)

# Layout Analysis
from .bbox_analyzer import analyze_page_layout

# Term Corrections (CSV-based)
from .term_corrections import (
    load_term_corrections,
    get_mandatory_terms,
    get_terms_in_text,
    build_term_replacer,
    replace_terms_in_text,
    # OCR 보정
    load_ocr_corrections,
    correct_ocr_text,
    build_ocr_corrector,
)
