"""
Block Translation Validation

번역 결과 검증 및 후처리

입력:
- blocks.translated.json
- glossary.generated.json

출력:
- blocks.final.json
- quality_report.json

검증 항목:
1. token preservation (missing/extra/duplicate/order)
2. glossary compliance
3. Korean remained
4. empty translation
"""
import re
from typing import Optional
from .token_protection import (
    recover_broken_tokens,
    validate_token_preservation,
    restore_tokens,
)


# BLOCKING_ISSUES 정의 (이 이슈가 있으면 블록 번역 실패)
BLOCKING_ISSUES = {
    "block_count_mismatch",
    "block_id_mismatch",
    "empty_translation",
    "token_missing",
    "token_duplicate",
    "token_order_changed",
    "glossary_violation",  # force policy only
    "korean_remained_unexpected",
    # "semantic_mismatch",  # 경고만 표시, 실패 처리 안 함
    # "glossary_recommendation",  # recommended policy - warning only, not blocking
}

# 핵심 키워드 매핑 (semantic mismatch 검증용)
# 한글 키워드 → 영어 키워드 리스트
SEMANTIC_KEYWORD_MAP = {
    # 일반 학술/비즈니스 용어
    "경제": ["economy", "economic", "economics"],
    "기업": ["firm", "company", "business", "enterprise", "corporation"],
    "생산": ["produce", "production", "manufacture", "output"],
    "노동": ["labor", "work", "employment"],
    "노동자": ["worker", "employee", "labor"],
    "고용": ["employ", "hire", "employment", "job"],
    "성장": ["growth", "grow", "increase"],
    "실업": ["unemploy", "jobless"],
    "인플레이션": ["inflation", "inflationary"],
    "이자": ["interest", "rate"],
    "환율": ["exchange", "currency"],
    "정부": ["government", "state", "public"],
    "시장": ["market"],
    "가격": ["price", "cost"],
    "수요": ["demand"],
    "공급": ["supply"],
    "소비": ["consume", "consumption", "spend"],
    "저축": ["save", "saving"],
    "투자": ["invest", "investment"],
    "무역": ["trade", "export", "import"],
    "세금": ["tax"],
    "예산": ["budget"],
    "통화": ["monetary", "currency", "money"],
    "은행": ["bank"],
    "자원": ["resource"],
    "희소": ["scarce", "scarcity"],
    "선택": ["choice", "choose", "decide"],
    "결정": ["decide", "decision", "determine"],
    "연구": ["study", "research"],
    # 일반 용어
    "사람": ["people", "person", "human"],
    "방법": ["method", "way", "how"],
    "문제": ["problem", "issue", "question"],
    "원리": ["principle", "theory"],
}


def is_validation_ok(issues: list) -> bool:
    """BLOCKING_ISSUES 기준으로 ok 판정

    특별 처리:
    - semantic_mismatch + forbidden_pattern: blocking (OCR fragment 오역)
    """
    for issue in issues:
        issue_type = issue.get("type", "")

        # BLOCKING_ISSUES에 있는 타입
        if issue_type in BLOCKING_ISSUES:
            return False

        # semantic_mismatch 중 forbidden_pattern만 blocking
        if issue_type == "semantic_mismatch" and issue.get("reason") == "forbidden_pattern":
            return False

    return True


def _filter_valid_token_expansions(
    token_issues: list,
    translation: str,
    token_map: dict,
    protected_text: str
) -> list:
    """토큰 누락 이슈 중 유효한 확장을 필터링

    Case 1: protected_text가 토큰만으로 이루어진 경우 (예: "__TERM_001__"),
            LLM이 토큰 대신 glossary 번역을 직접 출력했다면 유효한 번역으로 처리

    Case 2: protected_text에 토큰과 다른 텍스트가 섞인 경우,
            누락된 토큰의 영어 번역이 출력에 포함되어 있으면 유효한 번역으로 처리

    예시:
        Case 1:
            protected_text: "__TERM_001__"
            token_map: {"__TERM_001__": {"korean": "용어명", "english": "term"}}
            translation: "term"
            → token_missing 이슈 제거

        Case 2:
            protected_text: "■ __TERM_001__(resource)이 부족하다는 점"
            token_map: {"__TERM_001__": {"korean": "한글용어", "english": "resource"}}
            translation: "■ The point that resources are limited"
            → "resource"가 "resources"로 포함되어 있으므로 유효

    Args:
        token_issues: validate_token_preservation에서 반환된 이슈 리스트
        translation: LLM 번역 결과
        token_map: 토큰 → {korean, english} 매핑
        protected_text: 토큰으로 보호된 원문

    Returns:
        필터링된 이슈 리스트
    """
    if not token_issues:
        return token_issues

    # token_missing 이슈 찾기
    missing_issue = None
    other_issues = []
    for issue in token_issues:
        if issue.get("type") == "token_missing":
            missing_issue = issue
        else:
            other_issues.append(issue)

    if not missing_issue:
        return token_issues

    missing_tokens = missing_issue.get("tokens", [])
    translation_lower = translation.lower().strip()

    # 모든 missing 토큰에 대해 glossary 번역이 출력에 있는지 확인
    valid_tokens = []
    invalid_tokens = []

    for token in missing_tokens:
        if token not in token_map:
            invalid_tokens.append(token)
            continue

        token_entry = token_map[token]
        # token_map의 키가 "english"/"korean" 또는 "en"/"ko"일 수 있음
        expected_en = token_entry.get("english", token_entry.get("en", "")).lower().strip()

        if not expected_en:
            invalid_tokens.append(token)
            continue

        # 번역이 expected_en을 포함하는지 확인 (복수형, 동사형 등 허용)
        # 예: "resource" → "resources", "economy" → "economic"
        is_valid = _check_token_expansion_valid(expected_en, translation_lower)

        if is_valid:
            valid_tokens.append(token)
        else:
            invalid_tokens.append(token)

    # 모든 토큰이 유효하게 확장되었으면 missing 이슈 제거
    if not invalid_tokens:
        return other_issues

    # 일부만 유효한 경우: 남은 invalid 토큰만 이슈에 포함
    if valid_tokens:
        missing_issue["tokens"] = invalid_tokens
        return [missing_issue] + other_issues

    return token_issues


