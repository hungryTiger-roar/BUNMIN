"""
Glossary Token Protection

블록별 glossary 선택 및 토큰 보호

입력:
- blocks.json
- glossary.generated.json

출력:
- blocks.protected.json

핵심 로직:
- select_glossary_for_block: 블록에 등장하는 glossary 선택
- protect_glossary_tokens: 토큰으로 치환
- 3단계 매칭 (exact, normalized, fuzzy)
"""
import re
import copy
import unicodedata
from typing import Optional
from .config import cfg


# 토큰 템플릿
PROPER_NOUN_TOKEN = "__PN_{:03d}__"
ORG_TOKEN = "__ORG_{:03d}__"
TERM_TOKEN = "__TERM_{:03d}__"

# 토큰 복구용 정규식 (tolerant)
TOKEN_RE = re.compile(r"_{0,2}(PN|ORG|TERM)[_\- ]?0*([0-9]{1,3})_{0,2}")


def select_glossary_for_block(source_text: str, glossary: dict) -> dict:
    """해당 block에 등장하는 glossary 선택

    common_words 원칙:
    1. common_words는 prompt의 MANDATORY glossary에 넣지 않음
    2. common_words는 force/protect 대상 아님 (토큰 보호 안 함)
    3. common_words는 Korean remained validation에서만 사용
    """
    selected = {
        "proper_nouns": {},
        "organizations": {},
        "terms": {},
        "common_words": {}  # validation reference only
    }

    normalized_source = normalize_for_match(source_text)

    # 섹션별 처리 (fuzzy 허용 여부 다름)
    section_configs = [
        ("proper_nouns", True),    # fuzzy 허용
        ("organizations", True),    # fuzzy 허용
        ("terms", False),           # fuzzy 금지
        ("common_words", False),    # fuzzy 금지
    ]

    for section_name, allow_fuzzy in section_configs:
        section = glossary.get(section_name, {})

        # 긴 key 우선 정렬
        sorted_entries = sorted(
            section.items(),
            key=lambda x: max(
                len(x[0]),
                max((len(v) for v in x[1].get("variants", [])), default=0)
            ),
            reverse=True
        )

        for ko, entry in sorted_entries:
            match_result = match_glossary_entry(
                source_text, normalized_source, ko, entry, allow_fuzzy=allow_fuzzy
            )

            if match_result["matched"]:
                # deepcopy로 원본 glossary 오염 방지
                add_selected_entry(selected[section_name], ko, entry, match_result)

    return selected


def normalize_for_match(text: str) -> str:
    """매칭용 정규화 (공백/기호 제거)"""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", "", text)
    return text


def match_glossary_entry(
    source_text: str,
    normalized_source: str,
    ko: str,
    entry: dict,
    allow_fuzzy: bool = True
) -> dict:
    """glossary entry 매칭 (3단계)"""
    # 매칭 대상 forms
    forms = [ko] + entry.get("variants", [])

    for form in forms:
        # 1. exact match
        if form in source_text:
            return {"matched": True, "method": "exact", "form": form}

        # 2. normalized match
        normalized_form = normalize_for_match(form)
        if normalized_form in normalized_source:
            return {"matched": True, "method": "normalized", "form": form}

    # 3. fuzzy match (allow_fuzzy가 True일 때만)
    if allow_fuzzy:
        fuzzy_result = fuzzy_match(source_text, ko, entry)
        if fuzzy_result["matched"]:
            return fuzzy_result

    return {"matched": False}


def fuzzy_match(source_text: str, ko: str, entry: dict) -> dict:
    """fuzzy 매칭 (length-based threshold)"""
    # 길이에 따른 threshold
    ko_len = len(ko)
    if ko_len <= 3:
        threshold = cfg("glossary.fuzzy_threshold_short", 0.90)
    elif ko_len <= 5:
        threshold = cfg("glossary.fuzzy_threshold_medium", 0.85)
    else:
        threshold = cfg("glossary.fuzzy_threshold_long", 0.80)

    # 소스에서 유사한 부분 찾기
    for i in range(len(source_text) - ko_len + 1):
        candidate = source_text[i:i + ko_len]
        similarity = calculate_similarity(ko, candidate)
        if similarity >= threshold:
            return {
                "matched": True,
                "method": "fuzzy",
                "form": ko,
                "fuzzy_candidate": candidate,
                "similarity": similarity
            }

    return {"matched": False}


