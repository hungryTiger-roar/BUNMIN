"""
Final Korean Residual Audit (Phase 3)

최종 한글 잔존 검사

입력:
- blocks.final.json
- image_texts.translated.json
- 처리된 이미지 (optional, OCR 재검사용)

출력:
- residual_audit_report.json

역할:
- 모든 번역 결과에서 한글 잔존 검사
- 예외 허용 항목 (proper nouns, uncertain) 분류
- 품질 점수 산출
"""
import re
from typing import Optional
from .config import cfg


# 한글 유니코드 패턴
KOREAN_PATTERN = re.compile(r"[가-힣]+")

# ============================================================
# 구조 기반 패턴 (특정 단어/성씨 예외 금지 - 구조만 체크)
# ============================================================

# 구조적 컨텍스트 패턴: 한글이 예시로 나타나는 문맥 구조
# 형식: (regex, pattern_name, default_classification)
# - structural_exception: 높은 신뢰도 (단독으로도 허용)
# - review_needed: 낮은 신뢰도 (단독으로는 검토 필요, 다른 패턴과 함께면 승격)
STRUCTURAL_CONTEXT_PATTERNS = [
    # === 높은 신뢰도 패턴 (단독 허용) ===
    # ex) 또는 예) 뒤 예시 구조 (가장 명확한 패턴)
    (r"(?:ex|예|e\.g\.?)\s*\)\s*['\"]?[가-힣]", "example_marker", "structural_exception"),
    # 꺾쇠괄호 내 한글 (언어학 표기 전용, 길이 제한)
    (r"〈[가-힣,\s]{1,30}〉", "bracketed_list", "structural_exception"),
    # 형태소 분석 슬래시 표기 (eat/는/다, present/다)
    (r"[a-zA-Z]+/[가-힣]{1,3}(?:/|(?=\s|$))", "morpheme_notation", "structural_exception"),

    # === 낮은 신뢰도 패턴 (단독=review_needed, 다른 패턴과 함께=승격) ===
    # 괄호: 영어 단어 뒤 괄호 내 한글 (번역 병기 구조)
    # 'cover' (덮개), 'adult-like' (어른스럽다) 등
    (r"['\"]?[A-Za-z][A-Za-z\-]*['\"]?\s*\([가-힣\s]{1,15}\)", "translation_annotation", "review_needed"),
]
# 제거된 패턴 (너무 넓음):
# - 단독 따옴표 내 한글: 일반 문장에서도 자주 나타남
# - 콜론 뒤 한글: 목록 등에서 미번역일 수 있음
# - 단독 괄호 내 한글: 맥락 없이 너무 넓음


def run_residual_audit(
    final_blocks: list[dict],
    translated_image_texts: list[dict],
    glossary: dict,
    document_text: str = "",
    processed_images: Optional[list] = None,
    ocr_client=None
) -> dict:
    """최종 한글 잔존 검사 실행

    Args:
        final_blocks: blocks.final.json의 블록 리스트
        translated_image_texts: image_texts.translated.json의 텍스트 리스트
        glossary: 문서 glossary (uncertain 등 참조)
        document_text: 문서 전체 텍스트 (critical term 추출용)
        processed_images: 처리된 이미지 리스트 (optional)
        ocr_client: OCR 클라이언트 (이미지 재검사용)

    Returns:
        검사 리포트 dict
    """
    # Critical terms 추출 (glossary 기반 - 하드코딩 아님)
    from .domain_glossary import get_critical_terms_from_glossary
    critical_terms = get_critical_terms_from_glossary(glossary, document_text)

    report = {
        "block_audit": [],
        "image_text_audit": [],
        "image_ocr_audit": [],
        "summary": {},
        "critical_terms_used": list(critical_terms),  # 디버깅용
    }

    # 1. 블록 번역 결과 검사
    block_issues = audit_blocks(final_blocks, glossary, critical_terms)
    report["block_audit"] = block_issues

    # 2. 이미지 텍스트 번역 결과 검사
    image_text_issues = audit_image_texts(translated_image_texts, glossary, critical_terms)
    report["image_text_audit"] = image_text_issues

    # 3. 이미지 OCR 재검사 (optional)
    if processed_images and ocr_client:
        image_ocr_issues = audit_processed_images(processed_images, ocr_client)
        report["image_ocr_audit"] = image_ocr_issues

    # 4. 요약 통계
    report["summary"] = generate_audit_summary(report)

    return report


def audit_blocks(blocks: list[dict], glossary: dict, critical_terms: set = None) -> list[dict]:
    """블록 번역 결과 한글 잔존 검사 (모든 발견 항목 추적)"""
    issues = []

    for block in blocks:
        block_id = block.get("block_id", "")
        english = block.get("english", "")
        block_type = block.get("block_type", "")

        if not english:
            continue

        korean_found = KOREAN_PATTERN.findall(english)
        if not korean_found:
            continue

        for korean in korean_found:
            context = _extract_context(english, korean)
            # classify_korean은 이제 dict 반환 (critical_terms는 glossary 기반)
            classification_result = classify_korean(korean, glossary, context, block_type, critical_terms)

            issue = {
                "block_id": block_id,
                "page_no": block.get("page_no", 0),
                "korean": korean,
                "classification": classification_result["classification"],
                "reason": classification_result["reason"],
                "matched_patterns": classification_result["matched_patterns"],
                "context": context,
                "block_type": block_type,
            }

            # 분류에 따른 심각도 설정
            if classification_result["classification"] == "unexpected":
                issue["severity"] = "error"
            elif classification_result["classification"] == "review_needed":
                issue["severity"] = "warning"
            else:
                # structural_exception - 구조적으로 허용되지만 추적됨
                issue["severity"] = "info"

            # 모든 항목 추적 (조용히 pass하지 않음)
            issues.append(issue)

    return issues


def audit_image_texts(
    translated_texts: list[dict],
    glossary: dict,
    critical_terms: set = None
) -> list[dict]:
    """이미지 텍스트 번역 결과 한글 잔존 검사 (모든 발견 항목 추적)"""
    issues = []

    for text_item in translated_texts:
        english = text_item.get("english", "")
        region_type = text_item.get("region_type", "")

        if not english:
            continue

        korean_found = KOREAN_PATTERN.findall(english)
        if not korean_found:
            continue

        for korean in korean_found:
            # 원본 텍스트도 컨텍스트로 사용 (예시 패턴 확인)
            original = text_item.get("text", "")
            context = _extract_context(english, korean)
            # 원본에도 예시 패턴이 있을 수 있으므로 결합
            full_context = f"{original} {context}"
            # classify_korean은 이제 dict 반환 (critical_terms는 glossary 기반)
            classification_result = classify_korean(korean, glossary, full_context, region_type, critical_terms)

            issue = {
                "text_id": text_item.get("id", ""),
                "page_no": text_item.get("page_no", 0),
                "korean": korean,
                "classification": classification_result["classification"],
                "reason": classification_result["reason"],
                "matched_patterns": classification_result["matched_patterns"],
                "original": original,
                "context": context,
                "region_type": region_type,
            }

            # 분류에 따른 심각도 설정
            if classification_result["classification"] == "unexpected":
                issue["severity"] = "error"
            elif classification_result["classification"] == "review_needed":
                issue["severity"] = "warning"
            else:
                # structural_exception - 구조적으로 허용되지만 추적됨
                issue["severity"] = "info"

            # 모든 항목 추적 (조용히 pass하지 않음)
            issues.append(issue)

    return issues