def _check_token_expansion_valid(expected_en: str, translation_lower: str) -> bool:
    """토큰 확장이 유효한지 확인

    Args:
        expected_en: 토큰의 예상 영어 번역 (소문자)
        translation_lower: 번역 결과 (소문자)

    Returns:
        유효 여부
    """
    # 직접 포함
    if expected_en in translation_lower:
        return True

    # 번역이 expected_en을 포함 (반대 방향)
    if translation_lower in expected_en:
        return True

    # 핵심 단어 기반 매칭 (복수형, 동사형 등 허용)
    expected_words = expected_en.split()

    for word in expected_words:
        if len(word) < 3:
            continue

        # 단어의 stem(기본형)이 포함되어 있는지 확인
        # 예: "resource" → "resourc" → matches "resources"
        stem = word[:min(len(word), 6)]  # 앞 6글자까지만 비교
        if stem in translation_lower:
            return True

        # 복수형 체크: word + "s" 또는 word + "es"
        if word + "s" in translation_lower or word + "es" in translation_lower:
            return True

    # 긴 번역의 경우 핵심 단어 50% 이상 포함 확인
    if len(expected_words) > 2:
        match_count = 0
        for word in expected_words:
            if len(word) >= 3:
                stem = word[:min(len(word), 5)]
                if stem in translation_lower:
                    match_count += 1
        if match_count >= len(expected_words) / 2:
            return True

    return False


