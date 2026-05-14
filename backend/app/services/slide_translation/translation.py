"""
Block Translation

블록 번역 (LLM 호출)

입력:
- blocks.protected.json
- glossary.generated.json

출력:
- blocks.translated.json

역할:
- 프롬프트 생성 (타입 정보 + PROTECTED TOKEN MAP)
- LLM 호출
- model raw output 저장
"""
import re
from typing import Optional

from .term_corrections import get_terms_in_text


def build_translation_prompt(
    blocks: list[dict],
    glossary: dict,
    page_context: Optional[dict] = None
) -> str:
    """번역 프롬프트 생성

    Args:
        blocks: 보호된 블록 리스트
        glossary: 문서 glossary
        page_context: 페이지 컨텍스트 (optional)

    Returns:
        LLM 프롬프트 문자열
    """
    # 페이지 타입 확인 (블록들이 같은 페이지라고 가정)
    page_type = blocks[0].get("page_type", "paragraph_or_bullet") if blocks else "paragraph_or_bullet"
    is_diagram_page = page_type == "diagram_or_label_dense"

    # 짧은 라벨 개수 확인
    short_label_count = sum(1 for b in blocks if b.get("is_short_label") or len(b.get("source_text", "").strip()) < 30)
    has_many_short_labels = short_label_count > len(blocks) * 0.5

    # 헤더
    prompt_parts = [
        "Translate the following Korean text blocks to English.",
        "",
        "## Rules:",
        "1. Preserve all protected tokens exactly as they appear (e.g., __PN_001__, __ORG_001__, __TERM_001__)",
        "2. Translate each block separately, maintaining the EXACT block ID format",
        "3. If a Korean proper noun is not in the glossary, keep it in Korean",
        "4. Output ONLY the translated text for each block. Do NOT include metadata, type labels, or explanations.",
        "",
        "## Natural English Guidelines:",
        "- Write fluent, grammatically correct English sentences.",
        "- Use natural plural forms where appropriate.",
        "- For bilingual terms in the form 'KoreanTerm(EnglishTerm)', use the English term naturally and do not duplicate it.",
        "- For definition patterns like 'KoreanTerm(EnglishTerm): explanation', translate as 'EnglishTerm: translated explanation'.",
        "- Do not produce duplicated terms such as 'EnglishTerm(EnglishTerm)'.",
        "- Some blocks contain text merged from multiple OCR regions that together form ONE sentence.",
        "- Translate such merged blocks as one coherent English sentence, not as separate line fragments.",
        "- Do not translate Korean line fragments literally if they form one complete idea.",
        "- Avoid leaving dangling final nouns such as 'Research', 'Study', 'Method', 'Effect', or 'Result' at the end when they are part of a larger phrase.",
        "- When a Korean phrase is noun-final, rewrite it into the most natural English phrase or sentence based on context.",
        "- For multi-line bullet points, translate the whole block as one natural sentence or phrase.",
    ]

    # 다이어그램 페이지 또는 짧은 라벨이 많은 경우 추가 지침
    if is_diagram_page or has_many_short_labels:
        prompt_parts.extend([
            "",
            "## IMPORTANT - Diagram Labels (CONCISE MODE):",
            "- This page contains diagram labels and short text.",
            "- Labels MUST be translated as SHORT NOUN PHRASES (1-4 words).",
            "- Do NOT write full sentences for labels. Keep them concise.",
            "- Do NOT leave any Korean text untranslated.",
            "",
            "## Concise Translation Examples:",
            "  - '특정언어에서 다른 언어로의 번역' → 'Language Translation' (NOT 'Translation from one language to another')",
            "  - '처리할 자연어 데이터' → 'Natural Language Data'",
            "  - '숫자형태 변환' → 'Numeric Conversion'",
            "  - '의미 추출' → 'Meaning Extraction'",
            "  - '갖가지 응용' → 'Applications'",
            "  - '형태소 분석' → 'Morpheme Analysis'",
            "  - '구문 분석' → 'Syntax Analysis'",
            "  - '담화 분석' → 'Discourse Analysis'",
            "  - '자원은 제한되어 있음' → 'Limited Resources'",
            "  - '분배, 소비하는 모든 활동' → 'Distribution and Consumption'",
        ])

    prompt_parts.append("")

    # Glossary 섹션: JSON glossary + CSV term corrections
    mandatory_glossary = _extract_mandatory_glossary(glossary)

    # CSV 용어집에서 블록 텍스트에 등장하는 용어 추출
    all_source_text = " ".join(
        block.get("source_text", "") for block in blocks
    )
    csv_terms = get_terms_in_text(all_source_text)

    # CSV 용어를 mandatory glossary에 병합 (CSV가 우선)
    if csv_terms:
        if "terms" not in mandatory_glossary:
            mandatory_glossary["terms"] = {}
        mandatory_glossary["terms"].update(csv_terms)

    if mandatory_glossary:
        prompt_parts.append("## MANDATORY Glossary (must use these translations):")
        for section, items in mandatory_glossary.items():
            if items:
                prompt_parts.append(f"\n### {section}:")
                for ko, en in items.items():
                    prompt_parts.append(f"  - {ko} → {en}")
        prompt_parts.append("")

    # 블록별 프롬프트 - block["prompt_id"] 사용 (블록 생성 시 부여됨)
    prompt_parts.append("## Text Blocks:")
    prompt_parts.append("")

    for block in blocks:
        prompt_id = block.get("prompt_id")
        if not prompt_id:
            raise ValueError(f"Block missing prompt_id: {block.get('block_id')}")

        protected_text = block.get("protected_text", block.get("source_text", ""))
        token_map = block.get("token_map", {})

        # 블록 ID만 출력 (힌트 제거 - GPT가 힌트를 그대로 출력하는 문제 방지)
        prompt_parts.append(f"<{prompt_id}>")
        prompt_parts.append(protected_text)

        # 토큰 맵 힌트
        if token_map:
            prompt_parts.append(f"  TOKENS: {_format_token_map(token_map)}")

        prompt_parts.append("")

    # 출력 형식 (예시는 첫 2개 블록의 prompt_id 사용)
    prompt_parts.append("## Output Format:")
    prompt_parts.append("Return ONLY the block ID and translated text. No metadata or type labels.")
    prompt_parts.append("CRITICAL: Every block MUST have English translation. No Korean text should remain.")
    prompt_parts.append("Example:")
    if len(blocks) >= 1:
        prompt_parts.append(f"<{blocks[0].get('prompt_id')}> Introduction to the Subject")
    if len(blocks) >= 2:
        prompt_parts.append(f"<{blocks[1].get('prompt_id')}> Topics Covered in This Chapter")
    prompt_parts.append("...")

    return "\n".join(prompt_parts)


