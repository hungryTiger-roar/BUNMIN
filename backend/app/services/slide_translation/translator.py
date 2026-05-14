"""
공통 번역 모듈

[역할]
- PDF Layer / OCR 공통 번역 함수
- TextBlock 리스트를 받아 번역 결과 dict 반환
- 청크 단위 배치 처리 (컨텍스트 윈도우 고려)
- PDF/OCR 소스별 분리 배치 (OCR 노이즈 격리)

[호출 경로]
slides.py → translator.py (이 파일)
           └── image_pipeline.py (translate_text_vlm)
           └── term_corrections.py (용어집)
"""
import re
import logging
from collections import Counter
from typing import Optional

from .models import TextBlock, TranslationResult
from .image_pipeline import translate_text_vlm
from .term_corrections import get_terms_in_text

logger = logging.getLogger(__name__)


def _is_invalid_translation(text: str) -> bool:
    """무효한 번역인지 확인"""
    if not text or not text.strip():
        return True

    text = text.strip()

    # 물음표/마침표만 있는 경우
    if re.match(r'^[\?\.\!\s]+$', text):
        return True

    # 메타 텍스트 패턴
    invalid_patterns = [
        r'^\[.*\]$',
        r'^untranslat',
        r'^unknown$',
        r'^n/?a$',
        r'^\?+$',
        r'^\.+$',
    ]
    for pattern in invalid_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return True

    # 영문자나 숫자가 전혀 없으면 무효
    if not re.search(r'[A-Za-z0-9가-힣]', text):
        return True

    return False


def translate_blocks(
    blocks: list[TextBlock],
    target_lang: str = "en",
    chunk_size: int = 15,
    context_summary: Optional[str] = None,
) -> TranslationResult:
    """
    TextBlock 리스트 번역

    Args:
        blocks: 번역할 TextBlock 리스트
        target_lang: 목표 언어 (기본: en)
        chunk_size: 배치당 최대 블록 수 (기본: 15)
        context_summary: 이전 페이지 요약 (맥락 공유용)

    Returns:
        TranslationResult: {block_id: 번역문} 매핑

    Notes:
        - PDF와 OCR 블록을 분리하여 배치 처리 (OCR 노이즈 격리)
        - 용어집(term_corrections.csv)은 모든 배치에 공유
        - 페이지 단위로 청크 (같은 페이지 블록은 함께)
    """
    if not blocks:
        return TranslationResult(translations={}, failed_ids=[])

    # PDF / OCR 분리
    pdf_blocks = [b for b in blocks if b.source == "pdf"]
    ocr_blocks = [b for b in blocks if b.source == "ocr"]

    translations: dict[str, str] = {}
    failed_ids: list[str] = []

    # 전체 텍스트에서 용어집 추출 (공유)
    all_text = " ".join(b.text for b in blocks)
    shared_terms = get_terms_in_text(all_text)

    # PDF 블록 번역
    if pdf_blocks:
        logger.info(f"[Translator] Translating {len(pdf_blocks)} PDF blocks")
        pdf_result = _translate_block_group(
            pdf_blocks,
            target_lang=target_lang,
            chunk_size=chunk_size,
            shared_terms=shared_terms,
            context_summary=context_summary,
            source_label="PDF",
        )
        translations.update(pdf_result.translations)
        failed_ids.extend(pdf_result.failed_ids)

    # OCR 블록 번역 (PDF와 분리)
    if ocr_blocks:
        logger.info(f"[Translator] Translating {len(ocr_blocks)} OCR blocks")
        ocr_result = _translate_block_group(
            ocr_blocks,
            target_lang=target_lang,
            chunk_size=chunk_size,
            shared_terms=shared_terms,
            context_summary=context_summary,
            source_label="OCR",
        )
        translations.update(ocr_result.translations)
        failed_ids.extend(ocr_result.failed_ids)

    logger.info(f"[Translator] Completed: {len(translations)} translated, {len(failed_ids)} failed")
    return TranslationResult(translations=translations, failed_ids=failed_ids)


