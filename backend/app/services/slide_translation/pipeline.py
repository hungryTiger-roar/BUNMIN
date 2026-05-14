"""
슬라이드 번역 파이프라인 진입점

전체 파이프라인 실행을 위한 메인 함수 제공

사용법:
    from slide_translation.pipeline import run_pipeline

    result = run_pipeline(
        ocr_regions=ocr_data,
        images=page_images,
        output_dir="./output",
        existing_glossary=None,
        llm_client=my_llm_client
    )
"""
import os
import sys
import json
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager

from .config import PipelineConfig, set_config, cfg


class PipelineLogger:
    """파이프라인 로그를 콘솔과 파일에 동시에 출력하는 로거"""

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.log_file = None
        self.start_time = datetime.now()

    def __enter__(self):
        self.log_file = open(self.log_path, "w", encoding="utf-8")
        self._write_header()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.log_file:
            self._write_footer(exc_type is not None)
            self.log_file.close()
            self.log_file = None

    def _write_header(self):
        """로그 파일 헤더 작성"""
        header = f"""{'='*60}
Pipeline Log
Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}
{'='*60}
"""
        self.log_file.write(header)
        self.log_file.flush()

    def _write_footer(self, had_error: bool):
        """로그 파일 푸터 작성"""
        end_time = datetime.now()
        duration = end_time - self.start_time
        status = "FAILED" if had_error else "COMPLETED"
        footer = f"""
{'='*60}
Pipeline {status}
Ended: {end_time.strftime('%Y-%m-%d %H:%M:%S')}
Duration: {duration}
{'='*60}
"""
        self.log_file.write(footer)
        self.log_file.flush()

    def log(self, message: str):
        """메시지를 콘솔과 파일에 동시 출력"""
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        log_line = f"[{timestamp}] {message}"

        # 콘솔 출력
        print(message)

        # 파일 출력
        if self.log_file:
            self.log_file.write(log_line + "\n")
            self.log_file.flush()


# 전역 로거 인스턴스 (파이프라인 실행 중에만 활성화)
_pipeline_logger: Optional[PipelineLogger] = None


def plog(message: str):
    """파이프라인 로깅 함수 - 콘솔과 파일에 동시 출력"""
    global _pipeline_logger
    if _pipeline_logger:
        _pipeline_logger.log(message)
    else:
        print(message)


@contextmanager
def pipeline_logging(output_dir: str):
    """파이프라인 로깅 컨텍스트 매니저"""
    global _pipeline_logger
    log_path = os.path.join(output_dir, "pipeline.log")

    with PipelineLogger(log_path) as logger:
        _pipeline_logger = logger
        try:
            yield logger
        finally:
            _pipeline_logger = None

# 각 단계별 모듈
from .ocr_normalization import normalize_ocr_regions, save_normalized_regions
from .image_text_extraction import detect_image_regions, extract_image_texts, save_image_regions, save_image_texts
from .deduplication import deduplicate_ocr_and_image_texts, save_dedup_results
from .noise_classification import (
    classify_ocr_regions,
    save_classified_regions_with_noise,
    save_excluded_noise_regions,
    get_classification_stats,
)
from .candidate_extraction import extract_document_candidates, save_candidates
from .region_classification import classify_all_regions, save_classified_regions, classify_page_type
from .reading_order import sort_regions_reading_order, estimate_page_layout, save_sorted_regions
from .block_building import build_translation_blocks, save_blocks
from .token_protection import protect_blocks, save_protected_blocks
from .translation import translate_blocks_batch, apply_translations_to_blocks, save_translated_blocks
from .validation import (
    validate_batch_output,
    generate_quality_report,
    finalize_blocks,
    save_final_blocks,
    save_quality_report,
    extract_semantic_mismatch_blocks,
    extract_residual_korean_blocks,
    extract_token_error_blocks,
)
from .translation import (
    retry_semantic_mismatch_blocks,
    retry_residual_korean_blocks,
    retry_token_error_blocks,
)
from .image_text_translation import (
    translate_image_texts,
    save_translated_image_texts,
)
from .image_rendering import (
    process_page_images,
    save_processed_images,
    render_english_text,
    _inpaint_solid_color,
    _get_edge_dominant_color,
    is_solid_background,
)
from .residual_audit import (
    run_residual_audit,
    save_audit_report,
    save_review_log,
    extract_failed_regions,
    save_failed_regions,
    detect_korean_in_final_images,
    save_remaining_korean_regions,
    KOREAN_PATTERN,
    detect_low_confidence_ocr,
    save_low_confidence_review,
    classify_fallback_ocr_text,
)
from .image_text_extraction import extract_text_with_enhanced_ocr


@dataclass
class PipelineResult:
    """파이프라인 실행 결과"""
    success: bool
    output_dir: str

    # 주요 출력 파일 경로
    glossary_path: Optional[str] = None
    blocks_final_path: Optional[str] = None
    quality_report_path: Optional[str] = None
    image_texts_path: Optional[str] = None
    processed_images_dir: Optional[str] = None
    residual_audit_path: Optional[str] = None

    # 통계
    total_pages: int = 0
    total_blocks: int = 0
    blocks_ok: int = 0
    blocks_failed: int = 0

    # 에러 정보
    error: Optional[str] = None
    stage_completed: str = ""

    # 부분 성공 (일부 블록 실패했지만 PDF는 생성됨)
    partial_success: bool = False

    # 상세 결과
    metrics: dict = field(default_factory=dict)

    # 프론트엔드 상태 표시용 (partial status)
    status: str = "pending"  # "success", "partial", "failed", "pending"
    residual_audit_pass: bool = True
    failed_by_reason: dict = field(default_factory=dict)

    def to_frontend_status(self) -> dict:
        """프론트엔드에 전달할 상태 정보"""
        return {
            "status": self.status,
            "total_blocks": self.total_blocks,
            "blocks_ok": self.blocks_ok,
            "blocks_failed": self.blocks_failed,
            "partial_success": self.partial_success,
            "residual_audit_pass": self.residual_audit_pass,
            "failed_by_reason": self.failed_by_reason,
            "error": self.error,
            "stage_completed": self.stage_completed,
            "message": self._generate_status_message(),
        }

    def _generate_status_message(self) -> str:
        """상태 메시지 생성"""
        if self.success:
            return "Translation completed successfully"

        if self.partial_success:
            parts = []
            parts.append(f"Partial success: {self.blocks_ok}/{self.total_blocks} blocks translated")
            if self.blocks_failed > 0:
                parts.append(f"({self.blocks_failed} failed)")
            if not self.residual_audit_pass:
                parts.append("Residual audit: FAIL")
            return " ".join(parts)

        if self.error:
            return f"Failed at {self.stage_completed}: {self.error}"

        return "Unknown status"


@dataclass
class PipelineInput:
    """파이프라인 입력 데이터"""
    # OCR 결과 (페이지별)
    ocr_regions: list[list[dict]]

    # 페이지 이미지 (optional, 이미지 텍스트 추출용)
    images: Optional[list[Any]] = None

    # 페이지 크기 (width, height)
    page_sizes: Optional[list[tuple[int, int]]] = None

    # 기존 glossary (있으면 병합)
    existing_glossary: Optional[dict] = None


