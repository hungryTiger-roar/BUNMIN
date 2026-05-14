"""
슬라이드 번역 파이프라인

[파이프라인 순서]
1. OCR (Surya) → 텍스트 영역 감지
2. VLM (Qwen2.5-VL) → 번역
3. Overlay → 이미지에 텍스트 렌더링

[용어집]
- config/term_corrections.csv에서 한국어-영어 용어 매핑 로드
- 번역 프롬프트에 자동 포함
"""

from .config import PipelineConfig, get_config, set_config, cfg

# OCR Normalization
from .ocr_normalization import (
    normalize_ocr_regions,
    normalize_text,
    normalize_bbox,
)

# Image Text Extraction
from .image_text_extraction import (
    detect_image_regions,
    extract_image_texts,
)

# Deduplication
from .deduplication import (
    deduplicate_ocr_and_image_texts,
    calculate_text_similarity,
    calculate_bbox_iou,
    is_duplicate_region,
)

# Noise Classification
from .noise_classification import (
    classify_ocr_regions,
    calculate_noise_score,
    classify_region,
    save_classified_regions_with_noise,
    save_excluded_noise_regions,
    get_classification_stats,
    is_valid_english_word,
    is_broken_or_garbled,
    is_decorative_background,
)

# Candidate Extraction
from .candidate_extraction import (
    extract_document_candidates,
)

# Region Classification
from .region_classification import (
    classify_region_type_scored,
    classify_all_regions,
    REGION_TYPES,
)

# Reading Order
from .reading_order import (
    sort_regions_reading_order,
    estimate_page_layout,
)

# Block Building
from .block_building import (
    build_translation_blocks,
    MERGE_POLICY,
)

# Token Protection
from .token_protection import (
    select_glossary_for_block,
    protect_glossary_tokens,
    protect_blocks,
    restore_tokens,
    recover_broken_tokens,
)

# Translation
from .translation import (
    build_translation_prompt,
    translate_blocks_batch,
    retry_semantic_mismatch_blocks,
    retry_residual_korean_blocks,
    retry_token_error_blocks,
)

# Term Corrections (CSV-based)
from .term_corrections import (
    load_term_corrections,
    get_mandatory_terms,
    get_terms_in_text,
)

# Validation
from .validation import (
    validate_and_restore_single_block,
    validate_batch_output,
    generate_quality_report,
    finalize_blocks,
    extract_semantic_mismatch_blocks,
    extract_residual_korean_blocks,
    extract_token_error_blocks,
    BLOCKING_ISSUES,
)

# Image Text Translation (Phase 2)
from .image_text_translation import (
    translate_image_texts,
    validate_image_text_translation,
    save_translated_image_texts,
)

# Image Rendering (Phase 2)
from .image_rendering import (
    process_image_texts_phase2,
    render_english_text,
    process_page_images,
    is_solid_background,
    save_processed_image,
    save_processed_images,
)

# Residual Audit (Phase 3)
from .residual_audit import (
    run_residual_audit,
    audit_blocks,
    audit_image_texts,
    save_audit_report,
    save_review_log,
    extract_failed_regions,
    save_failed_regions,
)

# LLM Client
from .llm_client import (
    BaseLLMClient,
    OpenAIClient,
    AzureOpenAIClient,
    LocalLLMClient,
    MockLLMClient,
    create_llm_client,
    get_default_llm_client,
)

