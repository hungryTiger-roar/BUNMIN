"""
Document-level Candidate Extraction

문서 전체에서 glossary 후보 추출 (품질 최대화 버전)

입력:
- regions.deduplicated.json (정규화+중복제거된 OCR)
- image_texts.deduplicated.json (이미지 내 텍스트)
- existing_glossary (optional, 기존 glossary)

출력:
- document_candidates.json

역할:
- 후보는 넓게 뽑고 GPT가 분류한다
- 문장 내부 용어, 괄호 병기 용어, 나열 용어 등 다양한 패턴 추출
- GPT Classification 단계를 위한 후보 추출
"""
import re
from typing import Optional
from .config import cfg


# =============================================================================
# 정규화 함수
# =============================================================================

def normalize_glossary_key(text: str) -> str:
    """glossary 키 정규화 (중복 제거용)

    다양한 형태의 동일 용어를 같은 키로 매핑:
    - 용어명
    - 용어명(English)
    - ■ 용어명(English): 설명 텍스트
    - 용어명이란?
    """
    # 괄호 내용 제거
    text = re.sub(r"\([^)]*\)", "", text)
    # 앞쪽 bullet/기호 제거
    text = re.sub(r"^[■▪▫•●○◦\-\–\—\s·ㆍ]+", "", text)
    # 뒤쪽 구두점/조사 제거
    text = re.sub(r"[:：?？.!！\s]+(이란|이란\?|이다|입니다)?$", "", text)
    # 공백 제거
    text = re.sub(r"\s+", "", text)
    return text.lower()


# =============================================================================
# 기존 glossary 체크 (normalized match)
# =============================================================================

def build_normalized_glossary_index(existing_glossary: Optional[dict]) -> set:
    """기존 glossary의 normalized key 인덱스 생성"""
    if not existing_glossary:
        return set()

    index = set()
    for section in ["proper_nouns", "organizations", "terms", "common_words"]:
        for key in existing_glossary.get(section, {}).keys():
            index.add(normalize_glossary_key(key))
    return index


def is_in_existing_glossary(
    text: str,
    existing_glossary: Optional[dict],
    normalized_index: Optional[set] = None
) -> bool:
    """이미 glossary에 있는지 확인 (normalized match)"""
    if not existing_glossary:
        return False

    # normalized index가 없으면 생성
    if normalized_index is None:
        normalized_index = build_normalized_glossary_index(existing_glossary)

    normalized_text = normalize_glossary_key(text)
    return normalized_text in normalized_index


# =============================================================================
# 괄호 병기 용어 추출 (1순위)
# =============================================================================

def extract_parenthesized_terms(text: str) -> list[dict]:
    """괄호 병기 용어 추출

    한글(English) 형태의 용어 쌍 추출

    Returns:
        list: [{"ko": "한글용어", "en": "EnglishTerm", "kind_hint": "bilingual_term"}, ...]
    """
    results = []

    # 패턴 1: 한글(영어) - 가장 흔한 형태
    for match in re.finditer(r"([가-힣A-Za-z\s]{1,30})\(([^)]{1,50})\)", text):
        ko = match.group(1).strip(" ■-–—•·ㆍ\t")
        en = match.group(2).strip()

        # 한글이 포함되고, 괄호 안에 영어가 있는 경우만
        if re.search(r"[가-힣]", ko) and re.search(r"[A-Za-z]", en):
            # 너무 짧은 한글(조사 등)은 제외
            ko_only = re.sub(r"[^가-힣]", "", ko)
            if len(ko_only) >= 2:
                results.append({
                    "ko": ko,
                    "en": en,
                    "kind_hint": "bilingual_term",
                    "full_match": match.group(0)
                })

    # 패턴 2: English(한글) - 역방향
    for match in re.finditer(r"([A-Za-z][A-Za-z\s]{1,30})\(([가-힣]{2,20})\)", text):
        en = match.group(1).strip()
        ko = match.group(2).strip()

        results.append({
            "ko": ko,
            "en": en,
            "kind_hint": "bilingual_term",
            "full_match": match.group(0)
        })

    return results