def _extract_mandatory_glossary(glossary: dict) -> dict:
    """force 정책의 glossary만 추출"""
    mandatory = {
        "proper_nouns": {},
        "organizations": {},
        "terms": {},
    }

    for section in ["proper_nouns", "organizations", "terms"]:
        for ko, entry in glossary.get(section, {}).items():
            if entry.get("policy") == "force" and entry.get("en"):
                mandatory[section][ko] = entry["en"]

    return {k: v for k, v in mandatory.items() if v}


def _format_token_map(token_map: dict) -> str:
    """토큰 맵 포맷팅"""
    items = []
    for token, info in token_map.items():
        ko = info.get("korean", "")
        en = info.get("english", "")
        items.append(f"{token}={ko}→{en}")
    return ", ".join(items)


def _is_punctuation_only_block(block: dict) -> bool:
    """블록이 구두점/기호만 포함하는지 확인 (번역 불필요)

    source_text가 한글/영문자 없이 구두점/기호/숫자/공백만 있으면
    LLM에 보내지 않고 원본 유지
    """
    source_text = block.get("source_text", "")
    if not source_text:
        return True

    # 한글 또는 영문자가 하나라도 있으면 False
    if re.search(r'[가-힣a-zA-Z]', source_text):
        return False

    return True


def _is_token_only_block(block: dict) -> bool:
    """블록이 토큰/기호/공백만 포함하는지 확인

    protected_text가 토큰(__XX_NNN__), 기호(•■○●◆-.), 공백만 포함하면
    LLM에 보내지 않고 직접 token_map으로 복원할 수 있음
    """
    protected_text = block.get("protected_text", "")
    if not protected_text:
        return False

    # 토큰 패턴 제거
    text_without_tokens = re.sub(r'__[A-Z]+_\d+__', '', protected_text)

    # 기호와 공백만 남았는지 확인
    # 허용되는 문자: 공백, bullet 기호, 구두점, 대시
    allowed_pattern = r'^[\s•■○●◆◇▪▫►▶▷△▽※★☆·\-–—\.,:;!?\(\)\[\]「」『』""\'\'\"\"]*$'

    return bool(re.match(allowed_pattern, text_without_tokens))


def _expand_token_only_block(block: dict) -> str:
    """토큰만 있는 블록을 직접 영어로 확장

    token_map의 english 값으로 토큰을 치환
    """
    protected_text = block.get("protected_text", "")
    token_map = block.get("token_map", {})

    result = protected_text
    for token, info in token_map.items():
        english = info.get("english", "")
        if english:
            result = result.replace(token, english)

    # 기호 정리 (bullet 마커 등은 유지)
    result = result.strip()

    return result


def translate_blocks_batch(
    blocks: list[dict],
    glossary: dict,
    llm_client=None,
    max_retry: int = 2,
    missing_retry: int = 1,
    chunk_size: int = 8
) -> dict:
    """블록 배치 번역 (page/chunk 단위, 누락 블록 재시도 포함)

    Args:
        blocks: 보호된 블록 리스트 (prompt_id 필수)
        glossary: 문서 glossary
        llm_client: LLM 클라이언트 (None이면 mock)
        max_retry: LLM 호출 최대 재시도 횟수
        missing_retry: 누락 블록 재시도 횟수
        chunk_size: 한 번에 번역할 최대 블록 수 (기본 8)

    Returns:
        {"raw_output": str, "translations_by_id": {prompt_id: translation}}
    """
    if not blocks:
        print("[Translation] 번역할 블록 없음")
        return {"raw_output": "", "translations_by_id": {}}

    print(f"[Translation] {len(blocks)}개 블록 번역 시작 (chunk_size={chunk_size})...")

    # === 블록 분류: punctuation-only, token-only, LLM ===
    punctuation_only_blocks = []
    token_only_blocks = []
    llm_blocks = []

    for block in blocks:
        if _is_punctuation_only_block(block):
            punctuation_only_blocks.append(block)
        elif _is_token_only_block(block):
            token_only_blocks.append(block)
        else:
            llm_blocks.append(block)

    translations_by_id = {}

    # Punctuation-only 블록: 원본 유지 (번역 불필요)
    punctuation_only_ids = []
    for block in punctuation_only_blocks:
        prompt_id = block.get("prompt_id")
        source_text = block.get("source_text", "")
        translations_by_id[prompt_id] = source_text  # 원본 유지
        punctuation_only_ids.append(prompt_id)
        block["_punctuation_only"] = True

    if punctuation_only_ids:
        print(f"[Translation] Punctuation-only 블록 스킵: {len(punctuation_only_ids)}개")
        print(f"  예시: {punctuation_only_ids[:3]}...")

    # Token-only 블록 직접 확장
    token_only_expanded = []
    for block in token_only_blocks:
        prompt_id = block.get("prompt_id")
        expanded = _expand_token_only_block(block)
        if expanded:
            translations_by_id[prompt_id] = expanded
            token_only_expanded.append(prompt_id)
            # 블록에 직접 확장 표시
            block["_token_only_expanded"] = True

    if token_only_expanded:
        print(f"[Translation] Token-only 블록 직접 확장: {len(token_only_expanded)}개")
        print(f"  예시: {token_only_expanded[:3]}...")

    if llm_client is None:
        prompt = build_translation_prompt(llm_blocks, glossary) if llm_blocks else ""
        print("[Translation] LLM 클라이언트 없음, mock 모드")
        return {
            "raw_output": "",
            "translations_by_id": translations_by_id,
            "prompt": prompt
        }

    # LLM에 보낼 블록이 없으면 token-only 결과만 반환
    if not llm_blocks:
        print("[Translation] 모든 블록이 token-only, LLM 호출 스킵")
        combined_raw_output = _rebuild_raw_output(translations_by_id)
        return {
            "raw_output": combined_raw_output,
            "translations_by_id": translations_by_id,
            "prompt": ""
        }

    # page 단위로 그룹화 (LLM 블록만)
    blocks_by_page = _group_blocks_by_page(llm_blocks)
    print(f"[Translation] 페이지별 분할: {len(blocks_by_page)}개 페이지 (LLM 대상: {len(llm_blocks)}개)")

    # translations_by_id는 이미 token-only 결과 포함
    all_prompts = []

    for page_no, page_blocks in sorted(blocks_by_page.items()):
        print(f"[Translation] 페이지 {page_no}: {len(page_blocks)}개 블록")

        # 페이지가 chunk_size보다 크면 추가 분할
        chunks = _split_into_chunks(page_blocks, chunk_size)

        for chunk_idx, chunk in enumerate(chunks):
            if len(chunks) > 1:
                print(f"  [Chunk {chunk_idx + 1}/{len(chunks)}] {len(chunk)}개 블록")

            # chunk 번역
            chunk_result = _translate_chunk(chunk, glossary, llm_client, max_retry)
            all_prompts.append(chunk_result.get("prompt", ""))

            # 결과 병합
            for prompt_id, translation in chunk_result.get("translations_by_id", {}).items():
                translations_by_id[prompt_id] = translation

    # 누락된 블록 찾기 (prompt_id 기준) - LLM 블록만 대상
    llm_prompt_ids = {block.get("prompt_id") for block in llm_blocks}
    missing_prompt_ids = llm_prompt_ids - set(translations_by_id.keys())

    for retry_attempt in range(missing_retry):
        if not missing_prompt_ids:
            break

        print(f"[Translation] 누락 블록 재시도 ({retry_attempt + 1}/{missing_retry}): {len(missing_prompt_ids)}개")

        # 누락된 블록만 추출 (LLM 블록에서만)
        missing_blocks = [b for b in llm_blocks if b.get("prompt_id") in missing_prompt_ids]

        # 재시도 프롬프트 생성 (prompt_id 사용)
        retry_prompt = _build_retry_prompt(missing_blocks, glossary)
        retry_output = _call_llm_with_retry(llm_client, retry_prompt, max_retry)

        # 재시도 결과 파싱 및 병합
        retry_translations = _parse_translations(retry_output, missing_blocks)

        for prompt_id, translation in retry_translations.items():
            if translation:
                translations_by_id[prompt_id] = translation
                print(f"[Translation] {prompt_id} 재시도 성공")

        # 아직 누락된 블록 확인
        missing_prompt_ids = llm_prompt_ids - set(translations_by_id.keys())

    final_count = len(translations_by_id)
    token_only_count = len(token_only_expanded)
    llm_success_count = final_count - token_only_count

    if missing_prompt_ids:
        print(f"[Translation] 최종: {final_count}/{len(blocks)}개 번역 완료 (token-only: {token_only_count}, LLM: {llm_success_count}), {len(missing_prompt_ids)}개 누락")
        print(f"[Translation] 누락된 prompt_id: {list(missing_prompt_ids)[:5]}...")
    else:
        print(f"[Translation] 최종: {final_count}/{len(blocks)}개 번역 완료 (token-only: {token_only_count}, LLM: {llm_success_count}) - 전체 성공")

    # raw_output 재구성 (validation에서 사용)
    combined_raw_output = _rebuild_raw_output(translations_by_id)

    return {
        "raw_output": combined_raw_output,
        "translations_by_id": translations_by_id,
        "prompt": "\n---\n".join(all_prompts)
    }