def validate_semantic_match(source_text: str, english_text: str, block: dict = None) -> list:
    """source와 english의 의미적 일치 검증

    source에 있는 핵심 키워드가 english에도 적절히 번역되어 있는지 확인.

    Args:
        source_text: 원본 한글 텍스트
        english_text: 번역된 영어 텍스트
        block: 블록 정보 (region_count, page_type 등)

    Returns:
        semantic_mismatch issue 목록
    """
    issues = []

    if not source_text or not english_text:
        return issues

    source_lower = source_text.lower()
    english_lower = english_text.lower()

    # block 메타데이터 추출
    region_count = block.get("region_count", 1) if block else 1
    source_len = len(source_text)
    is_merged_block = region_count >= 2 or source_len > 50

    # 0. OCR fragment 오역 금지 패턴 체크
    # 짧은 한글 fragment가 엉뚱하게 번역된 경우의 대표 패턴
    forbidden_patterns = [
        (r'\bdirect\s+(face|aspect|side)\b', "직면/측면 OCR 오역", "error"),
        # "어원 설명 fragment": 짧은 단독 번역만 탐지 (30자 이하이고 끝에 있을 때)
        (r'^.{0,25}(originating|derived)\s+from\s+greek\s*\.?\s*$', "어원 설명 fragment", "error"),
        (r'^and\s+(spend|work|save)\s*\.?\s*$', "연결어만 남은 fragment", "error"),
        # 불완전한 절로 끝나는 경우 (how to determine spending, what to buy,)
        (r'\bhow\s+to\s+determine\s+\w+\s*,?\s*$', "incomplete how-to clause", "error"),
    ]
    for pattern, reason, severity in forbidden_patterns:
        if re.search(pattern, english_lower):
            issues.append({
                "type": "semantic_mismatch",
                "reason": "forbidden_pattern",
                "pattern": pattern,
                "description": reason,
                "severity": severity,
                "retryable": True,
            })
            print(f"  [SemanticCheck] 금지 패턴 발견: {reason} in '{english_text[:30]}'")

    # 1. dangling final noun 체크 (컨텍스트 기반)
    # "workers Research", "spending Study" 패턴 - 앞 단어와 공백으로 붙어있음
    # 단, "case study", "regression analysis" 같은 정상 표현은 제외
    # 마침표/공백 등 trailing 문자 허용
    dangling_pattern = r'\b\w+\s+(research|study|method|result|analysis|examination)[.\s]*$'
    dangling_match = re.search(dangling_pattern, english_lower)

    # 디버깅: potential dangling noun이 있을 수 있는 경우만 로그
    block_id = block.get("prompt_id", "unknown") if block else "unknown"
    has_academic_noun = bool(re.search(r'\b(research|study|method|result|analysis|examination)\b', english_lower))

    if has_academic_noun:
        print(f"  [DanglingCheck] block_id={block_id}")
        print(f"    source_text={source_text[:50]}...")
        print(f"    translation={english_text[-60:]}...")
        print(f"    region_count={region_count}, source_len={source_len}, is_merged_block={is_merged_block}")
        print(f"    pattern_match={dangling_match is not None}, english_end='{english_text[-30:]}'")

    if dangling_match:
        # 정상 표현 예외 처리
        normal_phrases = [
            r'\bcase\s+study\b', r'\bfeasibility\s+study\b', r'\bpilot\s+study\b',
            r'\bregression\s+analysis\b', r'\bdata\s+analysis\b', r'\bstatistical\s+analysis\b',
            r'\bscientific\s+method\b', r'\bresearch\s+method\b',
            r'\bexpected\s+result\b', r'\bfinal\s+result\b',
        ]
        is_normal_phrase = any(re.search(p, english_lower) for p in normal_phrases)
        print(f"    is_normal_phrase={is_normal_phrase}")

        if not is_normal_phrase:
            # merged block이면 error (재번역 필요), 아니면 review (경고만)
            if is_merged_block:
                issues.append({
                    "type": "semantic_mismatch",
                    "reason": "forbidden_pattern",
                    "pattern": dangling_pattern,
                    "description": "dangling final noun",
                    "severity": "error",
                    "retryable": True,
                })
                print(f"    → DETECTED: dangling noun (merged block), severity=error, retryable=True")
            else:
                issues.append({
                    "type": "semantic_mismatch",
                    "reason": "review_needed",
                    "pattern": dangling_pattern,
                    "description": "possible dangling final noun",
                    "severity": "warning",
                    "retryable": False,
                })
                print(f"    → DETECTED: dangling noun (single block), severity=warning, retryable=False")

    # source에서 키워드 찾기
    found_keywords = []
    missing_translations = []

    for korean, english_options in SEMANTIC_KEYWORD_MAP.items():
        if korean in source_lower:
            found_keywords.append(korean)
            # english에 해당 번역이 있는지 확인
            has_translation = any(en in english_lower for en in english_options)
            if not has_translation:
                missing_translations.append({
                    "korean": korean,
                    "expected_english": english_options[:3]
                })

    # 3개 이상 키워드 중 절반 이상 누락이면 mismatch
    if len(found_keywords) >= 3 and len(missing_translations) >= len(found_keywords) * 0.5:
        issues.append({
            "type": "semantic_mismatch",
            "found_keywords": found_keywords,
            "missing_translations": missing_translations[:5],
            "severity": "warning",
            "retryable": True,
        })
        print(f"  [SemanticCheck] {len(missing_translations)}/{len(found_keywords)} 키워드 불일치")

    # 길이 비율 체크 (한글 → 영어는 보통 1:2~1:4 정도)
    # source가 길고 english가 너무 짧으면 의심
    source_len = len(source_text.strip())
    english_len = len(english_text.strip())

    if source_len > 20 and english_len > 0:
        ratio = english_len / source_len
        if ratio < 0.5:  # 영어가 한글의 절반 이하면 의심
            issues.append({
                "type": "semantic_mismatch",
                "reason": "length_ratio_too_low",
                "source_len": source_len,
                "english_len": english_len,
                "ratio": round(ratio, 2),
                "severity": "warning",
                "retryable": True,
            })
            print(f"  [SemanticCheck] 길이 비율 의심: {source_len} → {english_len} (ratio={ratio:.2f})")

    return issues