def audit_processed_images(
    images: list,
    ocr_client
) -> list[dict]:
    """처리된 이미지 OCR 재검사

    최종 이미지에 한글이 남아있는지 OCR로 확인
    """
    issues = []

    for page_no, image in enumerate(images, 1):
        try:
            # OCR 실행
            ocr_result = ocr_client.recognize(image)

            # 결과에서 한글 검색
            for region in ocr_result:
                text = region.get("text", "")
                korean_found = KOREAN_PATTERN.findall(text)

                for korean in korean_found:
                    issues.append({
                        "page_no": page_no,
                        "korean": korean,
                        "bbox": region.get("bbox"),
                        "severity": "error",
                        "source": "image_ocr_recheck",
                    })

        except Exception as e:
            print(f"[ResidualAudit] OCR 오류 (page {page_no}): {e}")

    return issues


def classify_korean(
    korean: str,
    glossary: dict,
    context: str = "",
    block_type: str = "",
    critical_terms: set = None
) -> dict:
    """한글 분류 (구조 기반 - glossary의 critical term만 체크)

    Args:
        korean: 검사할 한글 텍스트
        glossary: 문서 glossary
        context: 한글이 발견된 문맥
        block_type: 블록 타입 (diagram_or_label_dense 등)
        critical_terms: glossary에서 추출한 critical term set (policy=force인 것들)

    Returns:
        dict with:
        - classification: "unexpected" | "structural_exception" | "review_needed" | "critical_error"
        - reason: 분류 이유
        - matched_patterns: 매칭된 구조 패턴 리스트 (복수 가능)
    """
    result = {
        "classification": "unexpected",
        "reason": "no_matching_structure",
        "matched_patterns": [],
    }

    # 0. Critical term 체크 (glossary 기반 - 하드코딩 아님)
    # glossary에서 policy=force인 용어 중 문서에 등장한 것만 critical
    if critical_terms:
        # 정확히 일치
        if korean in critical_terms:
            result["classification"] = "critical_error"
            result["reason"] = f"critical_term_untranslated:{korean}"
            return result

        # 4글자 이상 용어만 부분 매칭 허용
        for critical_term in critical_terms:
            if len(critical_term) >= 4:
                if critical_term in korean or korean in critical_term:
                    result["classification"] = "critical_error"
                    result["reason"] = f"critical_term_partial:{korean} (matches {critical_term})"
                    return result

    # 1. 구조적 컨텍스트 패턴 체크 (모든 매칭 패턴 수집)
    matched_patterns = []
    if context:
        for pattern, pattern_name, default_classification in STRUCTURAL_CONTEXT_PATTERNS:
            if re.search(pattern, context, re.IGNORECASE):
                matched_patterns.append({
                    "name": pattern_name,
                    "classification": default_classification
                })

    # 2. 패턴 기반 분류 결정 (복수 근거 점수화)
    if matched_patterns:
        result["matched_patterns"] = [p["name"] for p in matched_patterns]

        has_high_confidence = any(p["classification"] == "structural_exception" for p in matched_patterns)
        has_translation_annotation = any(p["name"] == "translation_annotation" for p in matched_patterns)

        # 승격 로직:
        # - 높은 신뢰도 패턴이 있으면 structural_exception
        # - 높은 신뢰도 + translation_annotation 함께면 structural_exception
        # - translation_annotation만 있으면 review_needed
        if has_high_confidence:
            result["classification"] = "structural_exception"
            pattern_names = ", ".join(result["matched_patterns"])
            result["reason"] = f"matches_structure:{pattern_names}"
            return result
        elif has_translation_annotation:
            # translation_annotation 단독은 review_needed
            result["classification"] = "review_needed"
            result["reason"] = "matches_structure:translation_annotation (low_confidence)"
            return result

    # 3. glossary의 uncertain 체크 (조용히 pass하지 않고 review_needed로)
    if korean in glossary.get("uncertain", {}):
        result["classification"] = "review_needed"
        result["reason"] = "glossary_uncertain"
        return result

    # 4. proper_nouns에 keep_korean=True로 명시된 경우만 structural_exception
    proper_nouns = glossary.get("proper_nouns", {})
    if korean in proper_nouns:
        entry = proper_nouns[korean]
        if entry.get("keep_korean") is True:
            result["classification"] = "structural_exception"
            result["reason"] = "glossary_keep_korean"
            return result

    # 5. block_type 기반 체크: diagram/label 블록은 review_needed
    if block_type and "diagram" in block_type.lower():
        result["classification"] = "review_needed"
        result["reason"] = f"block_type:{block_type}"
        return result

    # 6. 나머지는 unexpected (에러)
    return result


# looks_like_proper_noun 함수 제거됨 (특정 성씨 리스트 기반 예외 금지)


def _extract_context(text: str, korean: str, context_len: int = 30) -> str:
    """한글 주변 컨텍스트 추출"""
    idx = text.find(korean)
    if idx < 0:
        return ""

    start = max(0, idx - context_len)
    end = min(len(text), idx + len(korean) + context_len)

    return text[start:end]