def _group_blocks_by_page(blocks: list[dict]) -> dict:
    """블록을 페이지별로 그룹화"""
    by_page = {}
    for block in blocks:
        page_no = block.get("page_no", 1)
        if page_no not in by_page:
            by_page[page_no] = []
        by_page[page_no].append(block)
    return by_page


def _split_into_chunks(blocks: list[dict], chunk_size: int) -> list[list[dict]]:
    """블록 리스트를 chunk_size 단위로 분할"""
    if chunk_size <= 0 or len(blocks) <= chunk_size:
        return [blocks]

    chunks = []
    for i in range(0, len(blocks), chunk_size):
        chunks.append(blocks[i:i + chunk_size])
    return chunks


def _translate_chunk(
    chunk: list[dict],
    glossary: dict,
    llm_client,
    max_retry: int
) -> dict:
    """단일 chunk 번역"""
    prompt = build_translation_prompt(chunk, glossary)
    raw_output = _call_llm_with_retry(llm_client, prompt, max_retry)
    translations_by_id = _parse_translations(raw_output, chunk)

    print(f"    파싱: {len(translations_by_id)}/{len(chunk)}개 추출")

    return {
        "raw_output": raw_output,
        "translations_by_id": translations_by_id,
        "prompt": prompt
    }


def _rebuild_raw_output(translations_by_id: dict) -> str:
    """translations_by_id dict를 raw_output 형식으로 재구성"""
    parts = []
    # prompt_id 정렬 (p1_b01, p1_b02, p2_b01, ...)
    for prompt_id in sorted(translations_by_id.keys()):
        translation = translations_by_id[prompt_id]
        if translation:
            parts.append(f"<{prompt_id}> {translation}")
    return "\n".join(parts)


def _call_llm_with_retry(llm_client, prompt: str, max_retry: int) -> str:
    """LLM 호출 (재시도 포함)"""
    print(f"[Translation] LLM API 호출 중... (클라이언트: {type(llm_client).__name__})")
    raw_output = ""
    for attempt in range(max_retry + 1):
        try:
            raw_output = llm_client.complete(prompt)
            print(f"[Translation] LLM 응답 수신 완료 (길이: {len(raw_output)})")
            return raw_output
        except Exception as e:
            print(f"[Translation] LLM 호출 오류 (attempt {attempt + 1}): {e}")
            import traceback
            traceback.print_exc()
            if attempt == max_retry:
                return ""
    return raw_output


def _build_retry_prompt(
    missing_blocks: list[dict],
    glossary: dict
) -> str:
    """누락 블록 재시도 프롬프트 생성 (prompt_id 사용)"""
    prompt_parts = [
        "Translate the following Korean text blocks to English.",
        "IMPORTANT: Use the EXACT block IDs provided (e.g., p1_b05, p2_b03).",
        "",
        "## Rules:",
        "1. Preserve all protected tokens exactly as they appear",
        "2. Translate each block separately, maintaining the EXACT block ID format",
        "3. If a Korean proper noun is not in the glossary, keep it in Korean",
        "4. Output ONLY the translated text. Do NOT include metadata or type labels.",
        "",
    ]

    # Glossary 섹션
    mandatory_glossary = _extract_mandatory_glossary(glossary)
    if mandatory_glossary:
        prompt_parts.append("## MANDATORY Glossary:")
        for section, items in mandatory_glossary.items():
            if items:
                for ko, en in items.items():
                    prompt_parts.append(f"  - {ko} → {en}")
        prompt_parts.append("")

    # 블록별 프롬프트 (prompt_id 사용)
    prompt_parts.append("## Text Blocks:")
    prompt_parts.append("")

    for block in missing_blocks:
        prompt_id = block.get("prompt_id")
        if not prompt_id:
            continue
        protected_text = block.get("protected_text", block.get("source_text", ""))

        prompt_parts.append(f"<{prompt_id}>")
        prompt_parts.append(protected_text)
        prompt_parts.append("")

    # 출력 형식
    prompt_parts.append("## Output Format:")
    prompt_parts.append("Return ONLY the block ID and translated text:")
    for block in missing_blocks[:3]:
        pid = block.get("prompt_id", "p?_b??")
        prompt_parts.append(f"<{pid}> [English translation]")
    if len(missing_blocks) > 3:
        prompt_parts.append("...")

    return "\n".join(prompt_parts)