def validate_and_restore_single_block(
    translation: str,
    block: dict,
    token_map: dict,
    selected_glossary: dict,
    glossary: dict
) -> dict:
    """단일 block 검증 및 복구

    Args:
        translation: 해당 block의 번역 결과
        block: Translation Block
        token_map: 토큰 → 원문/영문 매핑
        selected_glossary: 이 block에 선택된 glossary
        glossary: 문서 전체 glossary (uncertain, common_words 등 포함)

    Returns:
        검증 결과 dict
    """
    issues = []

    # 특수 케이스: "(merged)" 마커 → predecessor에 병합된 OCR fragment
    if translation == "(merged)" or block.get("_merged_into"):
        return {
            "restored_output": "(merged into predecessor)",
            "issues": [],
            "token_recovered_count": 0,
            "ok": True,  # 병합된 블록은 성공으로 처리
            "_merged": True,
        }

    # 특수 케이스: token-only block 직접 확장
    # translation.py에서 LLM 없이 직접 token_map으로 확장됨
    if block.get("_token_only_expanded"):
        # 이미 token이 영어로 확장된 상태이므로 token restore 불필요
        restored_output = translation.strip()
        return {
            "restored_output": restored_output,
            "issues": [],
            "token_recovered_count": 0,
            "ok": True,
            "_token_only_expanded": True,
        }

    # 특수 케이스: 구두점/기호만 있는 블록 (번역 불필요)
    # 예: source_text = """ 또는 "•" 등
    source_text = block.get("source_text", "")
    if _is_punctuation_only(source_text):
        # 구두점만 있는 블록은 번역 없이 성공으로 처리
        return {
            "restored_output": source_text,  # 원본 유지
            "issues": [],
            "token_recovered_count": 0,
            "ok": True,
            "_punctuation_only": True,
        }

    # 1. token 깨짐 복구 먼저
    translation, token_recovered_count = recover_broken_tokens(translation, token_map)

    # 2. token preservation 검증
    token_issues = validate_token_preservation(
        block.get("protected_text", ""),
        translation,
        token_map,
        block.get("token_order", [])
    )

    # 2b. 토큰 누락 예외 처리: protected_text가 토큰만으로 이루어진 경우
    # LLM이 토큰 대신 glossary 번역을 직접 출력한 경우 유효한 번역으로 처리
    token_issues = _filter_valid_token_expansions(
        token_issues, translation, token_map, block.get("protected_text", "")
    )

    issues.extend(token_issues)

    # 3. token restore
    restored_output = restore_tokens(translation, token_map)

    # 4. glossary compliance 검증 (restore 후에!)
    glossary_issues = validate_glossary_compliance(
        restored_output,
        selected_glossary
    )
    issues.extend(glossary_issues)

    # 5. Korean remained 검증
    korean_issues = validate_korean_remained(
        restored_output,
        block,
        glossary
    )
    issues.extend(korean_issues)

    # 6. semantic mismatch 검증 (source와 english 의미 일치)
    source_text = block.get("source_text", "")
    semantic_issues = validate_semantic_match(source_text, restored_output, block)
    issues.extend(semantic_issues)

    # 7. empty translation 검증
    if not restored_output.strip():
        issues.append({"type": "empty_translation"})

    return {
        "restored_output": restored_output,
        "issues": issues,
        "token_recovered_count": token_recovered_count,
        "ok": is_validation_ok(issues)
    }


def validate_glossary_compliance(
    restored_output: str,
    selected_glossary: dict
) -> list:
    """glossary 준수 여부 검증 (token restore 후에 호출)

    Policy별 검증:
    - force: exact match 필수 → error (blocking)
    - recommended: aliases 허용, semantic 유사 허용 → warning (non-blocking)
    - suggest: 검증 없음 (skip)

    Args:
        restored_output: token이 영어로 복원된 번역 결과
        selected_glossary: 이 block에 선택된 glossary

    Returns:
        glossary_violation issue 목록
    """
    issues = []

    # proper_nouns, organizations, terms 모두 검사
    sections_to_check = [
        ("proper_nouns", "person"),
        ("organizations", "organization"),
        ("terms", "term"),
    ]

    output_lower = restored_output.lower()

    for section_name, entry_type in sections_to_check:
        section = selected_glossary.get(section_name, {})

        for ko, entry in section.items():
            expected_en = entry.get("en", "")
            policy = entry.get("policy", "force")

            # suggest 정책은 검사 안 함
            if policy == "suggest":
                continue

            if not expected_en:
                continue

            # 1. exact match 확인
            if expected_en.lower() in output_lower:
                continue  # OK

            # 2. aliases 확인 (recommended용)
            aliases = entry.get("aliases", [])
            alias_found = any(alias.lower() in output_lower for alias in aliases)
            if alias_found:
                continue  # OK (alias matched)

            # 3. semantic equivalence 확인
            # force: 90% threshold (더 엄격), recommended: 80% threshold
            if policy == "force":
                if _is_semantically_equivalent(expected_en, restored_output, threshold=0.9):
                    continue  # OK (semantic match, strict)
            elif policy == "recommended":
                if _is_semantically_equivalent(expected_en, restored_output, threshold=0.8):
                    continue  # OK (semantic match)

            # 4. bad_translations 목록에서 찾기
            bad_found = None
            for bad in entry.get("bad_translations", []):
                if bad.lower() in output_lower:
                    bad_found = bad
                    break

            # 5. policy에 따라 issue 타입 결정
            if policy == "force":
                issues.append({
                    "type": "glossary_violation",
                    "korean": ko,
                    "expected_english": expected_en,
                    "entry_type": entry_type,
                    "bad_found": bad_found,
                    "retryable": True,
                    "severity": "error"
                })
            elif policy == "recommended":
                issues.append({
                    "type": "glossary_recommendation",
                    "korean": ko,
                    "expected_english": expected_en,
                    "entry_type": entry_type,
                    "bad_found": bad_found,
                    "retryable": False,  # warning이므로 재시도 불필요
                    "severity": "warning"
                })

    return issues


def _is_punctuation_only(text: str) -> bool:
    """텍스트가 구두점/기호/공백만 포함하는지 확인

    예: '"', '•', '...', '—', '「」' 등

    Returns:
        구두점/기호만 있으면 True
    """
    if not text:
        return True

    # 허용되는 문자: 구두점, 기호, 공백, 숫자
    # 한글, 영문자가 있으면 False
    import re

    # 한글 또는 영문자가 하나라도 있으면 False
    if re.search(r'[가-힣a-zA-Z]', text):
        return False

    return True