def generate_audit_summary(report: dict) -> dict:
    """검사 요약 생성 (모든 발견 항목 추적)"""
    block_issues = report.get("block_audit", [])
    image_text_issues = report.get("image_text_audit", [])
    image_ocr_issues = report.get("image_ocr_audit", [])

    all_issues = block_issues + image_text_issues + image_ocr_issues

    # 심각도별 카운트
    error_count = sum(1 for i in all_issues if i.get("severity") == "error")
    warning_count = sum(1 for i in all_issues if i.get("severity") == "warning")
    info_count = sum(1 for i in all_issues if i.get("severity") == "info")

    # 분류별 카운트
    classification_counts = {}
    for issue in all_issues:
        cls = issue.get("classification", "unknown")
        classification_counts[cls] = classification_counts.get(cls, 0) + 1

    # 이유별 카운트 (추적용)
    reason_counts = {}
    for issue in all_issues:
        reason = issue.get("reason", "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    # 품질 점수 (0-100)
    quality_score = calculate_quality_score(
        error_count,
        warning_count,
        len(block_issues) + len(image_text_issues)
    )

    # pass 조건:
    # 1. error가 없어야 함
    # 2. critical_error가 없어야 함 (중요 용어 미번역)
    # 3. review_needed가 3개 이하여야 함
    review_needed_count = classification_counts.get("review_needed", 0)
    critical_error_count = classification_counts.get("critical_error", 0)
    unexpected_count = classification_counts.get("unexpected", 0)

    # critical_error는 무조건 fail
    is_pass = (error_count == 0) and (critical_error_count == 0) and (review_needed_count <= 3)

    return {
        "total_issues": len(all_issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "classification_counts": classification_counts,
        "reason_counts": reason_counts,
        "quality_score": quality_score,
        "pass": is_pass,
        # 추적 정보: 구조적 예외와 리뷰 필요 항목도 카운트
        "structural_exceptions": classification_counts.get("structural_exception", 0),
        "review_needed": review_needed_count,
        "critical_errors": critical_error_count,
        # pass 실패 이유 (디버깅용)
        "pass_fail_reason": None if is_pass else (
            "critical_terms_untranslated" if critical_error_count > 0 else
            "has_errors" if error_count > 0 else
            f"too_many_review_needed ({review_needed_count})"
        ),
    }


def calculate_quality_score(
    error_count: int,
    warning_count: int,
    total_items: int
) -> float:
    """품질 점수 계산

    Returns:
        0-100 점수
    """
    if total_items == 0:
        return 100.0

    # 에러당 -10점, 경고당 -2점
    penalty = (error_count * 10) + (warning_count * 2)
    score = max(0, 100 - penalty)

    return round(score, 1)


def save_audit_report(report: dict, output_path: str):
    """검사 리포트 저장"""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def format_audit_report_text(report: dict) -> str:
    """검사 리포트 텍스트 형식 (모든 발견 항목 표시)"""
    lines = []
    summary = report.get("summary", {})

    lines.append("=" * 60)
    lines.append("Korean Residual Audit Report")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Quality Score: {summary.get('quality_score', 0)}/100")
    lines.append(f"Pass: {'YES' if summary.get('pass') else 'NO'}")
    lines.append("")
    lines.append(f"Total Korean Found: {summary.get('total_issues', 0)}")
    lines.append(f"  - Errors (unexpected): {summary.get('error_count', 0)}")
    lines.append(f"  - Warnings (review_needed): {summary.get('warning_count', 0)}")
    lines.append(f"  - Allowed (structural_exception): {summary.get('info_count', 0)}")
    lines.append("")

    # 분류 이유별 통계
    reason_counts = summary.get("reason_counts", {})
    if reason_counts:
        lines.append("-" * 60)
        lines.append("Classification Reasons:")
        lines.append("-" * 60)
        for reason, count in reason_counts.items():
            lines.append(f"  {reason}: {count}")
        lines.append("")

    # 에러 상세
    if summary.get("error_count", 0) > 0:
        lines.append("-" * 60)
        lines.append("ERRORS (unexpected Korean - 번역 실패):")
        lines.append("-" * 60)

        for issue in report.get("block_audit", []):
            if issue.get("severity") == "error":
                lines.append(f"  Block {issue.get('block_id')}: '{issue.get('korean')}'")
                lines.append(f"    Reason: {issue.get('reason', 'unknown')}")
                lines.append(f"    Context: ...{issue.get('context', '')}...")

        for issue in report.get("image_text_audit", []):
            if issue.get("severity") == "error":
                lines.append(f"  Image Text: '{issue.get('korean')}'")
                lines.append(f"    Reason: {issue.get('reason', 'unknown')}")
                lines.append(f"    Original: {issue.get('original', '')[:50]}...")

    # 경고 상세 (review_needed)
    if summary.get("warning_count", 0) > 0:
        lines.append("")
        lines.append("-" * 60)
        lines.append("WARNINGS (review_needed - 수동 확인 필요):")
        lines.append("-" * 60)

        for issue in report.get("block_audit", []) + report.get("image_text_audit", []):
            if issue.get("severity") == "warning":
                block_id = issue.get("block_id", issue.get("text_id", ""))
                lines.append(f"  {block_id}: '{issue.get('korean')}'")
                lines.append(f"    Reason: {issue.get('reason', 'unknown')}")

    # 허용 항목 (structural_exception) - 추적용
    if summary.get("info_count", 0) > 0:
        lines.append("")
        lines.append("-" * 60)
        lines.append("ALLOWED (structural_exception - 추적됨):")
        lines.append("-" * 60)

        for issue in report.get("block_audit", []) + report.get("image_text_audit", []):
            if issue.get("severity") == "info":
                block_id = issue.get("block_id", issue.get("text_id", ""))
                lines.append(f"  {block_id}: '{issue.get('korean')}'")
                patterns = issue.get('matched_patterns', [])
                pattern_str = ", ".join(patterns) if patterns else "N/A"
                lines.append(f"    Patterns: {pattern_str}")

    return "\n".join(lines)


def extract_failed_regions(
    report: dict,
    final_blocks: list[dict]
) -> list[dict]:
    """Residual Audit 실패 영역 상세 정보 추출

    Args:
        report: run_residual_audit의 결과
        final_blocks: 최종 블록 리스트 (bbox 정보 포함)

    Returns:
        실패 영역 리스트:
        - page_no: 페이지 번호
        - bbox: 영역 bounding box
        - detected_text: 탐지된 한글 텍스트
        - source_block_id: 원본 블록 ID (prompt_id)
        - english_text: 번역된 영어 텍스트
        - failure_reason: 실패 이유
    """
    failed_regions = []

    # 블록 ID로 인덱싱
    blocks_by_id = {}
    for block in final_blocks:
        block_id = block.get("block_id", "")
        prompt_id = block.get("prompt_id", "")
        if block_id:
            blocks_by_id[block_id] = block
        if prompt_id:
            blocks_by_id[prompt_id] = block

    # block_audit에서 error 추출
    for issue in report.get("block_audit", []):
        if issue.get("severity") != "error":
            continue

        block_id = issue.get("block_id", "")
        block = blocks_by_id.get(block_id, {})

        failed_regions.append({
            "page_no": issue.get("page_no", block.get("page_no", 0)),
            "bbox": block.get("union_bbox", []),
            "detected_text": issue.get("korean", ""),
            "source_block_id": block.get("prompt_id", block_id),
            "english_text": block.get("english", "")[:100],
            "context": issue.get("context", ""),
            "failure_reason": "residual_korean",
            "classification": issue.get("classification", "unexpected"),
        })

    # image_text_audit에서 error 추출
    for issue in report.get("image_text_audit", []):
        if issue.get("severity") != "error":
            continue

        failed_regions.append({
            "page_no": issue.get("page_no", 0),
            "bbox": issue.get("bbox", []),
            "detected_text": issue.get("korean", ""),
            "source_block_id": issue.get("text_id", ""),
            "english_text": "",
            "context": issue.get("original", ""),
            "failure_reason": "image_text_residual_korean",
            "classification": issue.get("classification", "unexpected"),
        })

    # image_ocr_audit에서 error 추출
    for issue in report.get("image_ocr_audit", []):
        if issue.get("severity") != "error":
            continue

        failed_regions.append({
            "page_no": issue.get("page_no", 0),
            "bbox": issue.get("bbox", []),
            "detected_text": issue.get("korean", ""),
            "source_block_id": "",
            "english_text": "",
            "context": "",
            "failure_reason": "image_ocr_residual_korean",
            "classification": "unexpected",
        })

    return failed_regions


def save_failed_regions(failed_regions: list[dict], output_path: str):
    """실패 영역 정보 저장"""
    import json

    # 페이지 번호순 정렬
    failed_regions.sort(key=lambda x: (x.get("page_no", 0), x.get("source_block_id", "")))

    # 요약 통계
    summary = {
        "total_failed": len(failed_regions),
        "by_page": {},
        "by_reason": {},
    }

    for region in failed_regions:
        page_no = region.get("page_no", 0)
        reason = region.get("failure_reason", "unknown")

        summary["by_page"][str(page_no)] = summary["by_page"].get(str(page_no), 0) + 1
        summary["by_reason"][reason] = summary["by_reason"].get(reason, 0) + 1

    output = {
        "summary": summary,
        "failed_regions": failed_regions,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def save_review_log(report: dict, output_path: str):
    """모든 한글 발견 항목 저장 (추적용 - 조용히 pass하지 않음)

    이 함수는 error 뿐만 아니라 모든 한글 발견 항목을 저장합니다:
    - unexpected (error): 번역 실패
    - review_needed (warning): 수동 확인 필요
    - structural_exception (info): 구조적으로 허용되지만 추적됨

    사용자 요구사항: "의심되는 한글은 조용히 통과시키지 말고 추적 가능하게 저장"
    """
    import json
    from datetime import datetime

    block_issues = report.get("block_audit", [])
    image_text_issues = report.get("image_text_audit", [])
    image_ocr_issues = report.get("image_ocr_audit", [])

    all_issues = block_issues + image_text_issues + image_ocr_issues

    # 분류별로 정리
    log_entries = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "total_korean_found": len(all_issues),
        },
        "errors": [],  # unexpected - 번역 실패
        "warnings": [],  # review_needed - 수동 확인 필요
        "allowed": [],  # structural_exception - 구조적 허용 (추적됨)
    }

    for issue in all_issues:
        entry = {
            "korean": issue.get("korean", ""),
            "page_no": issue.get("page_no", 0),
            "block_id": issue.get("block_id", issue.get("text_id", "")),
            "classification": issue.get("classification", ""),
            "reason": issue.get("reason", ""),
            "matched_patterns": issue.get("matched_patterns", []),
            "context": issue.get("context", ""),
        }

        severity = issue.get("severity", "error")
        if severity == "error":
            log_entries["errors"].append(entry)
        elif severity == "warning":
            log_entries["warnings"].append(entry)
        else:
            log_entries["allowed"].append(entry)

    # 요약 통계
    log_entries["summary"] = {
        "errors": len(log_entries["errors"]),
        "warnings": len(log_entries["warnings"]),
        "allowed": len(log_entries["allowed"]),
        "total": len(all_issues),
    }

    # 페이지별 분포
    page_distribution = {}
    for issue in all_issues:
        page_no = str(issue.get("page_no", 0))
        if page_no not in page_distribution:
            page_distribution[page_no] = {"errors": 0, "warnings": 0, "allowed": 0}
        severity = issue.get("severity", "error")
        if severity == "error":
            page_distribution[page_no]["errors"] += 1
        elif severity == "warning":
            page_distribution[page_no]["warnings"] += 1
        else:
            page_distribution[page_no]["allowed"] += 1

    log_entries["page_distribution"] = page_distribution

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, ensure_ascii=False, indent=2)

    return log_entries