def _translate_block_group(
    blocks: list[TextBlock],
    target_lang: str,
    chunk_size: int,
    shared_terms: dict[str, str],
    context_summary: Optional[str],
    source_label: str,
) -> TranslationResult:
    """블록 그룹 번역 (PDF 또는 OCR)"""
    translations: dict[str, str] = {}
    failed_ids: list[str] = []

    # 페이지별 그룹화
    page_groups: dict[int, list[TextBlock]] = {}
    for block in blocks:
        page = block.page
        if page not in page_groups:
            page_groups[page] = []
        page_groups[page].append(block)

    # 청크 생성 (페이지 단위, chunk_size 이하)
    chunks: list[list[TextBlock]] = []
    current_chunk: list[TextBlock] = []

    for page in sorted(page_groups.keys()):
        page_blocks = page_groups[page]

        # 현재 청크 + 페이지 블록이 chunk_size 초과하면 새 청크
        if current_chunk and len(current_chunk) + len(page_blocks) > chunk_size:
            chunks.append(current_chunk)
            current_chunk = []

        current_chunk.extend(page_blocks)

        # 현재 청크가 chunk_size 이상이면 새 청크
        if len(current_chunk) >= chunk_size:
            chunks.append(current_chunk)
            current_chunk = []

    if current_chunk:
        chunks.append(current_chunk)

    # 청크별 번역
    for i, chunk in enumerate(chunks):
        logger.info(f"[Translator] ===== {source_label} Chunk {i+1}/{len(chunks)} ({len(chunk)} blocks) =====")

        try:
            chunk_result = _translate_chunk(
                chunk,
                target_lang=target_lang,
                shared_terms=shared_terms,
                context_summary=context_summary,
            )
            translations.update(chunk_result)
            logger.info(f"[Translator] Chunk {i+1} completed: {len(chunk_result)} translations")
        except Exception as e:
            logger.error(f"[Translator] Chunk {i+1} FAILED: {e}")
            # 청크 실패 시 해당 블록들은 failed로 처리
            for block in chunk:
                failed_ids.append(block.block_id)

    return TranslationResult(translations=translations, failed_ids=failed_ids)


def _translate_chunk(
    blocks: list[TextBlock],
    target_lang: str,
    shared_terms: dict[str, str],
    context_summary: Optional[str],
) -> dict[str, str]:
    """단일 청크 번역"""
    # 프롬프트 생성
    prompt = _build_prompt(blocks, target_lang, shared_terms, context_summary)

    # VLM 호출
    response = translate_text_vlm(prompt)

    # 응답 파싱
    return _parse_response(response, blocks)


def _build_prompt(
    blocks: list[TextBlock],
    target_lang: str,
    shared_terms: dict[str, str],
    context_summary: Optional[str],
) -> str:
    """번역 프롬프트 생성"""
    prompt_parts = [
        f"Translate the following Korean texts to {target_lang.upper()}.",
        "This is for slide/PDF layout replacement, so translations must be concise and fit the original text boxes.",
    ]

    # 맥락 요약 (있으면)
    if context_summary:
        prompt_parts.append("")
        prompt_parts.append("=== DOCUMENT CONTEXT ===")
        prompt_parts.append(context_summary)
        prompt_parts.append("=== END CONTEXT ===")

    # 용어집
    if shared_terms:
        prompt_parts.append("")
        prompt_parts.append("=== MANDATORY TERMINOLOGY ===")
        prompt_parts.append("Use these exact terms when the Korean source term appears with the same meaning.")
        for ko, en in shared_terms.items():
            prompt_parts.append(f"  {ko} = {en}")
        prompt_parts.append("=== END TERMINOLOGY ===")

    # 반복 단어 힌트
    all_text = " ".join(b.text for b in blocks)
    korean_words = re.findall(r'[가-힣]{2,}', all_text)
    word_counts = Counter(korean_words)
    repeated_words = [word for word, count in word_counts.items() if count >= 2]

    if repeated_words:
        prompt_parts.append("")
        prompt_parts.append(
            "Terminology consistency hint: The following Korean terms appear multiple times. "
            "Use consistent English terms when they have the same meaning in context."
        )
        prompt_parts.append(f"  {', '.join(repeated_words[:20])}")  # 최대 20개

    # 번역 규칙
    prompt_parts.extend([
        "",
        "Rules by text type:",
        "- TITLE: Use a concise slide title. Do not omit essential meaning.",
        "- HEADING: Use a clear, compact section heading. Preserve all numbers.",
        "- TERM_DEFINITION: Preserve the 'Term: Definition' structure.",
        "- BODY: Translate naturally but compactly.",
        "- BULLET: Use sentence case. Keep it concise.",
        "- CAPTION: Use a brief description.",
        "",
        "General rules:",
        "1. Translate compactly so English fits in the original text box.",
        "2. Keep numbers as digits. Do not omit numbers.",
        "3. NEVER add bullet symbols (-, *, •) - they are preserved from original.",
        "4. Keep symbols (⇒, →, ·) exactly in place.",
        "5. If Korean has English in parentheses, keep only the English term when appropriate.",
        "6. Output format: [BLOCK_ID]: translated text",
        "7. NEVER omit place names, proper nouns, or specific details from the source.",
        "8. Korean inequalities: 이상 = 'or more' (≥), 초과 = 'more than' (>), 이하 = 'or less' (≤), 미만 = 'less than' (<).",
        "9. Use correct English grammar. For broken/failed states, use passive voice (e.g., 'the transmission broke' not 'broke the transmission').",
        "",
        "Texts to translate:",
    ])

    # 번역할 텍스트
    for block in blocks:
        role = block.role.upper()
        # OCR은 신뢰도 낮으면 표시
        confidence_note = ""
        if block.confidence is not None and block.confidence < 0.8:
            confidence_note = " [LOW_CONFIDENCE_OCR]"
        prompt_parts.append(f"[{block.block_id}] ({role}{confidence_note}): {block.text}")

    prompt_parts.extend([
        "",
        "Translations:"
    ])

    return "\n".join(prompt_parts)