def _is_semantically_equivalent(expected: str, output: str, threshold: float = 0.8) -> bool:
    """두 표현이 의미상 동등한지 확인

    예:
    - "Chinese character-based language" ≈ "language based on Chinese characters"
    - "Natural Language Processing" ≈ "processing of natural language"
    - "subject omission" ≈ "Omission of the subject"

    Args:
        expected: glossary에 정의된 영어 번역
        output: 실제 번역 결과
        threshold: 일치율 임계값 (기본 0.8 = 80%)

    Returns:
        의미상 동등하면 True
    """
    # 핵심 단어 추출 (소문자, 불용어 제거)
    stopwords = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by'}

    def extract_keywords(text: str) -> set:
        words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
        return {w for w in words if w not in stopwords and len(w) > 2}

    expected_keywords = extract_keywords(expected)
    output_keywords = extract_keywords(output)

    if not expected_keywords:
        return False

    # 핵심 단어의 threshold% 이상이 output에 있으면 의미상 동등
    match_count = len(expected_keywords & output_keywords)
    match_ratio = match_count / len(expected_keywords)

    return match_ratio >= threshold


def validate_korean_remained(
    english_text: str,
    block: dict,
    glossary: dict
) -> list:
    """한글 잔존 검증 (허용 조건 세분화)

    Args:
        english_text: 번역 결과 (token restore 후)
        block: Translation Block
        glossary: 문서 전체 glossary (uncertain, common_words 등 포함)
    """
    korean_pattern = re.compile(r"[가-힣]+")
    found_korean = korean_pattern.findall(english_text)

    if not found_korean:
        return []

    issues = []
    block_type = block.get("block_type", "paragraph")

    # 허용 타입
    allowed_types = {"code", "formula", "url", "footer", "copyright"}

    for korean in found_korean:
        classification = classify_korean_residual(korean, block_type, glossary)

        if classification == "allowed":
            # 허용된 한글 (unlisted proper noun 등)
            continue
        elif classification == "uncertain":
            # 불확실 → review_required
            issues.append({
                "type": "korean_remained_review",
                "korean": korean,
                "reason": "uncertain_glossary"
            })
        else:
            # 비허용
            if block_type in allowed_types:
                continue

            issues.append({
                "type": "korean_remained_unexpected",
                "korean": korean,
                "block_type": block_type
            })

    return issues


def classify_korean_residual(
    korean: str,
    block_type: str,
    glossary: dict
) -> str:
    """한글 잔존 분류

    Returns:
        "allowed" | "uncertain" | "unexpected"
    """
    # 1. uncertain glossary에 있으면 허용 (review_required)
    if korean in glossary.get("uncertain", {}):
        return "uncertain"

    # 2. common_words에 있으면 비허용 (번역해야 함)
    if korean in glossary.get("common_words", {}):
        return "unexpected"

    # 3. 2-4글자 한글이고 사람 이름 패턴이면 허용 (unlisted proper noun)
    if 2 <= len(korean) <= 4 and looks_like_proper_noun(korean):
        return "allowed"

    # 4. 나머지는 비허용
    return "unexpected"


def looks_like_proper_noun(korean: str) -> bool:
    """한글이 고유명사처럼 보이는지 (간단한 휴리스틱)"""
    # 성씨 패턴 체크 (김, 이, 박, 최, 정 등)
    common_surnames = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"]
    if korean and korean[0] in common_surnames:
        return True

    return False


def validate_batch_output(
    raw_output: str,
    blocks: list[dict],
    document_glossary: dict
) -> dict:
    """batch 번역 결과 검증 (prompt_id 기반)

    Args:
        raw_output: LLM raw output
        blocks: blocks.protected.json의 블록 리스트 (prompt_id 필수)
        document_glossary: 문서 전체 glossary
    """
    issues = []
    expected_count = len(blocks)

    # 1. prompt_id 기반 번역 추출
    translations_by_id = _extract_translations_by_prompt_id(raw_output, blocks)
    parsed_count = len(translations_by_id)
    print(f"[Validation] prompt_id 기반 파싱: {parsed_count}/{expected_count}개 추출")

    # 2. 누락된 prompt_id 찾기
    # 단, _punctuation_only 또는 _token_only_expanded 플래그가 있는 블록은 제외
    all_prompt_ids = {
        block.get("prompt_id") for block in blocks
        if block.get("prompt_id") and
           not block.get("_punctuation_only") and
           not block.get("_token_only_expanded")
    }
    missing_prompt_ids = all_prompt_ids - set(translations_by_id.keys())

    if missing_prompt_ids:
        issues.append({
            "type": "block_count_mismatch",
            "expected": expected_count,
            "found": parsed_count,
            "missing_count": len(missing_prompt_ids),
            "missing_prompt_ids": list(missing_prompt_ids)[:10],
            "severity": "critical",
            "retryable": True,
        })
        print(f"[Validation] 번역 누락: {list(missing_prompt_ids)[:5]}...")

    # 3. 각 block 검증 (prompt_id 기반 매핑)
    results = []
    for block in blocks:
        prompt_id = block.get("prompt_id")

        # 해당 prompt_id의 번역 찾기
        # 우선순위: 1) block의 translated_text_raw (retry 결과) 2) raw_output에서 추출
        # retry 후에는 translated_text_raw가 최신 값이므로 우선 사용
        if block.get("translated_text_raw"):
            translation = block.get("translated_text_raw")
        elif prompt_id and prompt_id in translations_by_id:
            translation = translations_by_id[prompt_id]
        else:
            # 번역 누락 - 빈 번역으로 처리하고 실패 마킹
            translation = ""
            issues.append({
                "type": "translation_missing",
                "prompt_id": prompt_id,
                "block_text": block.get("source_text", "")[:50],
                "retryable": True,
            })

        result = validate_and_restore_single_block(
            translation,
            block,
            block.get("token_map", {}),
            block.get("selected_glossary", {}),
            document_glossary
        )

        # 번역 누락된 경우 강제 실패
        # 예외: translated_text_raw가 있거나, _punctuation_only 또는 _token_only_expanded 플래그가 있으면 OK
        has_translation = (
            (prompt_id and prompt_id in translations_by_id) or
            block.get("translated_text_raw") or
            block.get("_punctuation_only") or
            block.get("_token_only_expanded")
        )
        if not has_translation:
            result["ok"] = False
            result["issues"].append({"type": "translation_missing", "prompt_id": prompt_id})

        # prompt_id 저장 (finalize에서 사용)
        result["prompt_id"] = prompt_id
        results.append(result)

    # 전체 ok 판정
    has_missing = len(missing_prompt_ids) > 0
    all_individual_ok = all(r["ok"] for r in results)
    overall_ok = all_individual_ok and not has_missing

    return {"ok": overall_ok, "issues": issues, "results": results}