# ============================================================
# Final Image Korean Detection (최종 이미지 한글 감지)
# ============================================================

def detect_korean_in_final_images(
    rendered_images: list,
    original_regions: list[dict],
    final_blocks: list[dict],
    glossary: dict,
    document_text: str = "",
    ocr_service=None
) -> dict:
    """최종 렌더링된 이미지에서 한글 잔존 검사

    Args:
        rendered_images: 렌더링된 이미지 리스트 (PIL Image 또는 numpy array)
        original_regions: 원본 OCR regions (원인 분류용)
        final_blocks: 최종 블록 리스트 (원인 분류용)
        glossary: 문서 glossary (critical term 체크용)
        document_text: 문서 전체 텍스트
        ocr_service: OCR 서비스 인스턴스

    Returns:
        {
            "remaining_korean_regions": [...],
            "summary": {...},
            "has_critical": bool,
            "ocr_error_pages": [...],  # OCR 오류 발생 페이지 목록
            "pages_processed": int,
            "pages_skipped": int
        }
    """
    import numpy as np
    from PIL import Image
    import traceback

    # Critical terms 추출
    from .domain_glossary import get_critical_terms_from_glossary
    critical_terms = get_critical_terms_from_glossary(glossary, document_text)

    remaining_regions = []
    has_critical = False
    ocr_error_pages = []  # OCR 오류 발생 페이지 추적
    pages_processed = 0
    pages_skipped = 0

    # 원본 regions를 page_no + bbox로 인덱싱
    original_by_page = {}
    for r in original_regions:
        page_no = r.get("page_no", 1)
        if page_no not in original_by_page:
            original_by_page[page_no] = []
        original_by_page[page_no].append(r)

    # blocks를 page_no로 인덱싱
    blocks_by_page = {}
    for b in final_blocks:
        page_no = b.get("page_no", 1)
        if page_no not in blocks_by_page:
            blocks_by_page[page_no] = []
        blocks_by_page[page_no].append(b)

    print(f"[ResidualAudit] 최종 이미지 한글 감지 시작: {len(rendered_images)}개 페이지")

    for page_idx, image in enumerate(rendered_images):
        page_no = page_idx + 1

        # None 이미지 체크
        if image is None:
            print(f"[ResidualAudit] Page {page_no}: 이미지가 None - 스킵")
            pages_skipped += 1
            ocr_error_pages.append({
                "page_no": page_no,
                "error": "Image is None",
                "error_type": "image_null"
            })
            continue

        try:
            # 이미지를 numpy array로 변환
            if isinstance(image, Image.Image):
                img_np = np.array(image)
                print(f"[ResidualAudit] Page {page_no}: PIL Image -> numpy ({img_np.shape})")
            elif isinstance(image, np.ndarray):
                img_np = image
                print(f"[ResidualAudit] Page {page_no}: numpy array ({img_np.shape})")
            else:
                print(f"[ResidualAudit] Page {page_no}: 알 수 없는 이미지 타입: {type(image)}")
                pages_skipped += 1
                ocr_error_pages.append({
                    "page_no": page_no,
                    "error": f"Unknown image type: {type(image)}",
                    "error_type": "invalid_type"
                })
                continue

            # 이미지 유효성 체크
            if img_np is None or img_np.size == 0:
                print(f"[ResidualAudit] Page {page_no}: 빈 이미지 - 스킵")
                pages_skipped += 1
                ocr_error_pages.append({
                    "page_no": page_no,
                    "error": "Empty image array",
                    "error_type": "empty_image"
                })
                continue

            # OCR 서비스 초기화
            if ocr_service is None:
                from app.services.ocr_service import OCRService
                ocr_service = OCRService()

            # OCR 수행
            ocr_results = ocr_service.extract_with_positions(img_np, min_confidence=0.3)

            if ocr_results is None:
                print(f"[ResidualAudit] Page {page_no}: OCR 결과가 None")
                ocr_error_pages.append({
                    "page_no": page_no,
                    "error": "OCR returned None",
                    "error_type": "ocr_null_result"
                })
                pages_skipped += 1
                continue

            pages_processed += 1
            print(f"[ResidualAudit] Page {page_no}: OCR 완료 ({len(ocr_results)}개 텍스트 영역)")

            # 한글 검출
            for result in ocr_results:
                text = result.get("text", "")
                if text is None:
                    continue

                korean_found = KOREAN_PATTERN.findall(text)

                if not korean_found:
                    continue

                bbox = result.get("bbox", [])
                if isinstance(bbox, list) and len(bbox) == 4:
                    if isinstance(bbox[0], list):
                        xs = [p[0] for p in bbox]
                        ys = [p[1] for p in bbox]
                        bbox = [min(xs), min(ys), max(xs), max(ys)]

                for korean in korean_found:
                    # 원인 분류
                    cause = classify_remnant_cause(
                        korean, bbox, page_no,
                        original_by_page.get(page_no, []),
                        blocks_by_page.get(page_no, [])
                    )

                    # Critical 체크
                    is_critical = korean in critical_terms
                    if not is_critical:
                        for ct in critical_terms:
                            if len(ct) >= 4 and (ct in korean or korean in ct):
                                is_critical = True
                                break

                    if is_critical:
                        has_critical = True

                    remaining_regions.append({
                        "page_no": page_no,
                        "bbox": bbox,
                        "detected_text": korean,
                        "full_ocr_text": text,
                        "confidence": result.get("confidence", 0),
                        "cause": cause,
                        "is_critical": is_critical,
                        "source_region_id": cause.get("source_region_id"),
                        "block_id": cause.get("block_id"),
                        "render_target": cause.get("render_target", False),
                    })

        except Exception as e:
            error_msg = str(e)
            print(f"[ResidualAudit] Page {page_no}: OCR 오류 - {error_msg}")
            traceback.print_exc()
            pages_skipped += 1
            ocr_error_pages.append({
                "page_no": page_no,
                "error": error_msg,
                "error_type": "exception"
            })

    print(f"[ResidualAudit] 완료: processed={pages_processed}, skipped={pages_skipped}, errors={len(ocr_error_pages)}")

    # 요약
    summary = {
        "total_remaining": len(remaining_regions),
        "critical_remaining": sum(1 for r in remaining_regions if r.get("is_critical")),
        "by_cause": {},
        "by_page": {},
        "pages_processed": pages_processed,
        "pages_skipped": pages_skipped,
    }

    for r in remaining_regions:
        cause_type = r.get("cause", {}).get("type", "unknown")
        summary["by_cause"][cause_type] = summary["by_cause"].get(cause_type, 0) + 1

        page_no = str(r.get("page_no", 0))
        summary["by_page"][page_no] = summary["by_page"].get(page_no, 0) + 1

    return {
        "remaining_korean_regions": remaining_regions,
        "summary": summary,
        "has_critical": has_critical,
        "ocr_error_pages": ocr_error_pages,
        "pages_processed": pages_processed,
        "pages_skipped": pages_skipped,
    }