def _parse_translations(raw_output: str, blocks: list[dict]) -> dict:
    """raw output에서 번역 파싱 (prompt_id 기반)

    Args:
        raw_output: LLM 응답
        blocks: 블록 리스트 (prompt_id 매핑용)

    Returns:
        {prompt_id: translation} dict
    """
    import re

    # prompt_id 패턴: <p1_b01>, <p2_b03>, <fallback_p2_572_479> 등
    # p\d+_b\d+ : 일반 블록 (p1_b01)
    # fallback_p\d+_\d+_\d+ : fallback 블록 (fallback_p2_572_479)
    prompt_id_pattern = r"p\d+_b\d+|fallback_p\d+_\d+_\d+"
    pattern_prompt_id = re.compile(rf"<({prompt_id_pattern})>\s*(.*?)(?=<(?:{prompt_id_pattern})>|$)", re.DOTALL)

    # 유효한 prompt_id 집합 생성
    valid_prompt_ids = {block.get("prompt_id") for block in blocks if block.get("prompt_id")}

    translations_by_id = {}
    invalid_ids = []

    matches = pattern_prompt_id.findall(raw_output)
    for prompt_id, translation in matches:
        translation = _clean_translation_output(translation)
        if prompt_id in valid_prompt_ids:
            # 무효 번역 체크 (???, ... 등)
            if _is_invalid_translation(translation):
                invalid_ids.append(prompt_id)
                print(f"  [Parse] {prompt_id}: 무효 번역 감지 '{translation[:30]}' → 재시도 대상")
            else:
                translations_by_id[prompt_id] = translation

    if invalid_ids:
        print(f"  [Parse] 무효 번역 {len(invalid_ids)}개 필터링됨")

    return translations_by_id


def _clean_translation_output(text: str) -> str:
    """번역 출력에서 메타데이터 및 불필요한 태그 제거"""
    import re

    text = text.strip()

    # [SHORT_LABEL] 힌트 제거 (프롬프트에서 사용된 힌트가 출력에 포함된 경우)
    text = re.sub(r"\s*\[SHORT_LABEL\]\s*", " ", text, flags=re.IGNORECASE)

    # [type: ...] 패턴 제거
    text = re.sub(r"^\s*\[type:\s*\w+\]\s*", "", text, flags=re.IGNORECASE)

    # TYPE: ... 패턴 제거 (줄 시작)
    text = re.sub(r"^TYPE:\s*\w+\s*\n?", "", text, flags=re.IGNORECASE | re.MULTILINE)

    # TOKENS: __XXX__=... 패턴 제거 (LLM이 토큰 설명을 추가한 경우)
    # 예: "TOKENS: __ORG_001__=Omission of Subject"
    text = re.sub(r"\s*TOKENS?:\s*__[A-Z]+_\d+__\s*=\s*[^\n<]+", "", text, flags=re.IGNORECASE)

    # Token= 패턴 제거 (다른 형태의 토큰 설명)
    text = re.sub(r"\s*Token[s]?:\s*[^\n<]+", "", text, flags=re.IGNORECASE)

    # 줄 끝의 토큰 설명 제거 (예: "word order __ORG_001__=xxx")
    text = re.sub(r"\s*__[A-Z]+_\d+__\s*=\s*[^\n<]+", "", text)

    # HTML/LaTeX 스타일 태그 제거 (예: <math>, </math>, <br>, <p> 등)
    # <tag>content</tag> → content
    text = re.sub(r"</?(?:math|br|p|span|div|em|strong|b|i|sup|sub)[^>]*>", "", text, flags=re.IGNORECASE)

    # 자체 닫힘 태그 제거 (예: <br/>, <hr/>)
    text = re.sub(r"<[a-zA-Z]+\s*/?\s*>", "", text)

    return text.strip()


def _is_invalid_translation(text: str) -> bool:
    """무효한 번역인지 확인 (재시도 필요)

    무효 케이스:
    - "???" 또는 "??" 등 물음표만 있는 경우
    - "..." 또는 ".." 등 마침표만 있는 경우
    - "[untranslatable]", "[unknown]" 등 메타 텍스트
    - 빈 문자열 또는 공백만
    - 영문자/숫자가 전혀 없는 경우 (기호만)
    """
    import re

    if not text or not text.strip():
        return True

    text = text.strip()

    # 물음표/마침표만 있는 경우
    if re.match(r'^[\?\.\!\s]+$', text):
        return True

    # 메타 텍스트 패턴
    invalid_patterns = [
        r'^\[.*\]$',  # [anything]
        r'^untranslat',  # untranslatable, untranslated
        r'^unknown$',
        r'^n/?a$',
        r'^\?+$',
        r'^\.+$',
    ]
    for pattern in invalid_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return True

    # 영문자나 숫자가 전혀 없으면 무효 (기호/구두점만)
    if not re.search(r'[A-Za-z0-9가-힣]', text):
        return True

    return False


def _find_visual_predecessor(
    fragment_block: dict,
    same_page_blocks: list[dict],
    aggressive: bool = False
) -> dict | None:
    """OCR fragment의 visual predecessor 찾기 (bbox 기반)

    fragment 바로 위에 있고, 미완성 문장으로 끝나는 블록을 찾음

    Args:
        aggressive: forbidden_pattern 등 반드시 병합이 필요한 경우 True
                    → threshold를 낮추고 더 넓은 범위에서 검색
    """
    import re

    frag_bbox = fragment_block.get("union_bbox") or fragment_block.get("bbox")
    if not frag_bbox:
        return None

    frag_top = frag_bbox[1]
    frag_left = frag_bbox[0]

    best_pred = None
    best_score = 0

    # aggressive 모드에서는 더 넓은 범위로 검색
    max_y_gap = 150 if aggressive else 100

    for block in same_page_blocks:
        if block is fragment_block:
            continue

        pred_bbox = block.get("union_bbox") or block.get("bbox")
        if not pred_bbox:
            continue

        pred_bottom = pred_bbox[3]
        pred_left = pred_bbox[0]
        pred_text = block.get("source_text", "").strip()

        # 조건 1: fragment보다 위에 있어야 함
        y_gap = frag_top - pred_bottom
        if y_gap < -20:  # predecessor가 아래에 있음
            continue
        if y_gap > max_y_gap:  # 너무 멀리 있음
            continue

        score = 0

        # Y gap 점수 (가까울수록 높음)
        if y_gap <= 20:
            score += 5
        elif y_gap <= 40:
            score += 3
        elif y_gap <= 60:
            score += 2
        elif aggressive and y_gap <= 100:
            score += 1  # aggressive 모드에서 약간 멀어도 점수 부여

        # X 위치 점수 (비슷한 컬럼)
        x_diff = abs(frag_left - pred_left)
        if x_diff <= 80:
            score += 3
        elif x_diff <= 150:
            score += 1

        # 미완성 문장 점수 (한국어 조사로 끝남)
        if pred_text.endswith(("에", "를", "을", "의", "와", "과", "에서", "으로", "로")):
            score += 4
        elif pred_text.endswith((",", "，")):
            score += 3
        elif pred_text.endswith(")"):
            # 괄호로 끝나는 경우 (어원 설명 등)
            score += 2

        # bullet으로 시작하면 가산
        if pred_text and pred_text[0] in "■●▶•☐◦○□※★☆-":
            score += 2

        if score > best_score:
            best_score = score
            best_pred = block

    # threshold: aggressive 모드에서는 5점, 일반 모드에서는 8점
    threshold = 5 if aggressive else 8
    if best_pred and best_score >= threshold:
        return best_pred

    return None