def calculate_similarity(s1: str, s2: str) -> float:
    """두 문자열의 유사도 (Levenshtein 기반)"""
    if len(s1) == 0 or len(s2) == 0:
        return 0.0

    # 간단한 edit distance 기반 유사도
    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    return 1.0 - (distance / max_len)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Levenshtein 거리 계산"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def add_selected_entry(
    selected_section: dict,
    ko: str,
    entry: dict,
    match_result: dict
):
    """선택된 glossary entry 추가"""
    entry_copy = copy.deepcopy(entry)
    entry_copy["_match_info"] = match_result
    selected_section[ko] = entry_copy


def protect_glossary_tokens(
    text: str,
    selected_glossary: dict
) -> tuple[str, dict, list]:
    """glossary 토큰 보호 (token_order 저장)

    Returns:
        (protected_text, token_map, token_order)
    """
    token_map = {}
    counters = {"proper_nouns": 1, "organizations": 1, "terms": 1}

    # 섹션별 토큰 prefix와 처리 순서
    sections = [
        ("proper_nouns", PROPER_NOUN_TOKEN, "proper_noun"),
        ("organizations", ORG_TOKEN, "organization"),
        ("terms", TERM_TOKEN, "term"),
    ]

    for section_name, token_template, token_type in sections:
        section = selected_glossary.get(section_name, {})

        # 긴 key 우선 정렬
        for ko, entry in sorted(
            section.items(),
            key=lambda x: max(
                len(x[0]),
                max((len(v) for v in x[1].get("variants", [])), default=0)
            ),
            reverse=True
        ):
            if not entry.get("protect", True):
                continue

            token = token_template.format(counters[section_name])
            new_text, matched_form = replace_entry_with_token(text, ko, entry, token)

            if matched_form:
                text = new_text
                token_map[token] = {
                    "korean": ko,
                    "matched_form": matched_form,
                    "english": entry.get("en", ""),
                    "type": token_type
                }
                counters[section_name] += 1

    # token_order를 텍스트 내 출현 순서로 추출 (처리 순서가 아님)
    token_order = extract_token_order_from_text(text, token_map)

    return text, token_map, token_order


def extract_token_order_from_text(text: str, token_map: dict) -> list:
    """텍스트에서 토큰 출현 순서 추출

    Args:
        text: 토큰이 포함된 텍스트
        token_map: 토큰 맵

    Returns:
        텍스트 내 출현 순서대로 정렬된 토큰 리스트
    """
    if not token_map:
        return []

    # 각 토큰의 위치 찾기
    token_positions = []
    for token in token_map.keys():
        pos = text.find(token)
        if pos >= 0:
            token_positions.append((pos, token))

    # 위치 순으로 정렬
    token_positions.sort(key=lambda x: x[0])

    return [token for _, token in token_positions]


def replace_entry_with_token(
    text: str,
    ko: str,
    entry: dict,
    token: str
) -> tuple[str, Optional[str]]:
    """entry를 token으로 치환

    한영 병기 패턴 처리:
    - "한글용어(EnglishTerm)" → "__TERM_001__" (영어 괄호도 함께 제거)
    - "용어명(Translation)" → "__TERM_001__"
    """
    import re

    # 치환 대상 forms
    forms = [ko] + entry.get("variants", [])

    # fuzzy match 후보가 있으면 추가
    match_info = entry.get("_match_info", {})
    if "fuzzy_candidate" in match_info:
        forms.append(match_info["fuzzy_candidate"])

    # 긴 form 우선 치환
    forms = sorted(set(forms), key=len, reverse=True)

    # 영어 번역 (한영 병기 패턴 매칭용)
    english = entry.get("en", "")

    for form in forms:
        if form not in text:
            continue

        # 한영 병기 패턴 체크: "한글(English)" 또는 "한글 (English)"
        # 예: "한글용어(EnglishTerm)", "용어명 (Translation)"
        if english:
            # 패턴: 한글 + 선택적 공백 + (영어)
            bilingual_pattern = re.escape(form) + r'\s*\(' + re.escape(english) + r'\)'
            if re.search(bilingual_pattern, text, re.IGNORECASE):
                text = re.sub(bilingual_pattern, token, text, count=1, flags=re.IGNORECASE)
                return text, form

        # 일반 치환 (한영 병기가 아닌 경우)
        text = text.replace(form, token, 1)
        return text, form

    return text, None