def classify_remnant_cause(
    korean: str,
    bbox: list,
    page_no: int,
    page_regions: list[dict],
    page_blocks: list[dict]
) -> dict:
    """잔존 한글의 원인 분류

    원인 분류:
    - A_ocr_missing: 원본 OCR에 해당 한글이 없음
    - B_excluded_by_filter: OCR됐으나 노이즈 필터로 제외됨
    - C_not_in_blocks: regions에는 있으나 blocks에 없음
    - D_translated_not_rendered: blocks에 영어 있으나 렌더링 안 됨
    - E_mask_residue: 마스킹 실패 (영어 올라갔으나 한글 잔상)

    Returns:
        {
            "type": str,
            "description": str,
            "source_region_id": str or None,
            "block_id": str or None,
            "render_target": bool
        }
    """
    result = {
        "type": "A_ocr_missing",
        "description": "원본 OCR에서 감지되지 않음",
        "source_region_id": None,
        "block_id": None,
        "render_target": False,
    }

    # 1. 원본 OCR에서 해당 한글 검색
    matching_region = None
    for region in page_regions:
        ocr_text = region.get("ocr_text", "") or region.get("ocr_text_raw", "")
        if korean in ocr_text:
            matching_region = region
            break

    if not matching_region:
        # A. OCR 미검출
        return result

    result["source_region_id"] = matching_region.get("_idx", matching_region.get("id"))

    # 2. 노이즈 필터 체크
    classification = matching_region.get("_classification", "")
    if classification in ["decorative_noise", "excluded"]:
        result["type"] = "B_excluded_by_filter"
        result["description"] = f"노이즈 필터로 제외됨 ({classification})"
        return result

    # 3. blocks에 있는지 체크
    matching_block = None
    for block in page_blocks:
        source_text = block.get("source_text", "")
        if korean in source_text:
            matching_block = block
            break

    if not matching_block:
        result["type"] = "C_not_in_blocks"
        result["description"] = "regions에는 있으나 번역 블록에 포함되지 않음"
        return result

    result["block_id"] = matching_block.get("prompt_id", matching_block.get("block_id"))
    result["render_target"] = matching_block.get("translation_available", False)

    # 4. 번역 결과 체크
    english = matching_block.get("english", "")
    if not english:
        result["type"] = "D_translated_not_rendered"
        result["description"] = "번역 결과 없음"
        return result

    # 5. 번역됐으나 렌더링 문제
    result["type"] = "E_mask_residue"
    result["description"] = "마스킹/렌더링 실패 (한글 잔상 남음)"

    return result


def save_remaining_korean_regions(
    detection_result: dict,
    output_path: str
):
    """remaining_korean_regions.json 저장"""
    import json

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(detection_result, f, ensure_ascii=False, indent=2)

    summary = detection_result.get("summary", {})
    ocr_errors = detection_result.get("ocr_error_pages", [])

    print(f"[ResidualAudit] Saved remaining_korean_regions.json: "
          f"{summary.get('total_remaining', 0)} regions, "
          f"{summary.get('critical_remaining', 0)} critical, "
          f"processed={summary.get('pages_processed', 0)}, "
          f"skipped={summary.get('pages_skipped', 0)}")

    if ocr_errors:
        print(f"[ResidualAudit] WARNING: {len(ocr_errors)}개 페이지에서 OCR 오류 발생:")
        for err in ocr_errors:
            print(f"  Page {err.get('page_no')}: {err.get('error_type')} - {err.get('error')}")


# ============================================================
# Low Confidence OCR Review (저신뢰 OCR 검토)
# ============================================================

LOW_CONFIDENCE_THRESHOLD = 0.5