def _extract_translations_by_prompt_id(raw_output: str, blocks: list[dict]) -> dict:
    """raw_output에서 prompt_id 기반 번역 추출

    Returns:
        {prompt_id: translation} dict
    """
    # prompt_id 패턴: <p1_b01>, <p2_b03>, <fallback_p2_572_479> 등
    # p\d+_b\d+ : 일반 블록 (p1_b01)
    # fallback_p\d+_\d+_\d+ : fallback 블록 (fallback_p2_572_479)
    prompt_id_pattern = r"p\d+_b\d+|fallback_p\d+_\d+_\d+"
    pattern = re.compile(rf"<({prompt_id_pattern})>\s*(.*?)(?=<(?:{prompt_id_pattern})>|$)", re.DOTALL)

    # 유효한 prompt_id 집합
    valid_prompt_ids = {block.get("prompt_id") for block in blocks if block.get("prompt_id")}

    translations_by_id = {}
    matches = pattern.findall(raw_output)

    for prompt_id, translation in matches:
        translation = translation.strip()
        # [type: ...] 패턴 제거
        translation = re.sub(r"^\s*\[type:\s*\w+\]\s*", "", translation, flags=re.IGNORECASE)
        translation = translation.strip()

        if prompt_id in valid_prompt_ids:
            translations_by_id[prompt_id] = translation

    return translations_by_id


def generate_quality_report(
    blocks: list[dict],
    validation_results: list[dict]
) -> dict:
    """품질 리포트 생성

    failed_by_reason 분류:
    - residual_korean: 번역 후 한글이 남아있음
    - forbidden_pattern: 금지 패턴 탐지 (OCR 오역)
    - semantic_mismatch: 의미 불일치
    - missing_translation: 번역 누락
    - empty_translation: 빈 번역
    - token_error: 토큰 보존 실패
    - glossary_violation: glossary 위반
    """
    metrics = {
        "korean_remained_count": 0,
        "korean_remained_allowed_count": 0,
        "glossary_violation_count": 0,  # force policy 위반 (blocking)
        "glossary_recommendation_count": 0,  # recommended policy 미준수 (warning)
        "token_preservation_failure": 0,
        "token_recovered_count": 0,
        "token_missing_count": 0,
        "token_duplicate_count": 0,
        "token_order_changed_count": 0,
        "token_expanded_count": 0,  # 토큰이 영어로 확장됨 (valid)
        "empty_translation_count": 0,
        "review_required_count": 0,
        "total_blocks": len(blocks),
        "blocks_ok": 0,
        "blocks_failed": 0,
    }

    # failed_by_reason: 실패 원인별 통계
    failed_by_reason = {
        "residual_korean": 0,
        "forbidden_pattern": 0,
        "semantic_mismatch": 0,
        "missing_translation": 0,
        "empty_translation": 0,
        "token_error": 0,
        "glossary_violation": 0,
    }

    # failed_blocks: 실패 블록 상세 정보
    failed_blocks = []

    for result in validation_results:
        if result["ok"]:
            metrics["blocks_ok"] += 1
        else:
            metrics["blocks_failed"] += 1

            # 실패 원인 분류 (첫 번째 blocking issue 기준)
            failure_reason = _classify_failure_reason(result.get("issues", []))
            if failure_reason:
                failed_by_reason[failure_reason] += 1

            # 실패 블록 상세 정보
            failed_blocks.append({
                "prompt_id": result.get("prompt_id", ""),
                "failure_reason": failure_reason,
                "issues": result.get("issues", []),
            })

        metrics["token_recovered_count"] += result.get("token_recovered_count", 0)

        for issue in result.get("issues", []):
            issue_type = issue.get("type", "")

            if issue_type == "token_missing":
                metrics["token_missing_count"] += len(issue.get("tokens", []))
                metrics["token_preservation_failure"] += 1
            elif issue_type == "token_duplicate":
                metrics["token_duplicate_count"] += len(issue.get("tokens", []))
            elif issue_type == "token_order_changed":
                metrics["token_order_changed_count"] += 1
            elif issue_type == "glossary_violation":
                metrics["glossary_violation_count"] += 1
            elif issue_type == "glossary_recommendation":
                metrics["glossary_recommendation_count"] += 1
            elif issue_type == "korean_remained_unexpected":
                metrics["korean_remained_count"] += 1
            elif issue_type == "korean_remained_review":
                metrics["korean_remained_allowed_count"] += 1
            elif issue_type == "empty_translation":
                metrics["empty_translation_count"] += 1
            elif issue_type == "token_expanded":
                metrics["token_expanded_count"] += 1

    for block in blocks:
        if block.get("review_required"):
            metrics["review_required_count"] += 1

    metrics["failed_by_reason"] = failed_by_reason
    metrics["failed_blocks"] = failed_blocks

    return metrics