def _is_ocr_fragment_for_retry(text: str) -> bool:
    """재번역 시 OCR fragment 판단 (단독 번역 불가 케이스)

    "직 면", "희 소 성" 같은 공백으로 분리된 한글 조각
    또는 1~3자 한글 단독 텍스트
    """
    import re
    if not text:
        return False

    stripped = text.strip()
    if not stripped:
        return False

    no_space = stripped.replace(" ", "")

    # 조건 1: 한글 1글자들이 공백으로 분리 ("직 면", "희 소 성")
    if re.match(r'^[가-힣](\s+[가-힣])+$', stripped):
        return True

    # 조건 2: 1~3자 한글만 있는 경우
    if len(no_space) <= 3 and re.match(r'^[가-힣]+$', no_space):
        return True

    return False


def retry_semantic_mismatch_blocks(
    mismatch_blocks: list[dict],
    all_blocks: list[dict],
    glossary: dict,
    llm_client=None,
    max_retry: int = 1
) -> tuple[dict, dict]:
    """semantic mismatch 블록 재번역 (주변 컨텍스트 포함)

    특별 처리:
    - OCR fragment는 predecessor와 병합해서 재번역
      예: "직 면" → "■ 본문 텍스트가 이어지다가 다음 줄로 직면"
    - forbidden_pattern도 predecessor와 병합해서 재번역
      예: "그리스어에서 유래" + "'oiko nomos'..." → "Derived from the Greek..."

    Args:
        mismatch_blocks: 재번역할 블록 리스트 (_has_forbidden_pattern 플래그 포함)
        all_blocks: 전체 블록 리스트 (컨텍스트용)
        glossary: 문서 glossary
        llm_client: LLM 클라이언트
        max_retry: LLM 호출 재시도 횟수

    Returns:
        tuple: (
            {prompt_id: translation} dict,
            {prompt_id: {"_merged_into": str, "_skip_render": bool}} dict
        )
    """
    if not mismatch_blocks or llm_client is None:
        return {}, {}

    print(f"[SemanticRetry] {len(mismatch_blocks)}개 semantic mismatch 블록 재번역...")

    # 블록을 prompt_id로 빠르게 찾기 위한 dict
    blocks_by_id = {b.get("prompt_id"): b for b in all_blocks if b.get("prompt_id")}

    retried_translations = {}
    merged_info = {}  # {prompt_id: {"_merged_into": str, "_skip_render": bool}}

    for block in mismatch_blocks:
        prompt_id = block.get("prompt_id")
        if not prompt_id:
            continue

        source_text = block.get("source_text", "")
        has_forbidden_pattern = block.get("_has_forbidden_pattern", False)

        # 주변 블록 컨텍스트 수집 (같은 페이지의 이전/다음 2개씩)
        page_no = block.get("page_no", 1)
        same_page_blocks = [b for b in all_blocks if b.get("page_no") == page_no]
        same_page_blocks.sort(key=lambda b: b.get("prompt_id", ""))

        # 현재 블록 인덱스 찾기
        block_idx = -1
        for i, b in enumerate(same_page_blocks):
            if b.get("prompt_id") == prompt_id:
                block_idx = i
                break

        # OCR fragment 또는 forbidden_pattern인 경우 처리
        is_ocr_fragment = _is_ocr_fragment_for_retry(source_text)

        # dangling noun은 병합이 아닌 재번역으로 처리
        forbidden_descriptions = block.get("_forbidden_pattern_descriptions", [])
        is_dangling_noun = any(
            "dangling" in desc.lower() or "incomplete" in desc.lower()
            for desc in forbidden_descriptions
        )

        # 병합이 필요한 패턴: OCR fragment, 직면 오역 등 (dangling noun 제외)
        needs_merge = is_ocr_fragment or (has_forbidden_pattern and not is_dangling_noun)

        # dangling noun: 특별 재번역 프롬프트로 처리
        if is_dangling_noun:
            current_translation = block.get("translated_text_raw", "")
            print(f"  [DanglingRetry] {prompt_id}: dangling noun 감지")
            print(f"    before='{current_translation[:60]}...'")
            print(f"    forbidden_descriptions={forbidden_descriptions}")

            prompt = _build_dangling_noun_retry_prompt(block, glossary)
            raw_output = _call_llm_with_retry(llm_client, prompt, max_retry)
            translation = raw_output.strip() if raw_output else ""

            if translation:
                # 재번역 결과에서도 dangling noun이 있는지 재검증
                dangling_pattern = r'\b\w+\s+(research|study|method|result|analysis|examination)[.\s]*$'
                still_has_dangling = bool(re.search(dangling_pattern, translation.lower()))

                print(f"    after='{translation[:60]}...'")
                print(f"    still_has_dangling={still_has_dangling}")

                if still_has_dangling:
                    # retry 후에도 dangling noun이 남아있으면 실패로 마킹
                    print(f"    → FAILED: dangling noun still exists, not applying")
                    # retried_translations에 추가하지 않음 → 원본 유지, failed 상태
                else:
                    retried_translations[prompt_id] = translation
                    print(f"    → SUCCESS: applied_to_retried_translations=True")
            else:
                print(f"    → FAILED: empty translation from LLM")
            continue

        if needs_merge:
            # Visual predecessor 찾기: bbox 기반으로 바로 위에 있는 블록
            # forbidden_pattern은 aggressive 모드로 더 넓게 검색
            visual_pred = _find_visual_predecessor(
                block, same_page_blocks, aggressive=has_forbidden_pattern
            )

            if visual_pred:
                pred_text = visual_pred.get("source_text", "")
                # OCR fragment ("직 면" → "직면"): 공백 제거
                # forbidden_pattern ("그리스어에서 유래"): 그대로 + 구분자
                if is_ocr_fragment:
                    fragment_text = source_text.replace(" ", "")
                    merged_text = pred_text + fragment_text
                else:
                    # forbidden_pattern: 자연스러운 연결 (줄바꿈 또는 쉼표)
                    merged_text = pred_text + ", " + source_text

                merge_type = "OCR fragment" if is_ocr_fragment else "forbidden_pattern"
                print(f"  [SemanticRetry] {merge_type} 병합: '{pred_text[:20]}...' + '{source_text}' → '...{merged_text[-25:]}'")

                # 병합된 텍스트로 재번역
                prompt = _build_merged_fragment_retry_prompt(merged_text, glossary)
                raw_output = _call_llm_with_retry(llm_client, prompt, max_retry)
                translation = raw_output.strip() if raw_output else ""

                if translation:
                    pred_prompt_id = visual_pred.get("prompt_id")
                    if pred_prompt_id:
                        retried_translations[pred_prompt_id] = translation
                        print(f"  [SemanticRetry] {pred_prompt_id}: 병합 재번역 성공 → '{translation[:30]}...'")

                        # predecessor의 bbox 확장 정보 저장
                        pred_bbox = visual_pred.get("union_bbox") or visual_pred.get("bbox")
                        frag_bbox = block.get("union_bbox") or block.get("bbox")
                        if pred_bbox and frag_bbox:
                            expanded_bbox = [
                                min(pred_bbox[0], frag_bbox[0]),  # x_min
                                min(pred_bbox[1], frag_bbox[1]),  # y_min
                                max(pred_bbox[2], frag_bbox[2]),  # x_max
                                max(pred_bbox[3], frag_bbox[3]),  # y_max
                            ]
                            # predecessor에 적용할 확장된 bbox 정보
                            if pred_prompt_id not in merged_info:
                                merged_info[pred_prompt_id] = {}
                            merged_info[pred_prompt_id]["_expanded_bbox"] = expanded_bbox
                            print(f"  [SemanticRetry] {pred_prompt_id}: bbox 확장됨 {pred_bbox} → {expanded_bbox}")

                    # fragment는 "(merged)" 마커로 처리 (빈 문자열은 validation 실패)
                    retried_translations[prompt_id] = "(merged)"
                    # merged_info에 플래그 저장 (원본 블록에 적용하기 위해)
                    merged_info[prompt_id] = {
                        "_merged_into": pred_prompt_id,
                        "_skip_render": True
                    }
                    print(f"  [SemanticRetry] {prompt_id}: predecessor에 병합됨")
                else:
                    print(f"  [SemanticRetry] {prompt_id}: 병합 재번역 실패")
                continue
            else:
                print(f"  [SemanticRetry] {prompt_id}: visual predecessor 없음, 일반 재번역 시도")

        # 일반 블록: 컨텍스트 기반 재번역
        context_before = same_page_blocks[max(0, block_idx - 2):block_idx]
        context_after = same_page_blocks[block_idx + 1:block_idx + 3]

        prompt = _build_context_retry_prompt(block, context_before, context_after, glossary)
        raw_output = _call_llm_with_retry(llm_client, prompt, max_retry)

        # 결과 파싱 (단일 블록)
        translations = _parse_translations(raw_output, [block])
        if prompt_id in translations and translations[prompt_id]:
            retried_translations[prompt_id] = translations[prompt_id]
            print(f"  [SemanticRetry] {prompt_id}: 재번역 성공")
        else:
            print(f"  [SemanticRetry] {prompt_id}: 재번역 실패")

    print(f"[SemanticRetry] {len(retried_translations)}/{len(mismatch_blocks)}개 재번역 완료")
    return retried_translations, merged_info