def detect_low_confidence_ocr(
    all_regions: list[dict],
    glossary: dict,
    confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD
) -> dict:
    """저신뢰 OCR 결과 감지

    confidence < threshold 이고 한글이 포함된 OCR 결과를 검토 대상으로 마킹

    Args:
        all_regions: 모든 OCR regions (page_no 포함)
        glossary: 문서 glossary (suggested_candidates 참고용)
        confidence_threshold: 신뢰도 임계값 (기본 0.5)

    Returns:
        {
            "low_confidence_items": [...],
            "summary": {
                "total_count": int,
                "by_page": {...}
            }
        }
    """
    low_confidence_items = []

    # 페이지별 regions 인덱싱 (nearby_terms용)
    regions_by_page = {}
    for r in all_regions:
        page_no = r.get("page_no", 1)
        if page_no not in regions_by_page:
            regions_by_page[page_no] = []
        regions_by_page[page_no].append(r)

    for region in all_regions:
        confidence = region.get("confidence", 1.0)
        ocr_text = region.get("ocr_text", "") or ""

        # confidence < threshold 이고 한글 포함
        if confidence < confidence_threshold and KOREAN_PATTERN.search(ocr_text):
            page_no = region.get("page_no", 1)
            bbox = region.get("bbox", [])

            # nearby_terms 수집 (같은 페이지, bbox 근처)
            nearby_terms = _get_nearby_terms(
                region, regions_by_page.get(page_no, [])
            )

            # glossary에서 후보 검색 (참고용)
            suggested_candidates = _find_glossary_candidates(
                ocr_text, nearby_terms, glossary
            )

            low_confidence_items.append({
                "page_no": page_no,
                "bbox": bbox,
                "ocr_text": ocr_text,
                "confidence": confidence,
                "nearby_terms": nearby_terms,
                "suggested_candidates": suggested_candidates,
                "region_type": region.get("_region_type", "unknown"),
                "classification": region.get("_classification", "unknown"),
            })

    # 페이지별 집계
    by_page = {}
    for item in low_confidence_items:
        page_no = str(item.get("page_no", 0))
        by_page[page_no] = by_page.get(page_no, 0) + 1

    return {
        "low_confidence_items": low_confidence_items,
        "summary": {
            "total_count": len(low_confidence_items),
            "by_page": by_page,
            "threshold": confidence_threshold,
        }
    }


def _get_nearby_terms(
    target_region: dict,
    page_regions: list[dict],
    distance_threshold: int = 200
) -> list[str]:
    """주변 텍스트 수집 (bbox 기준 distance_threshold 이내)"""
    target_bbox = target_region.get("bbox", [])
    if not target_bbox or len(target_bbox) < 4:
        return []

    # target 중심점
    tx = (target_bbox[0] + target_bbox[2]) / 2
    ty = (target_bbox[1] + target_bbox[3]) / 2

    nearby = []
    for r in page_regions:
        if r is target_region:
            continue

        other_bbox = r.get("bbox", [])
        if not other_bbox or len(other_bbox) < 4:
            continue

        # other 중심점
        ox = (other_bbox[0] + other_bbox[2]) / 2
        oy = (other_bbox[1] + other_bbox[3]) / 2

        # 거리 계산
        distance = ((tx - ox) ** 2 + (ty - oy) ** 2) ** 0.5

        if distance < distance_threshold:
            text = r.get("ocr_text", "")
            if text and len(text) > 1:
                nearby.append(text)

    return nearby[:10]  # 최대 10개


def _find_glossary_candidates(
    ocr_text: str,
    nearby_terms: list[str],
    glossary: dict
) -> list[dict]:
    """glossary에서 후보 검색 (참고용)

    nearby_terms와 연관된 glossary 항목 반환
    - 도메인 힌트 활용 (문법, 품사 등 키워드 감지)
    - 길이 유사성 체크
    """
    if not glossary:
        return []

    # glossary가 terms 키를 가지고 있으면 그것을 사용
    terms = glossary.get("terms", glossary)

    candidates = []
    all_context = " ".join(nearby_terms)
    all_context_lower = all_context.lower()

    # 도메인 힌트 감지 (nearby_terms에서)
    domain_hints = []
    domain_keywords = {
        "grammar": ["문법", "품사", "형태소", "접사", "어미", "조사"],
        "linguistics": ["언어", "의미", "형태", "통사", "음운"],
        "nlp": ["처리", "분석", "토큰", "파싱"],
    }
    for domain, keywords in domain_keywords.items():
        if any(kw in all_context for kw in keywords):
            domain_hints.append(domain)

    for korean, entry in terms.items():
        if not isinstance(entry, dict):
            continue

        english = entry.get("english", "")
        domain = entry.get("domain", "")

        # 1. nearby_terms에 해당 한글 용어가 있으면 후보로 추가
        if korean in all_context:
            candidates.append({
                "korean": korean,
                "english": english,
                "domain": domain,
                "match_reason": "context_match",
                "score": 100
            })
            continue

        # 2. ocr_text와 길이가 비슷하고 (±1자)
        len_diff = abs(len(korean) - len(ocr_text))
        if len_diff <= 1:
            score = 50 - len_diff * 10

            # 도메인 힌트와 매칭되면 점수 증가
            if domain_hints and domain:
                domain_lower = domain.lower()
                for hint in domain_hints:
                    if hint in domain_lower or domain_lower in hint:
                        score += 30
                        break

            # 문법 관련 키워드가 nearby_terms에 있고, 한글 용어가 문법 관련이면 점수 증가
            grammar_terms = ["접사", "어미", "조사", "명사", "동사", "형용사", "부사"]
            if any("문법" in t or "품사" in t for t in nearby_terms):
                if korean in grammar_terms or any(gt in korean for gt in grammar_terms):
                    score += 40

            candidates.append({
                "korean": korean,
                "english": english,
                "domain": domain,
                "match_reason": "length_similar" + ("+domain_hint" if score > 50 else ""),
                "score": score
            })

    # 점수순 정렬 후 상위 5개 반환
    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    return candidates[:5]


def save_low_confidence_review(
    detection_result: dict,
    output_path: str
):
    """ocr_low_confidence_review.json 저장"""
    import json

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(detection_result, f, ensure_ascii=False, indent=2)

    summary = detection_result.get("summary", {})
    print(f"[ResidualAudit] Saved ocr_low_confidence_review.json: "
          f"{summary.get('total_count', 0)} items (threshold={summary.get('threshold', 0.5)})")

    if summary.get("total_count", 0) > 0:
        print(f"[ResidualAudit] Low confidence OCR by page: {summary.get('by_page', {})}")


# ============================================================
# Fallback OCR Classification (Score-based, Conservative)
# ============================================================