def _parse_response(response: str, blocks: list[TextBlock]) -> dict[str, str]:
    """VLM 응답 파싱"""
    translations: dict[str, str] = {}

    # block_id → TextBlock 매핑
    block_map = {b.block_id: b for b in blocks}

    # 패턴: [block_id]: text 또는 [block_id] (ROLE): text
    pattern = r'\[([^\]]+)\](?:\s*\([^)]+\))?:\s*(.+?)(?=\n\[|\Z)'
    matches = re.findall(pattern, response, re.DOTALL)

    # 1차 파싱 실패 시 라인별 파싱
    if not matches:
        for line in response.strip().split('\n'):
            line = line.strip()
            if not line.startswith('['):
                continue
            if ']' not in line:
                continue
            first_bracket = line.index(']')
            block_id = line[1:first_bracket]
            rest = line[first_bracket + 1:]
            colon_idx = rest.find(':')
            if colon_idx == -1:
                continue
            translated = rest[colon_idx + 1:].strip()
            if block_id and translated:
                matches.append((block_id, translated))

    # 매칭 처리
    for block_id, translated in matches:
        block_id = block_id.strip()
        translated = translated.strip()

        # VLM이 남긴 마크업 태그 제거
        # 예: "(HEADING): text" → "text"
        # 예: "[pdf_p14_b5] (BODY): text" → "text"
        translated = re.sub(r'^\[[\w_]+\]\s*', '', translated)  # [block_id] 제거
        translated = re.sub(r'^\((?:TITLE|HEADING|BODY|BULLET|CAPTION|TERM_DEFINITION)\)\s*:?\s*', '', translated, flags=re.IGNORECASE)
        translated = translated.strip()

        # LLM이 추가한 bullet 기호 제거
        translated = re.sub(r'^[\-\*•■◆◇○●\s]+', '', translated).strip()

        # 무효 번역 스킵
        if _is_invalid_translation(translated):
            logger.warning(f"[Translator] Invalid translation for {block_id}: '{translated[:30]}'")
            continue

        # block_id가 원래 블록에 있는지 확인
        if block_id in block_map:
            translations[block_id] = translated
        else:
            logger.warning(f"[Translator] Unknown block_id: {block_id}")

    # 매칭 안 된 블록 로깅
    matched_ids = set(translations.keys())
    for block in blocks:
        if block.block_id not in matched_ids:
            logger.warning(f"[Translator] No translation for {block.block_id}")

    return translations