def run_pipeline(
    ocr_regions: list[list[dict]],
    output_dir: str,
    images: Optional[list] = None,
    page_sizes: Optional[list[tuple[int, int]]] = None,
    existing_glossary: Optional[dict] = None,
    llm_client: Optional[Any] = None,
    config: Optional[PipelineConfig] = None,
    skip_image_text: bool = False,
    skip_translation: bool = False,
) -> PipelineResult:
    """슬라이드 번역 파이프라인 실행

    Args:
        ocr_regions: 페이지별 OCR region 리스트
        output_dir: 출력 디렉토리
        images: 페이지 이미지 리스트 (optional)
        page_sizes: 페이지 크기 리스트 [(w, h), ...]
        existing_glossary: 기존 glossary (optional)
        llm_client: LLM 클라이언트 (None이면 mock)
        config: 파이프라인 설정 (optional)
        skip_image_text: 이미지 텍스트 추출 스킵
        skip_translation: 번역 스킵 (블록 생성까지만)

    Returns:
        PipelineResult
    """
    # 설정 적용
    if config:
        set_config(config)

    # 출력 디렉토리 생성
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 기본 페이지 크기
    if page_sizes is None:
        page_sizes = [(1920, 1080) for _ in ocr_regions]

    result = PipelineResult(
        success=False,
        output_dir=output_dir,
        total_pages=len(ocr_regions)
    )

    # 로깅 컨텍스트 시작
    with pipeline_logging(output_dir):
        try:
            # ===== Phase 1: 전처리 =====

            # Step 1-1: OCR Normalization
            plog("[Pipeline] Step 1-1: OCR Normalization")
            all_normalized = []
            for page_no, page_regions in enumerate(ocr_regions):
                page_size = page_sizes[page_no] if page_no < len(page_sizes) else (1920, 1080)
                normalized = normalize_ocr_regions(page_regions, page_size)
                all_normalized.append(normalized)

            save_normalized_regions(
                _flatten_pages(all_normalized),
                str(output_path / "regions.normalized.json")
            )
            result.stage_completed = "ocr_normalization"

            # Step 1-2: Image Text Extraction (optional)
            image_regions = []
            image_texts = []

            if not skip_image_text and images:
                plog("[Pipeline] Step 1-2: Image Text Extraction")
                for page_no, (image, page_regions) in enumerate(zip(images, all_normalized)):
                    # 이미지 영역 감지
                    regions = detect_image_regions(image, page_regions)
                    for r in regions:
                        r["page_no"] = page_no + 1
                    image_regions.extend(regions)

                    # 텍스트 추출 (각 이미지 영역별로)
                    for img_region in regions:
                        texts = extract_image_texts(img_region, image, page_no + 1)
                        image_texts.extend(texts)

                save_image_regions(image_regions, str(output_path / "image_regions.json"))
                save_image_texts(image_texts, str(output_path / "image_texts.raw.json"))
                result.stage_completed = "image_text_extraction"

            # Step 1-3: Deduplication
            plog("[Pipeline] Step 1-3: Deduplication")
            flat_ocr = _flatten_pages(all_normalized)
            dedup_ocr, dedup_image_texts, dedup_report = deduplicate_ocr_and_image_texts(
                flat_ocr, image_regions, image_texts
            )
            save_dedup_results(dedup_ocr, dedup_image_texts, dedup_report, output_dir)
            result.stage_completed = "deduplication"

            # Step 1-3b: Noise Classification
            plog("[Pipeline] Step 1-3b: Noise Classification")
            all_texts_for_dedup = [r.get("ocr_text", "") for r in dedup_ocr]
            classified_ocr = []
            excluded_noise = []

            for page_no, page_size in enumerate(page_sizes):
                page_dedup = [r for r in dedup_ocr if r.get("page_no", page_no + 1) == page_no + 1]
                classified, excluded = classify_ocr_regions(page_dedup, page_size, all_texts_for_dedup)
                for r in excluded:
                    r["page_no"] = page_no + 1
                classified_ocr.extend(classified)
                excluded_noise.extend(excluded)

            save_classified_regions_with_noise(classified_ocr, str(output_path / "regions.noise_classified.json"))
            save_excluded_noise_regions(excluded_noise, str(output_path / "excluded_noise_regions.json"))
            stats = get_classification_stats(classified_ocr + excluded_noise)
            plog(f"  Total: {stats['total']}, Excluded: {len(excluded_noise)}")
            for classification, count in stats["by_classification"].items():
                plog(f"    {classification}: {count}")

            # Update all_normalized with classified results
            all_normalized = []
            for page_no in range(len(page_sizes)):
                page_classified = [r for r in classified_ocr if r.get("page_no", page_no + 1) == page_no + 1]
                all_normalized.append(page_classified)
            result.stage_completed = "noise_classification"


            # Step 1-4: Document Candidate Extraction
            plog("[Pipeline] Step 1-4: Document Candidate Extraction")
            candidates = extract_document_candidates(
                all_normalized,
                dedup_image_texts,
                existing_glossary
            )
            save_candidates(candidates, str(output_path / "document_candidates.json"))
            result.stage_completed = "candidate_extraction"

            # Step 1-5: GPT Glossary Classification
            plog("[Pipeline] Step 1-5: GPT Glossary Classification")
            gpt_results = classify_candidates_with_gpt(candidates, llm_client)
            generated_glossary = build_glossary_from_gpt_results(gpt_results)

            # 기존 glossary와 병합
            final_glossary = merge_with_existing_glossary(generated_glossary, existing_glossary)

            # 문서 전체 텍스트 추출 (도메인 감지 및 critical term용)
            document_text = " ".join(
                r.get("ocr_text", "") for page in all_normalized for r in page
            )

            # 도메인 자동 감지 및 glossary 병합 (하드코딩 아님)
            from .domain_glossary import auto_detect_and_load_glossary, merge_with_document_glossary
            domain_glossary, detected_domains = auto_detect_and_load_glossary(document_text, top_k=2)
            final_glossary = merge_with_document_glossary(domain_glossary, final_glossary)
            plog(f"[Pipeline] Step 1-5b: Domain glossary merged (detected: {detected_domains})")

            glossary_path = str(output_path / "glossary.generated.json")
            save_glossary(final_glossary, glossary_path)
            result.glossary_path = glossary_path

            # 검토 필요 항목 CSV
            review_items = extract_review_items(final_glossary)
            if review_items:
                save_review_csv(review_items, str(output_path / "glossary.review.csv"))

            result.stage_completed = "glossary_classification"

            # Step 1-5c: Low Confidence OCR Detection (저신뢰 OCR 감지)
            plog("[Pipeline] Step 1-5c: Low Confidence OCR Detection")
            all_regions_flat = _flatten_pages(all_normalized)
            low_confidence_result = detect_low_confidence_ocr(
                all_regions_flat,
                final_glossary,
                confidence_threshold=0.5
            )
            low_confidence_count = low_confidence_result.get("summary", {}).get("total_count", 0)

            if low_confidence_count > 0:
                low_confidence_path = str(output_path / "ocr_low_confidence_review.json")
                save_low_confidence_review(low_confidence_result, low_confidence_path)
                plog(f"  저신뢰 OCR 항목: {low_confidence_count}개 (review 필요)")

                # 로그에 상위 5개 출력
                for item in low_confidence_result.get("low_confidence_items", [])[:5]:
                    plog(f"    Page {item['page_no']}: '{item['ocr_text']}' [{item['confidence']:.2f}]")
                if low_confidence_count > 5:
                    plog(f"    ... 외 {low_confidence_count - 5}개")
            else:
                plog("  저신뢰 OCR 항목 없음")

            # ===== Phase 2: 블록 생성 =====

            # Step 2-1: Region Type Classification
            plog("[Pipeline] Step 2-1: Region Type Classification")
            for page_no, (page_regions, page_size) in enumerate(zip(all_normalized, page_sizes)):
                classify_all_regions(page_regions, page_size, final_glossary)

            save_classified_regions(
                _flatten_pages(all_normalized),
                str(output_path / "regions.classified.json")
            )
            result.stage_completed = "region_classification"

            # Step 2-1b: Page Type Classification
            plog("[Pipeline] Step 2-1b: Page Type Classification")
            page_types = []
            for page_no, (page_regions, page_size) in enumerate(zip(all_normalized, page_sizes)):
                page_type_info = classify_page_type(page_regions, page_size)
                page_types.append(page_type_info)
                plog(f"  Page {page_no + 1}: {page_type_info['page_type']} (confidence: {page_type_info['confidence']})")

            # 페이지 타입 정보 저장
            with open(str(output_path / "page_types.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "pages": [
                        {"page_no": i + 1, **pt}
                        for i, pt in enumerate(page_types)
                    ]
                }, f, ensure_ascii=False, indent=2)

            # Step 2-2: Reading Order Sorting
            plog("[Pipeline] Step 2-2: Reading Order Sorting")
            all_sorted = []
            for page_no, (page_regions, page_size) in enumerate(zip(all_normalized, page_sizes)):
                page_layout = estimate_page_layout(page_regions, page_size)
                sorted_regions = sort_regions_reading_order(page_regions, page_size, page_layout)
                all_sorted.append(sorted_regions)

            save_sorted_regions(
                _flatten_pages(all_sorted),
                str(output_path / "regions.sorted.json")
            )
            result.stage_completed = "reading_order"

            # Step 2-3: Translation Block Building
            plog("[Pipeline] Step 2-3: Translation Block Building")
            all_blocks = []
            for page_no, (page_regions, page_size, page_type_info) in enumerate(zip(all_sorted, page_sizes, page_types)):
                # page_no와 page_type을 전달하여 페이지별 처리
                page_type = page_type_info.get("page_type", "paragraph_or_bullet")
                blocks = build_translation_blocks(
                    page_regions,
                    page_size,
                    page_no=page_no + 1,
                    page_type=page_type
                )
                all_blocks.extend(blocks)

            save_blocks(all_blocks, str(output_path / "blocks.json"))
            result.stage_completed = "block_building"

            # Step 2-4: Glossary Token Protection
            plog("[Pipeline] Step 2-4: Glossary Token Protection")
            protected_blocks = protect_blocks(all_blocks, final_glossary)
            save_protected_blocks(protected_blocks, str(output_path / "blocks.protected.json"))
            result.stage_completed = "token_protection"

            result.total_blocks = len(all_blocks)

            # ===== Phase 3: 번역 및 검증 =====

            if skip_translation:
                plog("[Pipeline] Translation skipped")
                result.success = True
                result.blocks_ok = 0
                result.blocks_failed = len(all_blocks)
                return result

            # Step 3-1: Block Translation
            plog("[Pipeline] Step 3-1: Block Translation")
            translation_result = translate_blocks_batch(
                protected_blocks,
                final_glossary,
                llm_client
            )

            apply_translations_to_blocks(
                protected_blocks,
                translation_result["translations_by_id"],
                translation_result["raw_output"]
            )
            save_translated_blocks(protected_blocks, str(output_path / "blocks.translated.json"))
            result.stage_completed = "translation"

            # Step 3-2: Validation
            plog("[Pipeline] Step 3-2: Validation")
            validation_result = validate_batch_output(
                translation_result["raw_output"],
                protected_blocks,
                final_glossary
            )

            # Step 3-2b: Semantic Mismatch Retry (if any)
            mismatch_blocks = extract_semantic_mismatch_blocks(
                protected_blocks,
                validation_result["results"]
            )
            if mismatch_blocks and llm_client:
                plog(f"[Pipeline] Step 3-2b: Semantic Mismatch Retry ({len(mismatch_blocks)}개)")
                retried_translations, merged_info = retry_semantic_mismatch_blocks(
                    mismatch_blocks,
                    protected_blocks,
                    final_glossary,
                    llm_client
                )

                # 재번역 결과 적용
                if retried_translations:
                    for prompt_id, translation in retried_translations.items():
                        translation_result["translations_by_id"][prompt_id] = translation

                    # 재번역된 블록에 결과 적용
                    apply_translations_to_blocks(
                        protected_blocks,
                        retried_translations,
                        ""  # raw_output은 이미 적용됨
                    )

                    # merged 블록 플래그 적용 (원본 블록에)
                    if merged_info:
                        blocks_by_id = {b.get("prompt_id"): b for b in protected_blocks if b.get("prompt_id")}
                        for prompt_id, flags in merged_info.items():
                            if prompt_id in blocks_by_id:
                                block = blocks_by_id[prompt_id]
                                # fragment에 병합 플래그 적용
                                if "_merged_into" in flags:
                                    block["_merged_into"] = flags.get("_merged_into")
                                    block["_skip_render"] = flags.get("_skip_render", True)
                                # predecessor에 확장된 bbox 적용
                                if "_expanded_bbox" in flags:
                                    block["union_bbox"] = flags["_expanded_bbox"]
                                    plog(f"[Pipeline] {prompt_id}: bbox 확장 적용됨")

                    # 재검증
                    plog("[Pipeline] Step 3-2c: Re-validation after retry")
                    validation_result = validate_batch_output(
                        translation_result["raw_output"],
                        protected_blocks,
                        final_glossary
                    )

            # Step 3-2d: Residual Korean Retry (if any)
            residual_korean_blocks = extract_residual_korean_blocks(
                protected_blocks,
                validation_result["results"]
            )
            if residual_korean_blocks and llm_client:
                plog(f"[Pipeline] Step 3-2d: Residual Korean Retry ({len(residual_korean_blocks)}개)")
                korean_retried = retry_residual_korean_blocks(
                    residual_korean_blocks,
                    final_glossary,
                    llm_client
                )

                # 재번역 결과 적용
                if korean_retried:
                    for prompt_id, translation in korean_retried.items():
                        translation_result["translations_by_id"][prompt_id] = translation

                    apply_translations_to_blocks(
                        protected_blocks,
                        korean_retried,
                        ""
                    )

                    # 재검증
                    plog("[Pipeline] Step 3-2e: Re-validation after Korean retry")
                    validation_result = validate_batch_output(
                        translation_result["raw_output"],
                        protected_blocks,
                        final_glossary
                    )

            # Step 3-2f: Token Error Retry (if any)
            token_error_blocks = extract_token_error_blocks(
                protected_blocks,
                validation_result["results"]
            )
            if token_error_blocks and llm_client:
                plog(f"[Pipeline] Step 3-2f: Token Error Retry ({len(token_error_blocks)}개)")
                token_retried = retry_token_error_blocks(
                    token_error_blocks,
                    final_glossary,
                    llm_client
                )

                # 재번역 결과 적용
                if token_retried:
                    for prompt_id, translation in token_retried.items():
                        translation_result["translations_by_id"][prompt_id] = translation

                    apply_translations_to_blocks(
                        protected_blocks,
                        token_retried,
                        ""
                    )

                    # 재검증
                    plog("[Pipeline] Step 3-2g: Re-validation after Token retry")
                    validation_result = validate_batch_output(
                        translation_result["raw_output"],
                        protected_blocks,
                        final_glossary
                    )

            # Step 3-3: Finalize
            plog("[Pipeline] Step 3-3: Finalize")
            final_blocks = finalize_blocks(protected_blocks, validation_result["results"])

            blocks_final_path = str(output_path / "blocks.final.json")
            save_final_blocks(final_blocks, blocks_final_path)
            result.blocks_final_path = blocks_final_path
            result.stage_completed = "finalize"

            # Step 3-4: Quality Report
            plog("[Pipeline] Step 3-4: Quality Report")
            quality_report = generate_quality_report(final_blocks, validation_result["results"])

            quality_report_path = str(output_path / "quality_report.json")
            save_quality_report(quality_report, quality_report_path)
            result.quality_report_path = quality_report_path

            # ===== Phase 2: 이미지 텍스트 처리 =====

            # validation 실패 시 이미지 렌더링 스킵 여부 결정
            validation_ok = validation_result.get("ok", True)
            skip_rendering = not validation_ok and quality_report.get("blocks_failed", 0) > quality_report.get("blocks_ok", 0)

            if skip_rendering:
                plog(f"[Pipeline] WARNING: Validation 실패 (ok: {quality_report.get('blocks_ok')}, failed: {quality_report.get('blocks_failed')}) - 이미지 렌더링 스킵")
                translated_image_texts = []
                processed_images = None
                render_quality_report = None
            # Step 4-1: Image Text Translation
            elif dedup_image_texts:
                plog("[Pipeline] Step 4-1: Image Text Translation")
                translated_image_texts = translate_image_texts(
                    dedup_image_texts,
                    final_glossary,
                    llm_client
                )
                image_texts_path = str(output_path / "image_texts.translated.json")
                save_translated_image_texts(translated_image_texts, image_texts_path)
                result.image_texts_path = image_texts_path
                result.stage_completed = "image_text_translation"

                # Step 4-2: Image Rendering (인페인팅 + 텍스트 렌더링)
                if images:
                    plog("[Pipeline] Step 4-2: Image Rendering")
                    # 페이지별로 그룹화 (이미지 텍스트)
                    texts_by_page = {}
                    for text_item in translated_image_texts:
                        page_no = text_item.get("page_no", 1)
                        if page_no not in texts_by_page:
                            texts_by_page[page_no] = []
                        texts_by_page[page_no].append(text_item)

                    # 메인 블록 번역도 렌더링에 포함
                    for block in final_blocks:
                        page_no = block.get("page_no", 1)
                        english = block.get("english", "")
                        bbox = block.get("union_bbox")
                        status = block.get("status", "ok")

                        # 번역된 블록만 포함 (merged, skipped 제외)
                        if not english or not bbox:
                            continue
                        if status != "ok":
                            continue
                        if block.get("_skip_render") or block.get("_merged_into"):
                            continue

                        if page_no not in texts_by_page:
                            texts_by_page[page_no] = []

                        texts_by_page[page_no].append({
                            "page_no": page_no,
                            "bbox": bbox,
                            "english": english,
                            "source_text": block.get("source_text", ""),  # 한글 여부 판단용
                            "translation_available": True,
                            "source": "block",  # 메인 블록임을 표시
                            "block_id": block.get("block_id"),
                            "prompt_id": block.get("prompt_id"),
                            "region_type": block.get("block_type"),
                        })

                    plog(f"[Pipeline] 렌더링 대상: {sum(len(v) for v in texts_by_page.values())}개 텍스트 (블록 + 이미지텍스트)")

                    processed_images_dir = str(output_path / "processed_images")
                    processed_images, render_quality_report, render_debug = process_page_images(
                        images, texts_by_page, output_dir=processed_images_dir
                    )
                    save_processed_images(processed_images, processed_images_dir)
                    result.processed_images_dir = processed_images_dir

                    # Render Quality Report 저장
                    render_report_path = str(output_path / "render_quality_report.json")
                    with open(render_report_path, "w", encoding="utf-8") as f:
                        json.dump(render_quality_report, f, ensure_ascii=False, indent=2)
                    plog(f"[Pipeline] Render Quality Report 저장: {render_report_path}")
                    rq_stats = render_quality_report.get('stats', {})
                    plog(f"[Pipeline] Render Quality: ok={rq_stats.get('rendered_ok', 0)}, "
                         f"overflow={rq_stats.get('overflow', 0)}, block_overlap={rq_stats.get('block_overlap', 0)} "
                         f"(font_too_small={rq_stats.get('font_too_small', 0)} - info only)")

                    result.stage_completed = "image_rendering"
            else:
                # 이미지 텍스트가 없어도 메인 블록 렌더링은 필요
                translated_image_texts = []

                if images and final_blocks:
                    plog("[Pipeline] Step 4-2: Image Rendering (블록만)")
                    texts_by_page = {}

                    for block in final_blocks:
                        page_no = block.get("page_no", 1)
                        english = block.get("english", "")
                        bbox = block.get("union_bbox")
                        status = block.get("status", "ok")

                        if not english or not bbox:
                            continue
                        if status != "ok":
                            continue
                        if block.get("_skip_render") or block.get("_merged_into"):
                            continue

                        if page_no not in texts_by_page:
                            texts_by_page[page_no] = []

                        texts_by_page[page_no].append({
                            "page_no": page_no,
                            "bbox": bbox,
                            "english": english,
                            "source_text": block.get("source_text", ""),  # 한글 여부 판단용
                            "translation_available": True,
                            "source": "block",
                            "block_id": block.get("block_id"),
                            "region_type": block.get("block_type"),
                        })

                    plog(f"[Pipeline] 렌더링 대상: {sum(len(v) for v in texts_by_page.values())}개 블록")
                    processed_images_dir = str(output_path / "processed_images")
                    processed_images, render_quality_report, render_debug = process_page_images(
                        images, texts_by_page, output_dir=processed_images_dir
                    )
                    save_processed_images(processed_images, processed_images_dir)
                    result.processed_images_dir = processed_images_dir

                    # Render Quality Report 저장
                    render_report_path = str(output_path / "render_quality_report.json")
                    with open(render_report_path, "w", encoding="utf-8") as f:
                        json.dump(render_quality_report, f, ensure_ascii=False, indent=2)
                    plog(f"[Pipeline] Render Quality Report 저장: {render_report_path}")
                    rq_stats = render_quality_report.get('stats', {})
                    plog(f"[Pipeline] Render Quality: ok={rq_stats.get('rendered_ok', 0)}, "
                         f"overflow={rq_stats.get('overflow', 0)}, block_overlap={rq_stats.get('block_overlap', 0)} "
                         f"(font_too_small={rq_stats.get('font_too_small', 0)} - info only)")

                    result.stage_completed = "image_rendering"

                    # Step 4-2b: Update Low Confidence OCR Review with rendered_text
                    low_confidence_path = str(output_path / "ocr_low_confidence_review.json")
                    if os.path.exists(low_confidence_path) and final_blocks:
                        try:
                            with open(low_confidence_path, "r", encoding="utf-8") as f:
                                low_conf_data = json.load(f)

                            # 블록을 page_no와 bbox로 인덱싱
                            blocks_by_page = {}
                            for block in final_blocks:
                                page_no = block.get("page_no", 1)
                                if page_no not in blocks_by_page:
                                    blocks_by_page[page_no] = []
                                blocks_by_page[page_no].append(block)

                            def bbox_overlap(bbox1, bbox2, threshold=0.3):
                                """두 bbox가 겹치는지 확인"""
                                if not bbox1 or not bbox2 or len(bbox1) < 4 or len(bbox2) < 4:
                                    return False
                                x1 = max(bbox1[0], bbox2[0])
                                y1 = max(bbox1[1], bbox2[1])
                                x2 = min(bbox1[2], bbox2[2])
                                y2 = min(bbox1[3], bbox2[3])
                                if x1 >= x2 or y1 >= y2:
                                    return False
                                intersection = (x2 - x1) * (y2 - y1)
                                area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
                                return intersection / area1 > threshold if area1 > 0 else False

                            # 각 low_confidence item에 rendered_text 추가
                            for item in low_conf_data.get("low_confidence_items", []):
                                page_no = item.get("page_no", 1)
                                item_bbox = item.get("bbox", [])
                                ocr_text = item.get("ocr_text", "")
                                confidence = item.get("confidence", 1.0)

                                # 같은 페이지에서 겹치는 블록 찾기
                                rendered_text = ""
                                for block in blocks_by_page.get(page_no, []):
                                    block_bbox = block.get("union_bbox", block.get("bbox", []))
                                    if bbox_overlap(item_bbox, block_bbox):
                                        rendered_text = block.get("english", "")
                                        break

                                item["rendered_text"] = rendered_text

                                # severity 판단 개선:
                                # 1. 매우 낮은 confidence (< 0.4) + rendered_text가 OCR 텍스트와 의미적으로 무관 → error
                                # 2. suggested_candidates 중 유효한 English 번역이 있는 경우만 매칭 확인
                                suggested = item.get("suggested_candidates", [])

                                # 유효한 English 후보가 있는지 확인 (빈 문자열 제외)
                                valid_english_candidates = [
                                    s.get("english", "").strip()
                                    for s in suggested
                                    if s.get("english", "").strip()
                                ]

                                if rendered_text and valid_english_candidates:
                                    # rendered_text가 유효한 suggested 중 하나와 일치하는지 확인
                                    rendered_lower = rendered_text.lower().strip()
                                    match_found = any(
                                        eng.lower() in rendered_lower or rendered_lower in eng.lower()
                                        for eng in valid_english_candidates
                                    )
                                    item["severity"] = "warning" if match_found else "error"
                                    item["action"] = "review_needed"
                                elif rendered_text:
                                    # 유효 후보 없음 - confidence에 따라 판단
                                    if confidence < 0.4:
                                        # 매우 낮은 confidence는 OCR 오류 가능성 높음 → error
                                        item["severity"] = "error"
                                        item["action"] = "review_needed"
                                        item["note"] = f"Very low OCR confidence ({confidence:.2f}), translation may be incorrect"
                                    else:
                                        item["severity"] = "warning"
                                        item["action"] = "review_needed"
                                else:
                                    item["severity"] = "error"
                                    item["action"] = "manual_check"

                            # error severity 항목 수 계산
                            low_confidence_errors = sum(
                                1 for item in low_conf_data.get("low_confidence_items", [])
                                if item.get("severity") == "error"
                            )
                            low_conf_data["summary"]["error_count"] = low_confidence_errors

                            # 업데이트된 파일 저장
                            with open(low_confidence_path, "w", encoding="utf-8") as f:
                                json.dump(low_conf_data, f, ensure_ascii=False, indent=2)

                            if low_confidence_errors > 0:
                                plog(f"[Pipeline] Low confidence OCR: {low_confidence_errors} error(s) found (review required)")

                        except Exception as lc_err:
                            plog(f"[Pipeline] Low confidence review update failed: {lc_err}")

                else:
                    processed_images = None
                    render_quality_report = None

            # ===== Step 4-3: Final Image Korean Detection =====
            final_korean_detection = None
            has_critical_korean = False
            korean_detection_audit_failed = False  # OCR audit 실패 여부 추적
            korean_detection_error_msg = None

            if processed_images:
                plog("[Pipeline] Step 4-3: Final Image Korean Detection")
                try:
                    import numpy as np
                    from PIL import Image

                    # processed_images를 로드 (파일 경로 또는 이미지 객체)
                    images_for_detection = []
                    processed_images_dir = str(output_path / "processed_images")
                    image_load_errors = []

                    plog(f"[Pipeline] 이미지 로드 시작: {processed_images_dir}")
                    plog(f"[Pipeline] 예상 페이지 수: {len(images)}")

                    if os.path.exists(processed_images_dir):
                        for page_no in range(1, len(images) + 1):
                            # 파일명: page_001.png 형식 (3자리 패딩)
                            img_path = os.path.join(processed_images_dir, f"page_{page_no:03d}.png")
                            file_exists = os.path.exists(img_path)
                            plog(f"  Page {page_no}: {img_path} (exists={file_exists})")

                            if file_exists:
                                try:
                                    img = Image.open(img_path)
                                    img.load()  # 실제 이미지 데이터 로드 강제
                                    plog(f"    -> 로드 성공: {img.size}, mode={img.mode}")
                                    images_for_detection.append(img)
                                except Exception as load_err:
                                    plog(f"    -> 로드 실패: {load_err}")
                                    image_load_errors.append({
                                        "page_no": page_no,
                                        "path": img_path,
                                        "exists": True,
                                        "error": str(load_err)
                                    })
                                    images_for_detection.append(None)
                            else:
                                plog(f"    -> 파일 없음")
                                image_load_errors.append({
                                    "page_no": page_no,
                                    "path": img_path,
                                    "exists": False,
                                    "error": "File not found"
                                })
                                images_for_detection.append(None)
                    else:
                        plog(f"[Pipeline] ERROR: processed_images_dir가 존재하지 않음: {processed_images_dir}")
                        korean_detection_audit_failed = True
                        korean_detection_error_msg = f"processed_images_dir not found: {processed_images_dir}"

                    # 이미지 로드 실패가 있으면 경고
                    if image_load_errors:
                        plog(f"[Pipeline] WARNING: {len(image_load_errors)}개 페이지 이미지 로드 실패")
                        for err in image_load_errors:
                            plog(f"  Page {err['page_no']}: exists={err['exists']}, error={err['error']}")

                    # 로드된 이미지가 하나도 없으면 audit 실패
                    valid_images = [img for img in images_for_detection if img is not None]
                    if not valid_images:
                        plog("[Pipeline] ERROR: 로드된 이미지가 없음 - Korean Detection audit 실패")
                        korean_detection_audit_failed = True
                        korean_detection_error_msg = "No valid images loaded for Korean detection"
                    elif len(valid_images) < len(images):
                        plog(f"[Pipeline] WARNING: {len(images) - len(valid_images)}개 페이지 이미지 누락")

                    if valid_images and not korean_detection_audit_failed:
                        # original_regions 준비
                        original_regions = _flatten_pages(all_normalized)

                        # 최종 이미지에서 한글 감지
                        final_korean_detection = detect_korean_in_final_images(
                            rendered_images=images_for_detection,
                            original_regions=original_regions,
                            final_blocks=final_blocks,
                            glossary=final_glossary,
                            document_text=document_text,
                            ocr_service=None
                        )

                        # detect 함수 내부 오류 체크
                        if final_korean_detection is None:
                            plog("[Pipeline] ERROR: detect_korean_in_final_images returned None")
                            korean_detection_audit_failed = True
                            korean_detection_error_msg = "detect_korean_in_final_images returned None"
                        else:
                            # remaining_korean_regions.json 저장
                            remaining_korean_path = str(output_path / "remaining_korean_regions.json")
                            save_remaining_korean_regions(final_korean_detection, remaining_korean_path)

                            summary = final_korean_detection.get("summary", {})
                            has_critical_korean = final_korean_detection.get("has_critical", False)

                            # OCR 오류 발생 페이지 체크
                            ocr_error_pages = final_korean_detection.get("ocr_error_pages", [])
                            if ocr_error_pages:
                                plog(f"[Pipeline] WARNING: OCR 오류 발생 페이지: {ocr_error_pages}")
                                korean_detection_audit_failed = True
                                korean_detection_error_msg = f"OCR errors on pages: {ocr_error_pages}"

                            plog(f"[Pipeline] Final Korean Detection: {summary.get('total_remaining', 0)} regions found, "
                                 f"{summary.get('critical_remaining', 0)} critical")

                            if summary.get("by_cause"):
                                for cause, count in summary["by_cause"].items():
                                    plog(f"  {cause}: {count}")

                            # Step 4-4: Enhanced OCR Reprocessing for A_ocr_missing
                            a_ocr_missing = [
                                r for r in final_korean_detection.get("remaining_korean_regions", [])
                                if r.get("cause", {}).get("type") == "A_ocr_missing"
                            ]

                            # 재처리 결과 추적
                            reprocess_results = {
                                "total": len(a_ocr_missing),
                                "ocr_success": 0,
                                "translate_success": 0,
                                "render_success": 0,
                                "unresolved": [],
                                "resolved": [],
                            }

                            # Classification decisions 추적 (fallback_decisions.json 저장용)
                            fallback_decisions = []

                            if a_ocr_missing:
                                plog(f"[Pipeline] Step 4-4: Enhanced OCR Reprocessing ({len(a_ocr_missing)} OCR-missing regions)")

                                # 페이지별 fallback blocks 수집
                                fallback_blocks_by_page = {}

                                for remnant in a_ocr_missing:
                                    page_no = remnant.get("page_no", 1)
                                    bbox = remnant.get("bbox", [])
                                    detected_text = remnant.get("detected_text", "")

                                    if not bbox or len(bbox) != 4:
                                        reprocess_results["unresolved"].append({
                                            "page_no": page_no,
                                            "bbox": bbox,
                                            "reason": "invalid_bbox",
                                            "detected_text": detected_text,
                                        })
                                        continue

                                    # 페이지 이미지에서 crop
                                    if page_no - 1 < len(images_for_detection) and images_for_detection[page_no - 1]:
                                        try:
                                            page_img = images_for_detection[page_no - 1]
                                            img_np = np.array(page_img)

                                            # bbox로 crop (약간 확장)
                                            x1, y1, x2, y2 = [int(v) for v in bbox]
                                            pad = 15
                                            h, w = img_np.shape[:2]
                                            crop_x1 = max(0, x1 - pad)
                                            crop_y1 = max(0, y1 - pad)
                                            crop_x2 = min(w, x2 + pad)
                                            crop_y2 = min(h, y2 + pad)

                                            crop = img_np[crop_y1:crop_y2, crop_x1:crop_x2]

                                            if crop.size > 0:
                                                # Enhanced OCR 재시도
                                                enhanced_results = extract_text_with_enhanced_ocr(
                                                    crop,
                                                    ocr_service=None,
                                                    enable_retry=True
                                                )

                                                # 한글 텍스트 추출
                                                korean_texts = []
                                                for r in (enhanced_results or []):
                                                    text = r.get("text", "")
                                                    if KOREAN_PATTERN.search(text):
                                                        korean_texts.append(text)

                                                if korean_texts:
                                                    reprocess_results["ocr_success"] += 1
                                                    combined_text = " ".join(korean_texts)
                                                    plog(f"  Page {page_no}: Enhanced OCR detected: '{combined_text}'")

                                                    # Score-based OCR classification (하드코딩 단어 목록 사용 안함)
                                                    # OCR confidence 계산 (enhanced_results에서 평균)
                                                    ocr_confidences = [
                                                        r.get("confidence", 0.5) for r in enhanced_results
                                                        if r.get("text") and KOREAN_PATTERN.search(r.get("text", ""))
                                                    ]
                                                    avg_confidence = sum(ocr_confidences) / len(ocr_confidences) if ocr_confidences else 0.5

                                                    # Page type 가져오기
                                                    current_page_type = "paragraph_or_bullet"
                                                    if page_types and page_no - 1 < len(page_types):
                                                        current_page_type = page_types[page_no - 1].get("page_type", "paragraph_or_bullet")

                                                    # OCR variants 구성
                                                    ocr_variants = [
                                                        {"text": r.get("text", ""), "confidence": r.get("confidence", 0.5)}
                                                        for r in enhanced_results if r.get("text")
                                                    ]

                                                    # 주변 문맥 (nearby blocks on same page)
                                                    nearby_context = [
                                                        b for b in final_blocks
                                                        if b.get("page_no") == page_no and b.get("source_text")
                                                    ]

                                                    # Score-based classification
                                                    classification = classify_fallback_ocr_text(
                                                        text=combined_text,
                                                        confidence=avg_confidence,
                                                        bbox=[x1, y1, x2, y2],
                                                        page_type=current_page_type,
                                                        ocr_variants=ocr_variants,
                                                        glossary=final_glossary,
                                                        nearby_context=nearby_context,
                                                        page_size=page_sizes[page_no - 1] if page_sizes and page_no - 1 < len(page_sizes) else None,
                                                    )

                                                    decision = classification.get("decision", "review_needed")
                                                    reason = classification.get("reason", "")
                                                    score = classification.get("confidence_score", 0.0)

                                                    # Classification 결과 추적
                                                    fallback_decisions.append({
                                                        "page_no": page_no,
                                                        "bbox": [x1, y1, x2, y2],
                                                        "detected_text": combined_text,
                                                        "decision": decision,
                                                        "reason": reason,
                                                        "confidence_score": score,
                                                        "score_breakdown": classification.get("score_breakdown", {}),
                                                        "has_strong_signal": classification.get("has_strong_signal", False),
                                                        "glossary_match": classification.get("glossary_match", {}),
                                                        "stable_ocr": classification.get("stable_ocr", False),
                                                        "ocr_confidence": avg_confidence,
                                                    })

                                                    if decision == "unresolved":
                                                        plog(f"    -> unresolved (score={score:.2f}): {reason}")
                                                        reprocess_results["unresolved"].append({
                                                            "page_no": page_no,
                                                            "bbox": [x1, y1, x2, y2],
                                                            "reason": "classification_unresolved",
                                                            "detected_text": combined_text,
                                                            "note": reason,
                                                            "classification_score": score,
                                                            "score_breakdown": classification.get("score_breakdown", {}),
                                                        })
                                                        continue
                                                    elif decision == "review_needed":
                                                        plog(f"    -> review_needed (score={score:.2f}): {reason}")
                                                        reprocess_results["unresolved"].append({
                                                            "page_no": page_no,
                                                            "bbox": [x1, y1, x2, y2],
                                                            "reason": "classification_review_needed",
                                                            "detected_text": combined_text,
                                                            "note": reason,
                                                            "classification_score": score,
                                                            "score_breakdown": classification.get("score_breakdown", {}),
                                                        })
                                                        continue

                                                    # decision == "translate" - Fallback block 생성
                                                    plog(f"    -> translate allowed (score={score:.2f})")
                                                    fallback_block = {
                                                        "page_no": page_no,
                                                        "bbox": [x1, y1, x2, y2],
                                                        "union_bbox": [x1, y1, x2, y2],
                                                        "source_text": combined_text,
                                                        "prompt_id": f"fallback_p{page_no}_{x1}_{y1}",
                                                        "block_type": "fallback_ocr",
                                                        "_fallback": True,
                                                        "_original_remnant": remnant,
                                                    }

                                                    if page_no not in fallback_blocks_by_page:
                                                        fallback_blocks_by_page[page_no] = []
                                                    fallback_blocks_by_page[page_no].append(fallback_block)

                                                else:
                                                    # Enhanced OCR도 감지 실패
                                                    reprocess_results["unresolved"].append({
                                                        "page_no": page_no,
                                                        "bbox": [x1, y1, x2, y2],
                                                        "reason": "enhanced_ocr_no_korean",
                                                        "detected_text": detected_text,
                                                    })

                                        except Exception as e:
                                            plog(f"  Page {page_no}: Enhanced OCR failed - {e}")
                                            reprocess_results["unresolved"].append({
                                                "page_no": page_no,
                                                "bbox": bbox,
                                                "reason": f"exception: {str(e)}",
                                                "detected_text": detected_text,
                                            })
                                    else:
                                        reprocess_results["unresolved"].append({
                                            "page_no": page_no,
                                            "bbox": bbox,
                                            "reason": "image_not_available",
                                            "detected_text": detected_text,
                                        })

                                # Fallback blocks 번역 및 재렌더링
                                if fallback_blocks_by_page:
                                    plog(f"[Pipeline] Step 4-4b: Translating {sum(len(v) for v in fallback_blocks_by_page.values())} fallback blocks")

                                    try:
                                        # 모든 함수는 상단에서 import됨

                                        # Flatten fallback blocks
                                        all_fallback_blocks = []
                                        for blocks in fallback_blocks_by_page.values():
                                            all_fallback_blocks.extend(blocks)

                                        # Token protection
                                        protected_fallback = protect_blocks(all_fallback_blocks, final_glossary)

                                        # 번역
                                        fallback_translation = translate_blocks_batch(
                                            protected_fallback,
                                            final_glossary,
                                            llm_client
                                        )

                                        apply_translations_to_blocks(
                                            protected_fallback,
                                            fallback_translation["translations_by_id"],
                                            fallback_translation["raw_output"]
                                        )

                                        # 번역 검증 및 english 필드 설정
                                        fallback_validation = validate_batch_output(
                                            fallback_translation["raw_output"],
                                            protected_fallback,
                                            final_glossary
                                        )

                                        # finalize: english 필드 설정
                                        finalize_blocks(
                                            protected_fallback,
                                            fallback_validation["results"]
                                        )

                                        plog(f"[Pipeline] Step 4-4b: Validation done, {len([b for b in protected_fallback if b.get('english')])} blocks have english")

                                        # 번역 성공 체크 및 재렌더링
                                        for block in protected_fallback:
                                            page_no = block.get("page_no", 1)
                                            english = block.get("english", "")
                                            bbox = block.get("union_bbox", block.get("bbox", []))

                                            if english and not KOREAN_PATTERN.search(english):
                                                reprocess_results["translate_success"] += 1
                                                plog(f"  Page {page_no}: Translated to '{english[:50]}...' " if len(english) > 50 else f"  Page {page_no}: Translated to '{english}'")

                                                # 이미지 재렌더링
                                                if page_no - 1 < len(images_for_detection) and images_for_detection[page_no - 1]:
                                                    try:
                                                        page_img = images_for_detection[page_no - 1]

                                                        # PIL Image로 변환
                                                        if not isinstance(page_img, Image.Image):
                                                            page_img = Image.fromarray(page_img)

                                                        img_np = np.array(page_img)
                                                        x1, y1, x2, y2 = [int(v) for v in bbox]

                                                        # 배경색 추출 및 마스킹
                                                        bg_color = _get_edge_dominant_color(img_np, [x1, y1, x2, y2])
                                                        masked_img = _inpaint_solid_color(
                                                            page_img.copy(),
                                                            [x1, y1, x2, y2],
                                                            bg_color,
                                                            render_role="fallback"
                                                        )

                                                        # 텍스트 렌더링
                                                        text_item = {
                                                            "source_text": block.get("source_text", ""),
                                                            "_region_type": "fallback",
                                                            "block_type": "fallback_ocr",
                                                        }
                                                        rendered_img, _, _ = render_english_text(
                                                            masked_img,
                                                            [x1, y1, x2, y2],
                                                            english,
                                                            text_item
                                                        )

                                                        # 이미지 업데이트
                                                        images_for_detection[page_no - 1] = rendered_img

                                                        # 파일 저장
                                                        img_save_path = os.path.join(processed_images_dir, f"page_{page_no:03d}.png")
                                                        rendered_img.save(img_save_path)

                                                        reprocess_results["render_success"] += 1
                                                        reprocess_results["resolved"].append({
                                                            "page_no": page_no,
                                                            "bbox": [x1, y1, x2, y2],
                                                            "source_text": block.get("source_text", ""),
                                                            "english": english,
                                                        })

                                                        plog(f"  Page {page_no}: Re-rendered and saved")

                                                    except Exception as render_err:
                                                        plog(f"  Page {page_no}: Render failed - {render_err}")
                                                        import traceback
                                                        traceback.print_exc()
                                                        reprocess_results["unresolved"].append({
                                                            "page_no": page_no,
                                                            "bbox": bbox,
                                                            "reason": f"render_failed: {str(render_err)}",
                                                            "source_text": block.get("source_text", ""),
                                                            "english": english,
                                                        })
                                            else:
                                                # 번역 실패 또는 한글 잔존
                                                reprocess_results["unresolved"].append({
                                                    "page_no": page_no,
                                                    "bbox": bbox,
                                                    "reason": "translation_failed_or_korean_remains",
                                                    "source_text": block.get("source_text", ""),
                                                    "english": english,
                                                })

                                    except ImportError as ie:
                                        plog(f"[Pipeline] Step 4-4b: Import error - {ie}")
                                        import traceback
                                        traceback.print_exc()
                                    except Exception as te:
                                        plog(f"[Pipeline] Step 4-4b: Translation/Render error - {te}")
                                        import traceback
                                        traceback.print_exc()

                                # 결과 로그
                                plog(f"[Pipeline] Step 4-4 Complete: OCR={reprocess_results['ocr_success']}, "
                                     f"Translate={reprocess_results['translate_success']}, "
                                     f"Render={reprocess_results['render_success']}, "
                                     f"Unresolved={len(reprocess_results['unresolved'])}")

                            # Step 4-5: E_mask_residue 재마스킹/재렌더링
                            e_mask_residue = [
                                r for r in final_korean_detection.get("remaining_korean_regions", [])
                                if r.get("cause", {}).get("type") == "E_mask_residue"
                            ]

                            # 재마스킹 결과 추적 (기본값)
                            remask_results = {"success": 0, "failed": 0}

                            # 블록별로 그룹화 (같은 블록의 여러 잔존 영역 통합)
                            residue_by_block = {}
                            for remnant in e_mask_residue:
                                block_id = remnant.get("block_id")
                                if block_id:
                                    if block_id not in residue_by_block:
                                        residue_by_block[block_id] = {
                                            "block_id": block_id,
                                            "page_no": remnant.get("page_no", 1),
                                            "bboxes": [],
                                            "detected_texts": [],
                                        }
                                    residue_by_block[block_id]["bboxes"].append(remnant.get("bbox", []))
                                    residue_by_block[block_id]["detected_texts"].append(remnant.get("detected_text", ""))

                            if residue_by_block:
                                plog(f"[Pipeline] Step 4-5: E_mask_residue Re-masking ({len(residue_by_block)} blocks)")

                                # final_blocks를 prompt_id로 인덱싱
                                blocks_by_id = {b.get("prompt_id"): b for b in final_blocks if b.get("prompt_id")}

                                for block_id, residue_info in residue_by_block.items():
                                    page_no = residue_info["page_no"]
                                    bboxes = residue_info["bboxes"]

                                    # 해당 블록 찾기
                                    block = blocks_by_id.get(block_id)
                                    if not block:
                                        plog(f"  {block_id}: Block not found, skipping")
                                        remask_results["failed"] += 1
                                        continue

                                    english = block.get("english", "")
                                    if not english:
                                        plog(f"  {block_id}: No english text, skipping")
                                        remask_results["failed"] += 1
                                        continue

                                    # 원본 bbox와 잔존 영역 bbox 통합 (확장된 bbox 생성)
                                    original_bbox = block.get("union_bbox", block.get("bbox", []))
                                    if not original_bbox or len(original_bbox) != 4:
                                        remask_results["failed"] += 1
                                        continue

                                    # 모든 bbox를 통합하여 확장된 영역 계산
                                    all_bboxes = [original_bbox] + [b for b in bboxes if b and len(b) == 4]
                                    x1 = min(b[0] for b in all_bboxes)
                                    y1 = min(b[1] for b in all_bboxes)
                                    x2 = max(b[2] for b in all_bboxes)
                                    y2 = max(b[3] for b in all_bboxes)
                                    expanded_bbox = [int(x1), int(y1), int(x2), int(y2)]

                                    # 이미지 재마스킹/재렌더링
                                    if page_no - 1 < len(images_for_detection) and images_for_detection[page_no - 1]:
                                        try:
                                            page_img = images_for_detection[page_no - 1]
                                            if not isinstance(page_img, Image.Image):
                                                page_img = Image.fromarray(page_img)

                                            img_np = np.array(page_img)

                                            # 확장된 bbox로 재마스킹
                                            bg_color = _get_edge_dominant_color(img_np, expanded_bbox)
                                            masked_img = _inpaint_solid_color(
                                                page_img.copy(),
                                                expanded_bbox,
                                                bg_color,
                                                render_role="remask"
                                            )

                                            # 영어 텍스트 재렌더링
                                            text_item = {
                                                "source_text": block.get("source_text", ""),
                                                "_region_type": block.get("_region_type", "body"),
                                                "block_type": block.get("block_type", "paragraph"),
                                            }
                                            rendered_img, _, _ = render_english_text(
                                                masked_img,
                                                expanded_bbox,
                                                english,
                                                text_item
                                            )

                                            # 이미지 업데이트 및 저장
                                            images_for_detection[page_no - 1] = rendered_img
                                            img_save_path = os.path.join(processed_images_dir, f"page_{page_no:03d}.png")
                                            rendered_img.save(img_save_path)

                                            remask_results["success"] += 1
                                            plog(f"  {block_id}: Re-masked and re-rendered (expanded bbox)")

                                        except Exception as remask_err:
                                            plog(f"  {block_id}: Re-mask failed - {remask_err}")
                                            remask_results["failed"] += 1

                                plog(f"[Pipeline] Step 4-5 Complete: Success={remask_results['success']}, Failed={remask_results['failed']}")

                            # unresolved_ocr_missing.json 저장
                            if reprocess_results["unresolved"]:
                                unresolved_path = str(output_path / "unresolved_ocr_missing.json")
                                with open(unresolved_path, "w", encoding="utf-8") as f:
                                    json.dump({
                                        "unresolved_regions": reprocess_results["unresolved"],
                                        "resolved_regions": reprocess_results["resolved"],
                                        "summary": {
                                            "total": reprocess_results["total"],
                                            "ocr_success": reprocess_results["ocr_success"],
                                            "translate_success": reprocess_results["translate_success"],
                                            "render_success": reprocess_results["render_success"],
                                            "unresolved_count": len(reprocess_results["unresolved"]),
                                        }
                                    }, f, ensure_ascii=False, indent=2)
                                plog(f"[Pipeline] Saved unresolved_ocr_missing.json ({len(reprocess_results['unresolved'])} unresolved)")

                            # fallback_decisions.json 저장 (모든 classification 결과 추적)
                            if fallback_decisions:
                                decisions_path = str(output_path / "fallback_decisions.json")
                                decisions_summary = {
                                    "translate": sum(1 for d in fallback_decisions if d["decision"] == "translate"),
                                    "review_needed": sum(1 for d in fallback_decisions if d["decision"] == "review_needed"),
                                    "unresolved": sum(1 for d in fallback_decisions if d["decision"] == "unresolved"),
                                }
                                with open(decisions_path, "w", encoding="utf-8") as f:
                                    json.dump({
                                        "decisions": fallback_decisions,
                                        "summary": decisions_summary,
                                    }, f, ensure_ascii=False, indent=2)
                                plog(f"[Pipeline] Saved fallback_decisions.json (translate={decisions_summary['translate']}, "
                                     f"review_needed={decisions_summary['review_needed']}, unresolved={decisions_summary['unresolved']})")

                            # Step 4-6: Final Korean Detection 재실행 (Step 4-4/4-5 결과 반영)
                            if reprocess_results.get("render_success", 0) > 0 or remask_results.get("success", 0) > 0:
                                plog("[Pipeline] Step 4-6: Re-running Final Korean Detection (post-reprocess)")
                                try:
                                    final_korean_detection_v2 = detect_korean_in_final_images(
                                        rendered_images=images_for_detection,
                                        original_regions=original_regions,
                                        final_blocks=final_blocks,
                                        glossary=final_glossary,
                                        document_text=document_text,
                                        ocr_service=None
                                    )

                                    if final_korean_detection_v2:
                                        # 업데이트된 결과 저장
                                        remaining_korean_path_v2 = str(output_path / "remaining_korean_regions_final.json")
                                        save_remaining_korean_regions(final_korean_detection_v2, remaining_korean_path_v2)

                                        summary_v2 = final_korean_detection_v2.get("summary", {})
                                        has_critical_korean = final_korean_detection_v2.get("has_critical", False)

                                        plog(f"[Pipeline] Step 4-6 Complete: {summary_v2.get('total_remaining', 0)} regions, "
                                             f"{summary_v2.get('critical_remaining', 0)} critical (after reprocess)")

                                        # 최종 결과 업데이트
                                        final_korean_detection = final_korean_detection_v2

                                except Exception as redetect_err:
                                    plog(f"[Pipeline] Step 4-6 Re-detection failed: {redetect_err}")

                            result.stage_completed = "final_korean_detection"

                except Exception as e:
                    plog(f"[Pipeline] Final Korean Detection CRITICAL ERROR: {e}")
                    import traceback
                    traceback.print_exc()
                    korean_detection_audit_failed = True
                    korean_detection_error_msg = f"Exception: {str(e)}"
            else:
                # processed_images가 None이면 audit 실패
                plog("[Pipeline] WARNING: processed_images is None - Korean Detection audit 스킵")
                korean_detection_audit_failed = True
                korean_detection_error_msg = "processed_images is None"

            # Audit 실패 상태 로그
            if korean_detection_audit_failed:
                plog(f"[Pipeline] Korean Detection Audit FAILED: {korean_detection_error_msg}")

            # ===== Phase 3: 최종 검사 =====

            # Step 5: Final Korean Residual Audit
            plog("[Pipeline] Step 5: Final Korean Residual Audit")
            audit_report = run_residual_audit(
                final_blocks,
                translated_image_texts,
                final_glossary,
                document_text=document_text
            )
            residual_audit_path = str(output_path / "residual_audit_report.json")
            save_audit_report(audit_report, residual_audit_path)
            result.residual_audit_path = residual_audit_path
            result.stage_completed = "residual_audit"

            # Step 5b: Extract and save failed regions (for debugging/review)
            failed_regions = extract_failed_regions(audit_report, final_blocks)
            if failed_regions:
                failed_regions_path = str(output_path / "residual_audit_failed_regions.json")
                save_failed_regions(failed_regions, failed_regions_path)
                plog(f"[Pipeline] Saved {len(failed_regions)} failed regions to residual_audit_failed_regions.json")

            # Step 5c: Save review log (모든 한글 발견 항목 추적 - 조용히 pass 금지)
            review_log_path = str(output_path / "korean_review_log.json")
            review_log = save_review_log(audit_report, review_log_path)
            review_summary = review_log.get("summary", {})
            if review_summary.get("total", 0) > 0:
                plog(f"[Pipeline] Korean Review Log: {review_summary.get('errors', 0)} errors, "
                     f"{review_summary.get('warnings', 0)} warnings, {review_summary.get('allowed', 0)} allowed (tracked)")

            # 결과 통계
            result.blocks_ok = quality_report.get("blocks_ok", 0)
            result.blocks_failed = quality_report.get("blocks_failed", 0)
            result.failed_by_reason = quality_report.get("failed_by_reason", {})
            result.residual_audit_pass = audit_report.get("summary", {}).get("pass", True)

            # Render quality report 통계 포함
            render_quality_pass = True
            if render_quality_report:
                render_quality_pass = render_quality_report.get("success", True)

            # Final Korean Detection 결과를 metrics에 포함
            final_korean_summary = {}
            if final_korean_detection:
                final_korean_summary = final_korean_detection.get("summary", {})

            # Low confidence review 에러 수 (업데이트된 파일에서 읽기)
            low_confidence_error_count = 0
            low_confidence_path_check = str(output_path / "ocr_low_confidence_review.json")
            if os.path.exists(low_confidence_path_check):
                try:
                    with open(low_confidence_path_check, "r", encoding="utf-8") as f:
                        lc_data = json.load(f)
                    low_confidence_error_count = lc_data.get("summary", {}).get("error_count", 0)
                except Exception:
                    pass

            result.metrics = {
                **quality_report,
                "residual_audit": audit_report.get("summary", {}),
                "render_quality": render_quality_report if render_quality_report else {},
                "final_korean_detection": final_korean_summary,
                "korean_detection_audit_failed": korean_detection_audit_failed,
                "korean_detection_error": korean_detection_error_msg,
                "low_confidence_review_count": low_confidence_count,  # 저신뢰 OCR 검토 필요 항목 수
                "low_confidence_error_count": low_confidence_error_count,  # 저신뢰 OCR 중 error severity 항목 수
            }

            # success/status 판단 (render_quality + critical_korean + audit_failed 포함)
            has_failed_blocks = result.blocks_failed > 0
            residual_failed = not result.residual_audit_pass
            render_quality_failed = not render_quality_pass
            critical_korean_failed = has_critical_korean  # Critical 한글이 남아있으면 실패

            # Korean Detection Audit이 실패하면 success 불가 (OCR 오류 시 0 regions로 처리하면 안됨)
            # audit_failed=True면 한글 잔존 여부를 알 수 없으므로 PASS 판정 불가
            korean_audit_unreliable = korean_detection_audit_failed

            if not has_failed_blocks and not residual_failed and not render_quality_failed and not critical_korean_failed and not korean_audit_unreliable:
                # 완전 성공 (모든 audit이 정상 완료되고 문제 없음)
                result.success = True
                result.partial_success = False
                result.status = "success"
            elif has_failed_blocks or residual_failed or render_quality_failed or critical_korean_failed or korean_audit_unreliable:
                # 부분 성공 또는 실패
                result.success = False
                result.partial_success = True

                # 렌더링 품질 문제만 있으면 review_needed, 그 외엔 partial
                if render_quality_failed and not has_failed_blocks and not residual_failed and not critical_korean_failed and not korean_audit_unreliable:
                    result.status = "review_needed"
                else:
                    result.status = "partial"

                # 에러 메시지 생성
                error_parts = []
                if has_failed_blocks:
                    error_parts.append(f"{result.blocks_failed}개 블록 번역 실패")
                if residual_failed:
                    error_parts.append("Residual Audit FAIL")
                if render_quality_failed:
                    rq_stats = render_quality_report.get("stats", {}) if render_quality_report else {}
                    # overflow와 block_overlap만 실패 조건 (font_too_small은 확대로 해결 가능)
                    error_parts.append(f"Render Quality FAIL (overflow: {rq_stats.get('overflow', 0)}, "
                                      f"block_overlap: {rq_stats.get('block_overlap', 0)})")
                if critical_korean_failed:
                    critical_count = final_korean_summary.get("critical_remaining", 0)
                    error_parts.append(f"Critical Korean Remaining ({critical_count}개)")
                if korean_audit_unreliable:
                    error_parts.append(f"Korean Detection Audit FAILED ({korean_detection_error_msg})")
                result.error = ", ".join(error_parts)

                plog(f"[Pipeline] WARNING: {result.error}")
            else:
                result.success = True
                result.status = "success"

            plog(f"[Pipeline] Complete! Blocks: {result.total_blocks} (ok: {result.blocks_ok}, failed: {result.blocks_failed})")
            plog(f"[Pipeline] Residual Audit: {'PASS' if result.residual_audit_pass else 'FAIL'}")
            plog(f"[Pipeline] Render Quality: {'PASS' if render_quality_pass else 'FAIL'}")
            plog(f"[Pipeline] Korean Detection Audit: {'FAIL - ' + str(korean_detection_error_msg) if korean_audit_unreliable else 'PASS'}")
            plog(f"[Pipeline] Critical Korean: {'FAIL' if critical_korean_failed else ('N/A (audit failed)' if korean_audit_unreliable else 'PASS')} ({final_korean_summary.get('critical_remaining', 0)} remaining)")
            plog(f"[Pipeline] Low Confidence OCR: {low_confidence_error_count} error(s), {low_confidence_count - low_confidence_error_count} warning(s)")
            plog(f"[Pipeline] Status: {result.status}")

            # 프론트엔드 상태 출력
            frontend_status = result.to_frontend_status()
            plog(f"[Pipeline] Frontend Status: {frontend_status['message']}")

        except Exception as e:
            result.error = str(e)
            result.status = "failed"
            result.success = False
            result.partial_success = False
            plog(f"[Pipeline] Error at {result.stage_completed}: {e}")
            import traceback
            traceback.print_exc()

    return result