def _classify_failure_reason(issues: list) -> str:
    """실패 원인 분류 (첫 번째 blocking issue 기준)

    우선순위:
    1. forbidden_pattern (semantic_mismatch with forbidden_pattern)
    2. residual_korean (korean_remained_unexpected)
    3. missing_translation / empty_translation
    4. token_error (token_missing, token_duplicate, token_order_changed)
    5. glossary_violation
    6. semantic_mismatch (일반)
    """
    # 1. forbidden_pattern 체크
    for issue in issues:
        if issue.get("type") == "semantic_mismatch" and issue.get("reason") == "forbidden_pattern":
            return "forbidden_pattern"

    # 2. residual_korean 체크
    for issue in issues:
        if issue.get("type") == "korean_remained_unexpected":
            return "residual_korean"

    # 3. missing/empty 체크
    for issue in issues:
        if issue.get("type") == "translation_missing":
            return "missing_translation"
        if issue.get("type") == "empty_translation":
            return "empty_translation"

    # 4. token_error 체크
    for issue in issues:
        if issue.get("type") in ("token_missing", "token_duplicate", "token_order_changed"):
            return "token_error"

    # 5. glossary_violation 체크
    for issue in issues:
        if issue.get("type") == "glossary_violation":
            return "glossary_violation"

    # 6. 일반 semantic_mismatch
    for issue in issues:
        if issue.get("type") == "semantic_mismatch":
            return "semantic_mismatch"

    return "unknown"


def finalize_blocks(
    blocks: list[dict],
    validation_results: list[dict]
) -> list[dict]:
    """검증 결과로 블록 최종화 (prompt_id 기반)"""
    # validation_results를 prompt_id로 매핑
    results_by_id = {}
    for result in validation_results:
        prompt_id = result.get("prompt_id")
        if prompt_id:
            results_by_id[prompt_id] = result

    for block in blocks:
        prompt_id = block.get("prompt_id")

        if prompt_id and prompt_id in results_by_id:
            result = results_by_id[prompt_id]
            english = result.get("restored_output", "")
            block["english"] = english
            block["translation_available"] = result["ok"]
            block["validation_issues"] = result.get("issues", [])
            block["token_recovered_count"] = result.get("token_recovered_count", 0)

            # 디버그 로그: source/english 매핑 확인
            source_text = block.get("source_text", "")[:30]
            english_text = english[:30] if english else "(empty)"
            print(f"[MapCheck] {prompt_id}: '{source_text}...' → '{english_text}...'")

            if not result["ok"]:
                block["review_required"] = True
                block["review_reason"] = _summarize_issues(result.get("issues", []))
        else:
            # prompt_id가 없거나 결과가 없는 경우
            block["english"] = ""
            block["translation_available"] = False
            block["review_required"] = True
            block["review_reason"] = "missing_prompt_id_or_result"
            print(f"[MapCheck] WARNING: {prompt_id} not found in results")

    return blocks


def _summarize_issues(issues: list) -> str:
    """issue 목록 요약"""
    types = [i.get("type", "") for i in issues]
    return ", ".join(set(types))