# =============================================================================
# 문장 내부 나열 용어 추출 (2순위)
# =============================================================================

def extract_subterm_candidates(text: str) -> list[str]:
    """문장 내부에서 나열된 용어 개별 추출

    입력: "■ 용어1, 용어2, 용어3 등의 항목이..."
    출력: ["용어1", "용어2", "용어3"]

    쉼표, 중점, 슬래시 등으로 구분된 용어들을 개별 추출
    """
    candidates = []

    # 쉼표/중점/슬래시/콜론/세미콜론/개행 기준 분리
    parts = re.split(r"[,，、/·ㆍ:：;；\n]", text)

    for part in parts:
        # 앞뒤 기호/공백 제거
        part = part.strip(" ■▪▫•●○◦\-–—·ㆍ\t")

        # 괄호 제거 (병기 추출은 별도로 함)
        part_no_paren = re.sub(r"\([^)]*\)", "", part).strip()

        # 뒤쪽 조사 제거
        part_clean = re.sub(
            r"(은|는|이|가|을|를|의|에|에서|으로|로|와|과|등의|등|에게|한테|께|처럼|같이|보다|부터|까지|만|도|조차|마저)$",
            "",
            part_no_paren
        ).strip()

        # 유효성 검사: 2~20자, 한글 포함
        part_stripped = part_clean.replace(" ", "")
        if 2 <= len(part_stripped) <= 20 and re.search(r"[가-힣]", part_clean):
            # 문장이 아닌 용어만 (동사 어미로 끝나지 않음)
            if not re.search(r"(다|요|니다|습니다|했다|한다|된다|있다|없다)$", part_clean):
                candidates.append(part_clean)

    return candidates


# =============================================================================
# 외래어/전문용어 추출
# =============================================================================

def extract_foreign_loanwords(text: str) -> list[str]:
    """외래어/전문용어 추출

    알고리즘, 데이터베이스, 프레임워크 등
    """
    candidates = []

    # 4자 이상의 한글 단어 중 외래어 패턴
    # 외래어 특징: ㅔ, ㅐ, ㅣ 등의 모음 + 받침 없는 경우가 많음
    for match in re.finditer(r"[가-힣]{4,15}", text):
        word = match.group(0)

        # 외래어 힌트: 특정 음절 패턴
        loanword_patterns = [
            r"이션$",      # ~tion (커뮤니케이션)
            r"리즘$",      # ~ism (메커니즘)
            r"이스$",      # ~ce/~se (서비스)
            r"먼트$",      # ~ment (매니지먼트)
            r"워크$",      # ~work (네트워크)
            r"그램$",      # ~gram (프로그램)
            r"시스템$",    # 시스템
            r"모델$",      # 모델
            r"이론$",      # 이론
            r"^알고",      # algo~
            r"^데이터",    # data~
            r"^프로",      # pro~
            r"^컴퓨",      # compu~
            r"^마케",      # marke~
            r"^매니",      # mana~
        ]

        if any(re.search(p, word) for p in loanword_patterns):
            candidates.append(word)

    return candidates


# =============================================================================
# 메인 후보 추출 함수
# =============================================================================