def classify_fallback_ocr_text(
    text: str,
    confidence: float,
    bbox: list,
    page_type: str,
    ocr_variants: list,
    glossary: dict,
    nearby_context: list = None,
    page_size: tuple = None,
) -> dict:
    """
    Fallback OCR 텍스트를 score 기반으로 분류 (보수적 판정)

    특정 단어 목록으로 판단하지 않고, 구조적/통계적 조건으로 판단
    translate 판정은 glossary exact/fuzzy match 또는 안정적 OCR variant가 있을 때만 허용

    Args:
        text: OCR로 감지된 텍스트
        confidence: OCR confidence (0.0~1.0)
        bbox: [x1, y1, x2, y2] 좌표
        page_type: 페이지 유형 (paragraph_or_bullet, diagram_or_label_dense 등)
        ocr_variants: 여러 OCR 시도 결과 리스트 [{"text": "...", "confidence": ...}, ...]
        glossary: generated/domain glossary dict
        nearby_context: 주변 텍스트 영역 리스트
        page_size: (width, height) 페이지 크기

    Returns:
        {
            "decision": "translate" | "review_needed" | "unresolved",
            "reason": "판정 근거 설명",
            "confidence_score": 0.0~1.0,
            "score_breakdown": {...},
            "has_strong_signal": bool  # glossary exact/fuzzy 또는 stable OCR
        }
    """
    score = 0.0
    score_breakdown = {}
    reasons = []

    # translate 허용을 위한 strong signal 추적
    has_glossary_exact = False
    has_glossary_fuzzy = False
    has_stable_ocr = False
    has_only_partial = False

    text_clean = text.replace(" ", "").strip()
    text_len = len(text_clean)

    # ========== 1. 기본 텍스트 길이 체크 ==========
    if text_len >= 2:
        # 2글자 이상이지만 점수는 작게 (complete word 판정은 별도)
        score += 0.05
        score_breakdown["korean_length_2_or_more"] = 0.05
    elif text_len == 1:
        score -= 0.3
        score_breakdown["single_char"] = -0.3
        reasons.append("1글자 텍스트")
    else:
        return {
            "decision": "unresolved",
            "reason": "빈 텍스트",
            "confidence_score": 0.0,
            "score_breakdown": {"empty_text": -1.0},
            "has_strong_signal": False
        }

    # ========== 2. OCR Confidence 체크 ==========
    if confidence >= 0.8:
        score += 0.15
        score_breakdown["high_confidence"] = 0.15
    elif confidence >= 0.6:
        score += 0.1
        score_breakdown["medium_confidence"] = 0.1
    elif confidence >= 0.4:
        # 중간 - 점수 추가 없음
        score_breakdown["low_confidence"] = 0.0
    else:
        score -= 0.3
        score_breakdown["very_low_confidence"] = -0.3
        reasons.append(f"OCR confidence 매우 낮음 ({confidence:.2f})")

    # ========== 3. OCR Variants 안정성 체크 ==========
    if ocr_variants and len(ocr_variants) >= 2:
        variant_texts = [v.get("text", "").replace(" ", "") for v in ocr_variants if v.get("text")]

        if variant_texts:
            from collections import Counter
            text_counts = Counter(variant_texts)
            most_common_text, most_common_count = text_counts.most_common(1)[0]
            stability_ratio = most_common_count / len(variant_texts)

            if stability_ratio >= 0.8:
                score += 0.3
                score_breakdown["stable_ocr_variants"] = 0.3
                has_stable_ocr = True  # Strong signal
            elif stability_ratio >= 0.5:
                score += 0.1
                score_breakdown["moderate_ocr_stability"] = 0.1
            else:
                score -= 0.4
                score_breakdown["unstable_ocr_variants"] = -0.4
                reasons.append(f"OCR 결과 불안정 (일치율 {stability_ratio:.0%})")

    # ========== 4. Glossary 매칭 체크 ==========
    glossary_match_result = _check_glossary_match(text_clean, glossary, text_len)

    if glossary_match_result.get("exact_match"):
        score += 0.45
        score_breakdown["glossary_exact_match"] = 0.45
        has_glossary_exact = True  # Strong signal
    elif glossary_match_result.get("fuzzy_match"):
        # 짧은 단어(2-3자)는 fuzzy match 점수 낮게
        if text_len <= 3:
            score += 0.15
            score_breakdown["glossary_fuzzy_match_short"] = 0.15
        else:
            score += 0.3
            score_breakdown["glossary_fuzzy_match"] = 0.3
            has_glossary_fuzzy = True  # Strong signal (4자 이상만)
    elif glossary_match_result.get("partial_match"):
        # partial_match는 review signal만 (translate 판정에 기여 안함)
        score += 0.05
        score_breakdown["glossary_partial_match"] = 0.05
        has_only_partial = True
        reasons.append("glossary partial match만 있음")
    else:
        # glossary 매칭 없음 - 약간의 패널티
        score -= 0.1
        score_breakdown["no_glossary_match"] = -0.1

    # ========== 5. Bbox 라벨 영역 체크 ==========
    is_small_label = False
    if bbox and len(bbox) == 4:
        x1, y1, x2, y2 = bbox
        bbox_width = x2 - x1
        bbox_height = y2 - y1
        bbox_area = bbox_width * bbox_height

        if page_size:
            page_w, page_h = page_size
            area_ratio = bbox_area / (page_w * page_h) if page_w * page_h > 0 else 0
            if area_ratio < 0.02:
                is_small_label = True
        else:
            if bbox_area < 20000:
                is_small_label = True

        if is_small_label:
            score += 0.1
            score_breakdown["label_like_bbox"] = 0.1

        if page_type == "diagram_or_label_dense" and is_small_label:
            score += 0.05
            score_breakdown["diagram_page_label"] = 0.05

    # ========== 6. 불완전 조각 (Fragment) 체크 ==========
    fragment_result = _check_fragment_patterns(text_clean)

    if fragment_result.get("is_fragment"):
        score -= 0.4
        score_breakdown["fragment_like"] = -0.4
        reasons.append(fragment_result.get("reason", "불완전 조각"))
    elif fragment_result.get("is_likely_complete"):
        # complete word 점수는 작게 (glossary/OCR stability 없이는 translate 불가)
        score += 0.05
        score_breakdown["likely_complete_word"] = 0.05

    # ========== 7. 문맥 매칭 체크 ==========
    if nearby_context:
        context_result = _check_context_match(text_clean, nearby_context)
        if context_result.get("has_context_match"):
            score += 0.1
            score_breakdown["context_match"] = 0.1
        elif context_result.get("no_context"):
            score -= 0.05
            score_breakdown["no_context_match"] = -0.05

    # ========== 최종 판정 (보수적) ==========
    final_score = max(0.0, min(1.0, score))
    has_strong_signal = has_glossary_exact or has_glossary_fuzzy or has_stable_ocr

    # translate 판정 조건:
    # 1. score >= 0.6 AND
    # 2. strong signal이 있어야 함 (glossary exact/fuzzy 또는 stable OCR)
    # 3. partial_match만 있으면 translate 불가

    if final_score >= 0.6 and has_strong_signal and not has_only_partial:
        decision = "translate"
        reason = "번역 허용"
        if has_glossary_exact:
            reason += " (glossary exact match)"
        elif has_glossary_fuzzy:
            reason += " (glossary fuzzy match)"
        elif has_stable_ocr:
            reason += " (stable OCR variants)"
    elif final_score >= 0.6 and not has_strong_signal:
        # score는 높지만 strong signal 없음 → review_needed
        decision = "review_needed"
        reason = "점수 충분하나 glossary/OCR 확인 필요"
        reasons.append("strong signal 없음")
    elif final_score >= 0.3:
        decision = "review_needed"
        reason = "검토 필요"
        if reasons:
            reason += f": {', '.join(reasons)}"
    else:
        decision = "unresolved"
        reason = "자동 번역 불가"
        if reasons:
            reason += f": {', '.join(reasons)}"

    return {
        "decision": decision,
        "reason": reason,
        "confidence_score": final_score,
        "score_breakdown": score_breakdown,
        "has_strong_signal": has_strong_signal,
        "glossary_match": {
            "exact": has_glossary_exact,
            "fuzzy": has_glossary_fuzzy,
            "partial_only": has_only_partial
        },
        "stable_ocr": has_stable_ocr
    }