def run_pipeline_from_json(
    ocr_json_path: str,
    output_dir: str,
    glossary_json_path: Optional[str] = None,
    llm_client: Optional[Any] = None,
    **kwargs
) -> PipelineResult:
    """JSON 파일에서 OCR 데이터 로드하여 파이프라인 실행

    Args:
        ocr_json_path: OCR 결과 JSON 파일 경로
        output_dir: 출력 디렉토리
        glossary_json_path: 기존 glossary JSON 경로 (optional)
        llm_client: LLM 클라이언트
        **kwargs: run_pipeline에 전달할 추가 인자
    """
    # OCR 로드
    with open(ocr_json_path, "r", encoding="utf-8") as f:
        ocr_data = json.load(f)

    # OCR 형식 파싱
    if isinstance(ocr_data, list):
        # 이미 페이지별 리스트
        if ocr_data and isinstance(ocr_data[0], list):
            ocr_regions = ocr_data
        else:
            # 단일 페이지로 간주
            ocr_regions = [ocr_data]
    elif isinstance(ocr_data, dict):
        # {"pages": [...]} 또는 {"regions": [...]}
        if "pages" in ocr_data:
            ocr_regions = ocr_data["pages"]
        elif "regions" in ocr_data:
            ocr_regions = [ocr_data["regions"]]
        else:
            ocr_regions = [[]]
    else:
        ocr_regions = [[]]

    # 페이지 크기 추출
    page_sizes = None
    if isinstance(ocr_data, dict) and "page_sizes" in ocr_data:
        page_sizes = [tuple(s) for s in ocr_data["page_sizes"]]

    # Glossary 로드
    existing_glossary = None
    if glossary_json_path and os.path.exists(glossary_json_path):
        with open(glossary_json_path, "r", encoding="utf-8") as f:
            existing_glossary = json.load(f)

    return run_pipeline(
        ocr_regions=ocr_regions,
        output_dir=output_dir,
        page_sizes=page_sizes,
        existing_glossary=existing_glossary,
        llm_client=llm_client,
        **kwargs
    )


def _flatten_pages(pages: list[list[dict]]) -> list[dict]:
    """페이지별 리스트를 flat 리스트로 변환"""
    result = []
    for page_no, page_regions in enumerate(pages, 1):
        for region in page_regions:
            region["page_no"] = page_no
            result.append(region)
    return result


# CLI 지원
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="슬라이드 번역 파이프라인")
    parser.add_argument("ocr_json", help="OCR 결과 JSON 파일")
    parser.add_argument("output_dir", help="출력 디렉토리")
    parser.add_argument("--glossary", help="기존 glossary JSON 파일")
    parser.add_argument("--skip-translation", action="store_true", help="번역 스킵")

    args = parser.parse_args()

    result = run_pipeline_from_json(
        ocr_json_path=args.ocr_json,
        output_dir=args.output_dir,
        glossary_json_path=args.glossary,
        skip_translation=args.skip_translation
    )

    if result.success:
        print(f"Success! Output: {result.output_dir}")
    else:
        print(f"Failed at {result.stage_completed}: {result.error}")