def retry_residual_korean_blocks(
    korean_blocks: list[dict],
    glossary: dict,
    llm_client=None,
    max_retry: int = 1
) -> dict:
    """잔여 한글(korean_remained_unexpected)이 있는 블록 재번역

    Args:
        korean_blocks: 잔여 한글이 있는 블록 리스트
            - _residual_korean: 남아있는 한글 텍스트 리스트
            - _current_translation: 현재 번역 결과
        glossary: 문서 glossary
        llm_client: LLM 클라이언트
        max_retry: LLM 호출 재시도 횟수

    Returns:
        {prompt_id: translation} dict
    """
    if not korean_blocks or llm_client is None:
        return {}

    print(f"[ResidualKoreanRetry] {len(korean_blocks)}개 잔여 한글 블록 재번역...")

    retried_translations = {}

    for block in korean_blocks:
        prompt_id = block.get("prompt_id")
        if not prompt_id:
            continue

        source_text = block.get("source_text", "")
        current_translation = block.get("_current_translation", "")
        residual_korean = block.get("_residual_korean", [])

        if not current_translation or not residual_korean:
            print(f"  [ResidualKoreanRetry] {prompt_id}: 데이터 부족, 스킵")
            continue

        # 잔여 한글을 명시적으로 번역하도록 프롬프트 생성
        prompt = _build_residual_korean_retry_prompt(
            source_text, current_translation, residual_korean, glossary
        )

        raw_output = _call_llm_with_retry(llm_client, prompt, max_retry)
        translation = raw_output.strip() if raw_output else ""

        if translation and translation != current_translation:
            # 새 번역에서도 잔여 한글이 있는지 간단히 체크
            import re
            remaining = re.findall(r'[가-힣]{2,}', translation)
            if len(remaining) < len(residual_korean):
                retried_translations[prompt_id] = translation
                print(f"  [ResidualKoreanRetry] {prompt_id}: 재번역 성공 (잔여 한글 {len(residual_korean)} → {len(remaining)})")
            else:
                # 개선 안됐으면 그래도 사용 (다른 품질은 더 좋을 수 있음)
                retried_translations[prompt_id] = translation
                print(f"  [ResidualKoreanRetry] {prompt_id}: 재번역 완료 (잔여 한글 미개선)")
        else:
            print(f"  [ResidualKoreanRetry] {prompt_id}: 재번역 실패 또는 동일")

    print(f"[ResidualKoreanRetry] {len(retried_translations)}/{len(korean_blocks)}개 재번역 완료")
    return retried_translations