def extract_document_candidates(
    all_pages_regions: list[list[dict]],
    image_text_regions: Optional[list[dict]] = None,
    existing_glossary: Optional[dict] = None
) -> list[dict]:
    """문서 후보 추출 (GPT Classification용) - 품질 최대화 버전

    역할: 문서 전체에서 모든 타입의 '후보'를 추출.
    문장 내부 용어, 괄호 병기 용어, 나열 용어 등 다양한 패턴 추출.
    최종 분류(person vs common_word 등)는 GPT Classification 단계에서 결정.

    Args:
        all_pages_regions: 일반 OCR regions (페이지별)
        image_text_regions: 이미지 내 텍스트 (image_texts.deduplicated.json)
        existing_glossary: 기존 glossary (있으면 skip)

    Returns:
        list: 후보 목록 (각 항목에 kind_hint, source, context_samples 포함)
    """
    candidates = {}

    # normalized glossary index 미리 생성 (성능 최적화)
    normalized_index = build_normalized_glossary_index(existing_glossary)

    # 1. 일반 OCR regions 후보 추출
    for page_no, page_regions in enumerate(all_pages_regions, start=1):
        for region in page_regions:
            text = region.get("ocr_text", "").strip()
            if not text:
                continue

            extract_candidates_from_text(
                candidates=candidates,
                text=text,
                page_no=page_no,
                region=region,
                source="ocr_text",
                bbox=region.get("bbox"),
                existing_glossary=existing_glossary,
                normalized_index=normalized_index
            )

    # 2. 이미지 내부 텍스트 후보 추출
    for item in image_text_regions or []:
        text = item.get("text", "").strip()
        if not text:
            continue

        extract_candidates_from_text(
            candidates=candidates,
            text=text,
            page_no=item.get("page_no"),
            region=item,
            source="image_text",
            bbox=item.get("bbox_page"),
            parent_image_region_id=item.get("parent_image_region_id"),
            existing_glossary=existing_glossary,
            normalized_index=normalized_index
        )

    # 최소 빈도 이상만 반환
    min_freq = cfg("candidate.min_frequency", 1)
    return [v for v in candidates.values() if v["count"] >= min_freq]