def extract_semantic_mismatch_blocks(
    blocks: list[dict],
    validation_results: list[dict]
) -> list[dict]:
    """semantic_mismatch 이슈가 있는 블록 추출 (재번역용)

    Args:
        blocks: 원본 블록 리스트
        validation_results: 검증 결과 리스트

    Returns:
        semantic_mismatch 이슈가 있는 블록 리스트
    """
    # validation_results를 prompt_id로 매핑
    results_by_id = {}
    for result in validation_results:
        prompt_id = result.get("prompt_id")
        if prompt_id:
            results_by_id[prompt_id] = result

    mismatch_blocks = []
    for block in blocks:
        prompt_id = block.get("prompt_id")
        if not prompt_id or prompt_id not in results_by_id:
            continue

        result = results_by_id[prompt_id]
        issues = result.get("issues", [])

        # semantic_mismatch 이슈가 있고 retryable인 경우만
        semantic_issues = [
            issue for issue in issues
            if issue.get("type") == "semantic_mismatch" and issue.get("retryable", False)
        ]

        if semantic_issues:
            # 블록에 mismatch 이유 정보 추가 (retry에서 사용)
            block_copy = block.copy()
            block_copy["_mismatch_reasons"] = [
                issue.get("reason") for issue in semantic_issues
            ]
            # forbidden_pattern 여부 플래그 및 설명
            forbidden_issues = [
                issue for issue in semantic_issues
                if issue.get("reason") == "forbidden_pattern"
            ]
            block_copy["_has_forbidden_pattern"] = len(forbidden_issues) > 0
            # forbidden pattern의 종류 저장 (dangling noun vs OCR fragment 구분용)
            if forbidden_issues:
                block_copy["_forbidden_pattern_descriptions"] = [
                    issue.get("description", "") for issue in forbidden_issues
                ]
            mismatch_blocks.append(block_copy)

            # 디버깅 로그
            print(f"  [ExtractMismatch] {prompt_id}: semantic_issues={len(semantic_issues)}")
            print(f"    reasons={block_copy['_mismatch_reasons']}")
            print(f"    has_forbidden_pattern={block_copy['_has_forbidden_pattern']}")
            if forbidden_issues:
                print(f"    forbidden_descriptions={block_copy['_forbidden_pattern_descriptions']}")

    print(f"[ExtractMismatch] Total: {len(mismatch_blocks)} blocks extracted for retry")
    return mismatch_blocks


def extract_residual_korean_blocks(
    blocks: list[dict],
    validation_results: list[dict]
) -> list[dict]:
    """korean_remained_unexpected 이슈가 있는 블록 추출 (재번역용)

    Args:
        blocks: 원본 블록 리스트
        validation_results: 검증 결과 리스트

    Returns:
        한글 잔존 이슈가 있는 블록 리스트
    """
    # validation_results를 prompt_id로 매핑
    results_by_id = {}
    for result in validation_results:
        prompt_id = result.get("prompt_id")
        if prompt_id:
            results_by_id[prompt_id] = result

    korean_blocks = []
    for block in blocks:
        prompt_id = block.get("prompt_id")
        if not prompt_id or prompt_id not in results_by_id:
            continue

        result = results_by_id[prompt_id]
        issues = result.get("issues", [])

        # korean_remained_unexpected 이슈 추출
        korean_issues = [
            issue for issue in issues
            if issue.get("type") == "korean_remained_unexpected"
        ]

        if korean_issues:
            # 블록에 잔존 한글 정보 추가
            block_copy = block.copy()
            block_copy["_residual_korean"] = [
                issue.get("korean", "") for issue in korean_issues
            ]
            block_copy["_current_translation"] = result.get("restored_output", "")
            korean_blocks.append(block_copy)

    return korean_blocks


def extract_token_error_blocks(
    blocks: list[dict],
    validation_results: list[dict]
) -> list[dict]:
    """token_missing 이슈가 있는 블록 추출 (재번역용)

    Args:
        blocks: 원본 블록 리스트
        validation_results: 검증 결과 리스트

    Returns:
        토큰 누락 이슈가 있는 블록 리스트
    """
    # validation_results를 prompt_id로 매핑
    results_by_id = {}
    for result in validation_results:
        prompt_id = result.get("prompt_id")
        if prompt_id:
            results_by_id[prompt_id] = result

    token_error_blocks = []
    for block in blocks:
        prompt_id = block.get("prompt_id")
        if not prompt_id or prompt_id not in results_by_id:
            continue

        result = results_by_id[prompt_id]
        issues = result.get("issues", [])

        # token_missing 이슈 추출
        token_issues = [
            issue for issue in issues
            if issue.get("type") == "token_missing"
        ]

        if token_issues:
            # 블록에 누락 토큰 정보 추가
            block_copy = block.copy()

            # 누락된 토큰과 expected English 수집
            missing_tokens = []
            for issue in token_issues:
                tokens = issue.get("tokens", [])
                for token in tokens:
                    # token_map에서 expected English 찾기
                    token_map = block.get("token_map", {})
                    expected_en = token_map.get(token, {}).get("en", "")
                    missing_tokens.append({
                        "token": token,
                        "expected_en": expected_en
                    })

            block_copy["_missing_tokens"] = missing_tokens
            block_copy["_current_translation"] = result.get("restored_output", "")
            token_error_blocks.append(block_copy)

    print(f"[ExtractTokenError] {len(token_error_blocks)}개 토큰 누락 블록 추출")
    return token_error_blocks


def save_final_blocks(blocks: list[dict], output_path: str):
    """최종 블록 저장"""
    import json

    # regions 제거한 버전 저장
    blocks_for_save = []
    for block in blocks:
        block_copy = {k: v for k, v in block.items() if k != "regions"}
        blocks_for_save.append(block_copy)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "blocks": blocks_for_save,
            "count": len(blocks)
        }, f, ensure_ascii=False, indent=2)


def save_quality_report(report: dict, output_path: str):
    """품질 리포트 저장"""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