def _build_residual_korean_retry_prompt(
    source_text: str,
    current_translation: str,
    residual_korean: list[str],
    glossary: dict
) -> str:
    """잔여 한글 재번역 프롬프트"""
    prompt_parts = [
        "Fix the following translation that still contains untranslated Korean text.",
        "",
        "## Original Korean:",
        source_text,
        "",
        "## Current Translation (has untranslated Korean):",
        current_translation,
        "",
        "## Untranslated Korean words that MUST be translated:",
    ]

    for korean in residual_korean:
        prompt_parts.append(f"  - {korean}")

    prompt_parts.extend([
        "",
        "## Rules:",
        "- Translate ALL the Korean words listed above to English",
        "- Keep the rest of the translation intact",
        "- Do NOT add explanations or metadata",
        "- Output ONLY the corrected English translation",
        "- Even short phrases like '분배' (distribution), '소비' (consumption) must be translated",
    ])

    # Glossary 추가
    if glossary:
        terms = glossary.get("terms", {})
        if terms:
            prompt_parts.append("")
            prompt_parts.append("## Glossary (use these translations if applicable):")
            for ko, entry in list(terms.items())[:15]:
                en = entry.get("en", "")
                if en:
                    prompt_parts.append(f"  - {ko} → {en}")

    prompt_parts.extend([
        "",
        "## Corrected Translation:"
    ])

    return "\n".join(prompt_parts)


def retry_token_error_blocks(
    token_error_blocks: list[dict],
    glossary: dict,
    llm_client=None,
    max_retry: int = 1
) -> dict:
    """토큰 누락(token_missing)이 있는 블록 재번역

    Args:
        token_error_blocks: 토큰 누락이 있는 블록 리스트
            - _missing_tokens: [{token, expected_en}, ...]
            - _current_translation: 현재 번역 결과
        glossary: 문서 glossary
        llm_client: LLM 클라이언트
        max_retry: LLM 호출 재시도 횟수

    Returns:
        {prompt_id: translation} dict
    """
    if not token_error_blocks or llm_client is None:
        return {}

    print(f"[TokenErrorRetry] {len(token_error_blocks)}개 토큰 누락 블록 재번역...")

    retried_translations = {}

    for block in token_error_blocks:
        prompt_id = block.get("prompt_id")
        if not prompt_id:
            continue

        source_text = block.get("source_text", "")
        protected_text = block.get("protected_text", "")
        current_translation = block.get("_current_translation", "")
        missing_tokens = block.get("_missing_tokens", [])

        if not missing_tokens:
            print(f"  [TokenErrorRetry] {prompt_id}: 누락 토큰 정보 없음, 스킵")
            continue

        # 토큰 retry 프롬프트 생성
        prompt = _build_token_error_retry_prompt(
            source_text, protected_text, current_translation, missing_tokens, glossary
        )

        raw_output = _call_llm_with_retry(llm_client, prompt, max_retry)
        translation = raw_output.strip() if raw_output else ""

        if translation:
            # 자동 보정 시도: source가 토큰으로 시작하면 번역도 expected_en으로 시작해야 함
            translation = _auto_correct_token_start(
                translation, source_text, protected_text, missing_tokens
            )

            # 누락 토큰이 expected_en으로 포함되었는지 확인
            all_tokens_present = True
            for token_info in missing_tokens:
                expected_en = token_info.get("expected_en", "")
                if expected_en and expected_en.lower() not in translation.lower():
                    all_tokens_present = False
                    break

            if all_tokens_present:
                retried_translations[prompt_id] = translation
                print(f"  [TokenErrorRetry] {prompt_id}: 재번역 성공 (모든 토큰 포함)")
            else:
                # 토큰이 여전히 누락되면 강제 삽입 시도
                corrected = _force_insert_missing_tokens(
                    translation, source_text, protected_text, missing_tokens
                )
                if corrected != translation:
                    retried_translations[prompt_id] = corrected
                    print(f"  [TokenErrorRetry] {prompt_id}: 강제 보정 적용")
                else:
                    # 그래도 안 되면 원본 유지 (실패 상태)
                    print(f"  [TokenErrorRetry] {prompt_id}: 재번역 실패 (토큰 여전히 누락)")
        else:
            print(f"  [TokenErrorRetry] {prompt_id}: LLM 응답 없음")

    print(f"[TokenErrorRetry] {len(retried_translations)}/{len(token_error_blocks)}개 재번역 완료")
    return retried_translations


def _build_token_error_retry_prompt(
    source_text: str,
    protected_text: str,
    current_translation: str,
    missing_tokens: list[dict],
    glossary: dict
) -> str:
    """토큰 누락 재번역 프롬프트"""
    prompt_parts = [
        "Fix the following translation that is MISSING required terms.",
        "",
        "## Original Korean:",
        source_text,
        "",
        "## Protected Text (with tokens):",
        protected_text,
        "",
        "## Current Translation (MISSING required terms):",
        current_translation if current_translation else "(empty)",
        "",
        "## MISSING TERMS - You MUST include these in the translation:",
    ]

    for token_info in missing_tokens:
        token = token_info.get("token", "")
        expected_en = token_info.get("expected_en", "")
        if expected_en:
            prompt_parts.append(f"  - {token} → \"{expected_en}\" (REQUIRED)")
        else:
            prompt_parts.append(f"  - {token} (REQUIRED)")

    prompt_parts.extend([
        "",
        "## Rules:",
        "- You MUST include ALL the terms listed above in your translation",
        "- If the original starts with a term, your translation MUST start with that term's English",
        "- Keep the meaning and structure of the original",
        "- Do NOT add explanations or metadata",
        "- Output ONLY the corrected English translation",
        "",
        "## Corrected Translation (MUST include all required terms):"
    ])

    return "\n".join(prompt_parts)


def _auto_correct_token_start(
    translation: str,
    source_text: str,
    protected_text: str,
    missing_tokens: list[dict]
) -> str:
    """source가 토큰으로 시작하면 번역도 expected_en으로 시작하도록 보정"""
    if not translation or not missing_tokens:
        return translation

    # protected_text가 토큰으로 시작하는지 확인
    for token_info in missing_tokens:
        token = token_info.get("token", "")
        expected_en = token_info.get("expected_en", "")

        if not token or not expected_en:
            continue

        # protected_text가 이 토큰으로 시작하는지 확인
        if protected_text.strip().startswith(token):
            # 번역이 expected_en으로 시작하지 않으면 추가
            if not translation.lower().startswith(expected_en.lower()):
                # 쉼표나 콜론 뒤에 나머지 번역 붙이기
                if translation and translation[0].isupper():
                    translation = expected_en + ", " + translation[0].lower() + translation[1:]
                else:
                    translation = expected_en + ", " + translation
                print(f"    [AutoCorrect] 번역 시작 부분 보정: {expected_en}")
            break

    return translation