def restore_tokens(text: str, token_map: dict) -> str:
    """토큰 복원 (깨짐 대응)"""
    def replace_token(match):
        token_type = match.group(1)  # PN, ORG, or TERM
        token_num = int(match.group(2))
        original_key = f"__{token_type}_{token_num:03d}__"
        entry = token_map.get(original_key, {})
        return entry.get("english", match.group(0))

    return TOKEN_RE.sub(replace_token, text)


def extract_token_keys(text: str) -> list:
    """텍스트에서 토큰 키 추출"""
    keys = []
    for m in TOKEN_RE.finditer(text):
        typ = m.group(1)
        num = int(m.group(2))
        keys.append(f"__{typ}_{num:03d}__")
    return keys


def validate_token_preservation(
    input_text: str,
    output_text: str,
    token_map: dict,
    token_order: Optional[list] = None
) -> list:
    """토큰 보존 검증 (missing/extra/duplicate/order/expanded)

    token_missing vs token_expanded:
    - 토큰이 출력에 없더라도 expected English가 출력에 있으면 token_expanded (valid)
    - 토큰도 없고 expected English도 없으면 token_missing (error)
    """
    issues = []
    output_lower = output_text.lower()

    expected = token_order if token_order else list(token_map.keys())
    found = extract_token_keys(output_text)

    # missing 체크 (with expanded detection)
    missing_tokens = []
    expanded_tokens = []

    for token in expected:
        if token in found:
            continue  # 토큰 있음 → OK

        # 토큰 없음 → expected English 확인
        token_info = token_map.get(token, {})
        expected_en = token_info.get("english", "")
        aliases = token_info.get("aliases", [])

        # expected English 또는 aliases가 출력에 있는지 확인
        english_found = False
        if expected_en and expected_en.lower() in output_lower:
            english_found = True
        elif aliases:
            for alias in aliases:
                if alias.lower() in output_lower:
                    english_found = True
                    break

        if english_found:
            expanded_tokens.append(token)  # token_expanded (valid)
        else:
            missing_tokens.append(token)  # token_missing (error)

    if missing_tokens:
        issues.append({"type": "token_missing", "tokens": missing_tokens})

    if expanded_tokens:
        issues.append({"type": "token_expanded", "tokens": expanded_tokens})

    # extra 체크
    extra = [t for t in found if t not in expected]
    if extra:
        issues.append({"type": "token_extra", "tokens": extra})

    # duplicate 체크
    duplicate = [t for t in set(found) if found.count(t) > 1]
    if duplicate:
        issues.append({"type": "token_duplicate", "tokens": duplicate})

    # order 체크 (expanded tokens 제외)
    found_in_expected = [t for t in found if t in expected]
    expected_order = [t for t in expected if t in found]
    if found_in_expected != expected_order:
        issues.append({"type": "token_order_changed"})

    return issues


def recover_broken_tokens(output_text: str, token_map: dict) -> tuple[str, int]:
    """깨진 토큰 복구

    Returns:
        (recovered_text, recovered_count)
    """
    recovered_count = 0

    def repl(match):
        nonlocal recovered_count
        typ = match.group(1)  # PN, ORG, or TERM
        num = int(match.group(2))
        canonical = f"__{typ}_{num:03d}__"

        if canonical in token_map:
            if match.group(0) != canonical:
                recovered_count += 1
            return canonical
        return match.group(0)

    recovered_text = TOKEN_RE.sub(repl, output_text)
    return recovered_text, recovered_count


def protect_blocks(blocks: list[dict], glossary: dict) -> list[dict]:
    """모든 블록에 glossary 토큰 보호 적용"""
    for block in blocks:
        source_text = block.get("source_text", "")

        # glossary 선택
        selected = select_glossary_for_block(source_text, glossary)

        # 토큰 보호
        protected_text, token_map, token_order = protect_glossary_tokens(
            source_text, selected
        )

        block["selected_glossary"] = selected
        block["protected_text"] = protected_text
        block["token_map"] = token_map
        block["token_order"] = token_order

    return blocks


def save_protected_blocks(blocks: list[dict], output_path: str):
    """보호된 블록 저장"""
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