def extract_candidates_from_text(
    candidates: dict,
    text: str,
    page_no: int,
    region: dict,
    source: str,
    bbox: Optional[list],
    parent_image_region_id: Optional[str] = None,
    existing_glossary: Optional[dict] = None,
    normalized_index: Optional[set] = None
):
    """텍스트에서 후보 추출 (품질 최대화 버전)

    여러 extractor 병렬 실행:
    1. 괄호 병기 용어 추출 (bilingual_term)
    2. 나열 용어 추출 (subterm_phrase)
    3. 외래어 추출 (foreign_loanword)
    4. 기관명 추출 (organization)
    5. 제목/소제목 추출 (title_phrase)
    6. 짧은 한글 (short_korean) - 점수 힌트용
    """

    # =========================================================================
    # 1순위: 괄호 병기 용어 추출 (가장 고품질)
    # =========================================================================
    bilingual_terms = extract_parenthesized_terms(text)
    for term in bilingual_terms:
        ko_text = term["ko"]

        # 기존 glossary 체크
        if is_in_existing_glossary(ko_text, existing_glossary, normalized_index):
            continue

        add_candidate(
            candidates=candidates,
            text=ko_text,
            page_no=page_no,
            region=region,
            kind_hint="bilingual_term",
            source=source,
            bbox=bbox,
            parent_image_region_id=parent_image_region_id,
            context_sample=text,
            suggested_translation=term["en"]
        )

    # =========================================================================
    # 2순위: 문장 내부 나열 용어 추출
    # =========================================================================
    subterms = extract_subterm_candidates(text)
    for subterm in subterms:
        if is_in_existing_glossary(subterm, existing_glossary, normalized_index):
            continue

        add_candidate(
            candidates=candidates,
            text=subterm,
            page_no=page_no,
            region=region,
            kind_hint="subterm_phrase",
            source=source,
            bbox=bbox,
            parent_image_region_id=parent_image_region_id,
            context_sample=text
        )

    # =========================================================================
    # 3순위: 외래어/전문용어 추출
    # =========================================================================
    loanwords = extract_foreign_loanwords(text)
    for word in loanwords:
        if is_in_existing_glossary(word, existing_glossary, normalized_index):
            continue

        add_candidate(
            candidates=candidates,
            text=word,
            page_no=page_no,
            region=region,
            kind_hint="foreign_loanword",
            source=source,
            bbox=bbox,
            parent_image_region_id=parent_image_region_id,
            context_sample=text
        )

    # =========================================================================
    # 4순위: 기관/학교명 패턴
    # =========================================================================
    if looks_like_organization(text):
        if not is_in_existing_glossary(text, existing_glossary, normalized_index):
            add_candidate(
                candidates=candidates,
                text=text,
                page_no=page_no,
                region=region,
                kind_hint="organization",
                source=source,
                bbox=bbox,
                parent_image_region_id=parent_image_region_id,
                context_sample=text
            )

    # =========================================================================
    # 5순위: 제목/부제목 추출 (OCR만)
    # =========================================================================
    if source == "ocr_text" and region.get("_type") in ["title", "subtitle"]:
        if not is_in_existing_glossary(text, existing_glossary, normalized_index):
            add_candidate(
                candidates=candidates,
                text=text,
                page_no=page_no,
                region=region,
                kind_hint="title_phrase",
                source=source,
                bbox=bbox,
                parent_image_region_id=parent_image_region_id,
                context_sample=text
            )

    # =========================================================================
    # 6순위: 짧은 한글 (점수 힌트용 - risk_flag 추가)
    # =========================================================================
    norm_ko = re.sub(r"[^가-힣]", "", text)
    short_min = cfg("candidate.short_korean_min_len", 2)
    short_max = cfg("candidate.short_korean_max_len", 4)

    if short_min <= len(norm_ko) <= short_max and re.fullmatch(r"[가-힣]+", norm_ko):
        if not is_in_existing_glossary(norm_ko, existing_glossary, normalized_index):
            add_candidate(
                candidates=candidates,
                text=norm_ko,
                page_no=page_no,
                region=region,
                kind_hint="short_korean",
                source=source,
                bbox=bbox,
                parent_image_region_id=parent_image_region_id,
                context_sample=text,
                risk_flag="common_word_possible"
            )

    # =========================================================================
    # 7순위: 접미사 기반 용어 (점수 힌트용 - 이미 다른 방식으로 안 잡힌 경우만)
    # =========================================================================
    if looks_like_term_phrase(text):
        normalized = normalize_glossary_key(text)
        # 이미 다른 kind_hint로 추가된 경우 스킵
        already_added = any(
            normalize_glossary_key(c["text"]) == normalized
            for c in candidates.values()
        )
        if not already_added and not is_in_existing_glossary(text, existing_glossary, normalized_index):
            add_candidate(
                candidates=candidates,
                text=text,
                page_no=page_no,
                region=region,
                kind_hint="term_phrase_suffix",
                source=source,
                bbox=bbox,
                parent_image_region_id=parent_image_region_id,
                context_sample=text,
                risk_flag="suffix_based_only"
            )