def _force_insert_missing_tokens(
    translation: str,
    source_text: str,
    protected_text: str,
    missing_tokens: list[dict]
) -> str:
    """누락된 토큰의 expected_en을 강제로 삽입"""
    if not translation:
        return translation

    for token_info in missing_tokens:
        token = token_info.get("token", "")
        expected_en = token_info.get("expected_en", "")

        if not expected_en:
            continue

        # 이미 포함되어 있으면 스킵
        if expected_en.lower() in translation.lower():
            continue

        # protected_text에서 토큰 위치 확인
        if protected_text.strip().startswith(token):
            # 문장 시작에 삽입
            if translation and translation[0].isupper():
                translation = expected_en + ", " + translation[0].lower() + translation[1:]
            else:
                translation = expected_en + ", " + translation
        else:
            # 문장 끝에 삽입 (괄호 안)
            translation = translation.rstrip(".") + f" ({expected_en})."

    return translation


def _build_merged_fragment_retry_prompt(merged_text: str, glossary: dict) -> str:
    """OCR fragment 병합 재번역 프롬프트"""
    prompt_parts = [
        "Translate the following Korean text to English.",
        "This text was split by OCR but should be one continuous phrase.",
        "",
        "## Text to translate:",
        merged_text,
        "",
        "## Rules:",
        "- Output ONLY the English translation",
        "- Do NOT include any metadata or explanation",
    ]

    # glossary가 있으면 추가
    if glossary:
        terms = glossary.get("terms", {})
        if terms:
            prompt_parts.append("")
            prompt_parts.append("## Glossary (use these translations):")
            for ko, entry in list(terms.items())[:10]:
                en = entry.get("en", "")
                if en:
                    prompt_parts.append(f"- {ko} → {en}")

    return "\n".join(prompt_parts)


def _build_dangling_noun_retry_prompt(block: dict, glossary: dict) -> str:
    """dangling final noun 재번역 프롬프트

    번역 끝에 'workers Research', 'spending Study' 같이
    뜬금없는 명사가 붙은 경우 자연스러운 문장으로 재작성
    """
    source_text = block.get("source_text", "")
    current_translation = block.get("translated_text_raw", "")

    prompt_parts = [
        "The previous translation left a dangling final noun that makes the sentence unnatural.",
        "Rewrite the ENTIRE block as one fluent English sentence.",
        "",
        "## Problem:",
        "The translation ends with an isolated noun that is not properly integrated into the sentence.",
        "This often happens when translating Korean noun-final academic or descriptive phrases.",
        "",
        "## Source Korean text:",
        source_text,
        "",
        "## Previous translation (has issues):",
        current_translation,
        "",
        "## Instructions:",
        "- Translate the source text as ONE coherent English sentence or phrase.",
        "- Restructure noun-final phrases into natural English word order.",
        "- Do NOT leave dangling nouns at the end.",
        "- Do NOT split the idea into multiple fragments.",
        "- Output ONLY the corrected English translation.",
        "",
        "## Corrected Translation:",
    ]

    # glossary가 있으면 추가
    if glossary:
        terms = glossary.get("terms", {})
        if terms:
            prompt_parts.insert(-2, "")
            prompt_parts.insert(-2, "## Glossary (use these translations):")
            for ko, entry in list(terms.items())[:8]:
                en = entry.get("en", "")
                if en:
                    prompt_parts.insert(-2, f"- {ko} → {en}")

    return "\n".join(prompt_parts)


def _build_context_retry_prompt(
    block: dict,
    context_before: list[dict],
    context_after: list[dict],
    glossary: dict
) -> str:
    """컨텍스트 포함 재번역 프롬프트 생성"""
    prompt_parts = [
        "Translate the following Korean text to English.",
        "Use the surrounding context to ensure accurate translation.",
        "",
        "## Rules:",
        "1. Preserve all protected tokens exactly as they appear",
        "2. Output ONLY the translated text, no metadata",
        "3. If a Korean proper noun is not in the glossary, keep it in Korean",
        "4. Match the meaning with the surrounding context",
        "",
    ]

    # Glossary
    mandatory_glossary = _extract_mandatory_glossary(glossary)
    if mandatory_glossary:
        prompt_parts.append("## MANDATORY Glossary:")
        for section, items in mandatory_glossary.items():
            if items:
                for ko, en in items.items():
                    prompt_parts.append(f"  - {ko} → {en}")
        prompt_parts.append("")

    # Context before
    if context_before:
        prompt_parts.append("## Context (preceding text):")
        for ctx in context_before:
            src = ctx.get("source_text", "")[:60]
            en = ctx.get("translated_text_raw", "")[:60]
            prompt_parts.append(f"  - KO: {src}")
            if en:
                prompt_parts.append(f"    EN: {en}")
        prompt_parts.append("")

    # Target block
    prompt_id = block.get("prompt_id")
    protected_text = block.get("protected_text", block.get("source_text", ""))
    token_map = block.get("token_map", {})

    prompt_parts.append("## Text to Translate:")
    prompt_parts.append(f"<{prompt_id}>")
    prompt_parts.append(protected_text)
    if token_map:
        prompt_parts.append(f"  TOKENS: {_format_token_map(token_map)}")
    prompt_parts.append("")

    # Context after
    if context_after:
        prompt_parts.append("## Context (following text):")
        for ctx in context_after:
            src = ctx.get("source_text", "")[:60]
            prompt_parts.append(f"  - KO: {src}")
        prompt_parts.append("")

    # Output format
    prompt_parts.append("## Output Format:")
    prompt_parts.append(f"<{prompt_id}> [English translation]")

    return "\n".join(prompt_parts)


def apply_translations_to_blocks(
    blocks: list[dict],
    translations_by_id: dict,
    raw_output: str
) -> list[dict]:
    """번역 결과를 블록에 적용 (prompt_id 기반)

    Args:
        blocks: 블록 리스트
        translations_by_id: {prompt_id: translation} dict
        raw_output: LLM raw output (저장용)

    Returns:
        번역이 적용된 블록 리스트
    """
    for block in blocks:
        prompt_id = block.get("prompt_id")
        if prompt_id and prompt_id in translations_by_id:
            block["model_raw_output"] = raw_output
            block["translated_text_raw"] = translations_by_id[prompt_id]
        # else: 기존 값 유지 (retry 시 다른 블록의 번역을 덮어쓰지 않음)

    return blocks


def save_translated_blocks(blocks: list[dict], output_path: str):
    """번역된 블록 저장"""
    import json

    blocks_for_save = []
    for block in blocks:
        block_copy = {k: v for k, v in block.items() if k != "regions"}
        blocks_for_save.append(block_copy)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "blocks": blocks_for_save,
            "count": len(blocks)
        }, f, ensure_ascii=False, indent=2)