def _check_glossary_match(text: str, glossary: dict, text_len: int = None) -> dict:
    """
    Glossary와의 매칭 체크 (exact, fuzzy, partial) - 보수적 판정

    하드코딩된 단어 목록 없이, glossary/domain glossary/terms만 사용
    짧은 단어(2-3자)는 exact/alias 중심으로 보수적 처리
    """
    if not glossary:
        return {"exact_match": False, "fuzzy_match": False, "partial_match": False}

    result = {"exact_match": False, "fuzzy_match": False, "partial_match": False}

    if text_len is None:
        text_len = len(text)

    all_korean_terms = set()

    # 1. terms dict 구조 (glossary.generated.json의 주요 구조)
    terms_dict = glossary.get("terms", {})
    for korean_term in terms_dict.keys():
        if korean_term and KOREAN_PATTERN.search(korean_term):
            all_korean_terms.add(korean_term.replace(" ", ""))

    # 2. Generated glossary entries (list 구조)
    entries = glossary.get("entries", [])
    for entry in entries:
        korean = entry.get("korean", "")
        if korean:
            all_korean_terms.add(korean.replace(" ", ""))

    # 3. Domain glossary entries (merged)
    domain_entries = glossary.get("domain_entries", [])
    for entry in domain_entries:
        korean = entry.get("korean", "")
        if korean:
            all_korean_terms.add(korean.replace(" ", ""))

    # 4. Alias mappings
    aliases = glossary.get("aliases", {})
    for alias_list in aliases.values():
        for alias in alias_list:
            if KOREAN_PATTERN.search(alias):
                all_korean_terms.add(alias.replace(" ", ""))

    # 5. domain_glossary 내부 구조 (nested)
    domain_glossary = glossary.get("domain_glossary", {})
    for domain_name, domain_data in domain_glossary.items():
        if isinstance(domain_data, dict):
            for korean_term in domain_data.get("terms", {}).keys():
                if korean_term and KOREAN_PATTERN.search(korean_term):
                    all_korean_terms.add(korean_term.replace(" ", ""))

    # ========== Exact match ==========
    if text in all_korean_terms:
        result["exact_match"] = True
        return result

    # ========== Fuzzy match (보수적) ==========
    # 2-3글자 단어는 fuzzy match 비활성화 (오탐 위험)
    # 4글자 이상만 fuzzy match 허용
    if text_len >= 4:
        # RapidFuzz 사용 시도
        try:
            from rapidfuzz import fuzz
            for term in all_korean_terms:
                if len(term) >= 3:
                    # token_ratio 사용 (더 정확)
                    ratio = fuzz.ratio(text, term)
                    if ratio >= 85:  # 85% 이상 일치
                        result["fuzzy_match"] = True
                        return result
        except ImportError:
            # RapidFuzz 없으면 simple character overlap 사용
            for term in all_korean_terms:
                if len(term) >= 4 and abs(len(term) - text_len) <= 1:
                    # 정확한 character 비교
                    matches = sum(1 for i, c in enumerate(text) if i < len(term) and term[i] == c)
                    similarity = matches / max(text_len, len(term))
                    if similarity >= 0.85:
                        result["fuzzy_match"] = True
                        return result

    # ========== Partial match (review signal만) ==========
    # partial match는 원문 일부 잘림 가능성 있음 → translate 불가, review만
    for term in all_korean_terms:
        if len(term) >= 4 and text_len >= 2:
            # text가 term의 일부인 경우만 (역방향은 위험)
            if text in term and text != term:
                result["partial_match"] = True
                return result

    return result


def _check_fragment_patterns(text: str) -> dict:
    """
    불완전 조각 패턴 체크

    특정 단어 목록 없이, 구조적 패턴으로 판단:
    - 조사/어미만 있는 경우
    - 자음/모음 조합이 불완전한 경우
    - 일반적인 단어 구조가 아닌 경우
    """
    result = {"is_fragment": False, "is_likely_complete": False, "reason": None}

    # 한글 자모 분리 체크 (조합되지 않은 자음/모음)
    JAMO_PATTERN = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]")
    if JAMO_PATTERN.search(text):
        result["is_fragment"] = True
        result["reason"] = "분리된 자모 포함"
        return result

    # 조사/어미만 있는 패턴 체크 (2글자 이하에서 의미 없는 조합)
    # 주의: 하드코딩 단어 목록이 아닌 구조적 패턴
    if len(text) <= 2:
        # 한국어 문법적으로 단독 사용이 어려운 패턴
        # 자음 종성 없이 모음으로만 끝나는 1글자 + 조사성 2글자
        ENDING_PARTICLE_PATTERN = re.compile(r"^[은는이가을를와과의로]$")
        if ENDING_PARTICLE_PATTERN.match(text):
            result["is_fragment"] = True
            result["reason"] = "조사 단독 사용"
            return result

    # 반복 문자 체크 (같은 글자 3회 이상)
    for char in set(text):
        if text.count(char) >= 3 and len(text) <= 5:
            result["is_fragment"] = True
            result["reason"] = "비정상 반복 패턴"
            return result

    # 의미 있는 단어 구조 체크
    # 2글자 이상의 일반적인 한글 구조면 완전한 단어로 추정
    if len(text) >= 2:
        # 자음+모음 조합이 정상적이면 완전한 단어로 추정
        if KOREAN_PATTERN.fullmatch(text):
            result["is_likely_complete"] = True

    return result


def _check_context_match(text: str, nearby_context: list) -> dict:
    """
    주변 문맥과의 연관성 체크

    nearby_context: [{"text": "...", "bbox": [...], ...}, ...]
    """
    result = {"has_context_match": False, "no_context": False}

    if not nearby_context:
        result["no_context"] = True
        return result

    # 주변 텍스트에서 같은 단어가 있는지 확인
    for ctx in nearby_context:
        ctx_text = ctx.get("text", "") or ctx.get("source_text", "")
        if ctx_text and text in ctx_text:
            result["has_context_match"] = True
            return result

    # 주변 텍스트와 유사한 도메인 용어인지 확인
    # (예: 주변에 "처리", "분석" 등 NLP 용어가 있으면 관련 가능성)

    return result