def add_candidate(
    candidates: dict,
    text: str,
    page_no: int,
    region: dict,
    kind_hint: str,
    source: str,
    bbox: Optional[list],
    parent_image_region_id: Optional[str] = None,
    context_sample: Optional[str] = None,
    suggested_translation: Optional[str] = None,
    risk_flag: Optional[str] = None
):
    """후보 추가 (품질 최대화 버전)

    확장된 필드:
    - normalized_text: 정규화된 키 (중복 제거용)
    - suggested_translation: 괄호 병기에서 추출된 영어 번역
    - context_samples: GPT 분류를 위한 문맥 샘플
    - risk_flags: 품질 위험 플래그
    """
    normalized = normalize_glossary_key(text)
    key = (normalized, kind_hint)

    if key not in candidates:
        candidates[key] = {
            "text": text,
            "normalized_text": normalized,
            "kind_hint": kind_hint,
            "suggested_translation": suggested_translation,
            "count": 0,
            "pages": [],
            "evidence": [],
            "context_samples": [],
            "risk_flags": []
        }

    candidates[key]["count"] += 1

    if page_no and page_no not in candidates[key]["pages"]:
        candidates[key]["pages"].append(page_no)

    # suggested_translation 업데이트 (있으면)
    if suggested_translation and not candidates[key]["suggested_translation"]:
        candidates[key]["suggested_translation"] = suggested_translation

    # context_sample 추가 (최대 5개까지)
    if context_sample and len(candidates[key]["context_samples"]) < 5:
        # 중복 방지
        if context_sample not in candidates[key]["context_samples"]:
            candidates[key]["context_samples"].append(context_sample)

    # risk_flag 추가
    if risk_flag and risk_flag not in candidates[key]["risk_flags"]:
        candidates[key]["risk_flags"].append(risk_flag)

    # evidence 추가
    evidence = {
        "page_no": page_no,
        "bbox": bbox,
        "confidence": region.get("confidence", 1.0),
        "source": source
    }

    if source == "ocr_text":
        evidence["region_type"] = region.get("_type")
        evidence["is_near_cover_or_footer"] = is_near_cover_or_footer(region)
    elif source == "image_text":
        evidence["parent_image_region_id"] = parent_image_region_id

    candidates[key]["evidence"].append(evidence)


# =============================================================================
# 패턴 매칭 함수
# =============================================================================

def looks_like_organization(text: str) -> bool:
    """기관/학교명 패턴인지 (품질 우선: 포괄적 매칭)"""
    org_suffixes = [
        # 교육기관
        "대학교", "대학", "학과", "학부", "대학원", "학교", "고등학교", "중학교",
        # 연구기관
        "연구소", "연구원", "연구실", "연구센터", "실험실",
        # 의료기관
        "병원", "의원", "클리닉", "의료원",
        # 단체/기관
        "재단", "협회", "학회", "위원회", "공단", "공사",
        "센터", "원", "청", "부", "처", "국", "과",
        # 기업/조직
        "회사", "기업", "그룹", "법인", "조합",
        # 기타
        "본부", "지부", "사무소", "사무국"
    ]
    return any(text.endswith(suffix) for suffix in org_suffixes)


def looks_like_term_phrase(text: str) -> bool:
    """전문 용어 패턴인지 (접미사 기반 - 점수 힌트용)

    주의: 이 함수는 단독 판단이 아닌 점수 힌트로만 사용
    """
    term_suffixes = [
        "학", "론", "설", "주의", "사상",
        "법", "술", "기", "방", "식",
        "성", "화", "력", "도", "율", "량",
        "비", "치", "가", "점", "값",
        "형", "계", "체", "제", "구", "층",
        "관", "권", "면", "선", "역", "간",
    ]
    text_stripped = text.replace(" ", "")
    if len(text_stripped) < 2 or len(text_stripped) > 20:
        return False
    if not re.fullmatch(r"[가-힣\s]+", text):
        return False
    return any(text_stripped.endswith(suffix) for suffix in term_suffixes)


def is_near_cover_or_footer(region: dict) -> bool:
    """표지/footer 근처인지"""
    region_type = region.get("_type", "")
    return region_type in ["footer", "affiliation", "person_name", "copyright"]


# =============================================================================
# 저장/로드 함수
# =============================================================================

def save_candidates(candidates: list[dict], output_path: str):
    """후보 목록 저장"""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "candidates": candidates,
            "count": len(candidates),
            "by_kind": _count_by_kind(candidates)
        }, f, ensure_ascii=False, indent=2)


def _count_by_kind(candidates: list[dict]) -> dict:
    """kind_hint별 개수 집계"""
    counts = {}
    for c in candidates:
        kind = c.get("kind_hint", "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def load_candidates(input_path: str) -> list[dict]:
    """후보 목록 로드"""
    import json
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "candidates" in data:
        return data["candidates"]
    return []
