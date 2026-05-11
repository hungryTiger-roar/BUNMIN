"""
Translation Block Building

정렬된 region들을 번역 블록으로 병합

입력:
- regions.sorted.json

출력:
- blocks.json

핵심 로직:
- MERGE_POLICY에 따른 병합 결정
- 불완전 문장 기반 continuation 병합
- safety check (면적, 높이, gap, 방해 region)
- bullet_candidate 승격 처리
"""
import re
from typing import Optional
from .config import cfg
from .region_classification import starts_with_bullet


def is_ocr_fragment_like(text: str) -> bool:
    """OCR fragment로 보이는지 판단 (공격적 병합 대상)

    True 케이스:
    - "직 면", "희 소 성" 등 한글 1글자들이 공백으로 분리된 경우
    - 총 2-3자 한글인데 공백이 포함된 경우

    False 케이스:
    - "연구", "참고", "문헌" 등 정상적인 짧은 한글 단어
    - 영어나 숫자가 포함된 경우
    """
    if not text:
        return False

    stripped = text.strip()
    if not stripped:
        return False

    # 공백 제거한 텍스트
    no_space = stripped.replace(" ", "")

    # 조건 1: 한글 1글자들이 공백으로 분리 ("직 면", "희 소 성")
    # 패턴: 한글1자 + 공백 + 한글1자 (반복 가능)
    if re.match(r'^[가-힣](\s+[가-힣])+$', stripped):
        return True

    # 조건 2: 2-3자 한글인데 공백이 포함된 경우
    if len(no_space) <= 3 and ' ' in stripped:
        # 순수 한글인지 확인
        if re.match(r'^[가-힣]+$', no_space):
            return True

    # 조건 3: 1자 한글만 있는 경우 (예: "면", "에")
    if len(no_space) == 1 and re.match(r'^[가-힣]$', no_space):
        return True

    return False


def has_colon_definition_pattern(text: str) -> bool:
    """colon definition 패턴인지 확인

    패턴 예시:
    - "용어명(English): 설명 텍스트가 이어지는 형태"
    - "■ 주제: 관련 내용 설명..."
    - "■ 용어(English): 설명..."

    조건:
    1. 텍스트에 ':' 가 있음
    2. ':' 뒤에 텍스트가 있음 (빈 문자열 아님)
    3. ':' 앞에 한글 또는 영어 용어가 있음
    """
    if not text or ':' not in text:
        return False

    # 콜론 위치 찾기
    colon_pos = text.find(':')
    if colon_pos < 2:  # 최소 2자 이상의 용어가 콜론 앞에 있어야 함
        return False

    before_colon = text[:colon_pos].strip()
    after_colon = text[colon_pos + 1:].strip()

    # 콜론 뒤에 텍스트가 있어야 함
    if len(after_colon) < 3:
        return False

    # 콜론 앞이 용어 패턴인지 확인
    # 패턴: "용어", "용어(English)", "■ 용어", "■ 용어(English)"
    term_pattern = r'(?:^|■\s*)[\w가-힣]+(?:\s*\([A-Za-z]+\))?$'
    if re.search(term_pattern, before_colon):
        return True

    return False


def get_incomplete_sentence_score(text: str) -> tuple[int, str]:
    """문장의 불완전성 점수 계산 (score hint)

    Returns:
        (score, reason):
            0: 완전한 문장
            1-2: 약간 불완전
            3+: 확실히 불완전 (continuation 병합 필요)
    """
    if not text or not text.strip():
        return 0, "empty"

    text = text.strip()
    score = 0
    reasons = []

    # 1. 완전한 종결 패턴 (한국어/영어) → score 감소
    complete_patterns = [
        (r'[.!?。？！]$', "punct"),           # 마침표/물음표/느낌표
        (r'[다니까요죠네데][\.]?$', "ending"),  # 한국어 종결어미
        (r'습니다[\.]?$', "-습니다"),            # -습니다
        (r'합니다[\.]?$', "-합니다"),            # -합니다
        (r'됩니다[\.]?$', "-됩니다"),            # -됩니다
        (r'입니다[\.]?$', "-입니다"),            # -입니다
        (r'있다[\.]?$', "-있다"),              # -있다
        (r'없다[\.]?$', "-없다"),              # -없다
        (r'이다[\.]?$', "-이다"),              # -이다
    ]

    for pattern, name in complete_patterns:
        if re.search(pattern, text):
            return 0, f"complete({name})"  # 완전한 문장

    # 2. 강한 불완전 종결 패턴 → score +4 (쉼표), +3 (기타)
    strong_incomplete = [
        (r'[,，]$', "comma", 4),            # 쉼표 → +4 (강화)
        (r'[;:；]$', "semicolon", 3),       # 세미콜론/콜론
        (r'하고$', "-하고", 3),              # ~하고
        (r'하며$', "-하며", 3),              # ~하며
        (r'으며$', "-으며", 3),              # ~으며
        (r'이며$', "-이며", 3),              # ~이며
        # 연체형 종결 패턴 (다음 명사 필요)
        (r'관한$', "-관한", 3),              # ~에 관한 + 명사
        (r'대한$', "-대한", 3),              # ~에 대한 + 명사
        (r'위한$', "-위한", 3),              # ~을 위한 + 명사
        (r'통한$', "-통한", 3),              # ~을 통한 + 명사
        (r'의한$', "-의한", 3),              # ~에 의한 + 명사
        (r'따른$', "-따른", 3),              # ~에 따른 + 명사
        (r'인한$', "-인한", 3),              # ~로 인한 + 명사
        (r'향한$', "-향한", 3),              # ~을 향한 + 명사
        # 동사 연체형 (다음 명사 필요) - "고용하는 연구" 등
        (r'하는$', "-하는", 3),              # ~하는 + 명사
        (r'되는$', "-되는", 3),              # ~되는 + 명사
        (r'있는$', "-있는", 3),              # ~있는 + 명사 (형용사적)
        (r'없는$', "-없는", 3),              # ~없는 + 명사
        (r'받는$', "-받는", 3),              # ~받는 + 명사
        (r'주는$', "-주는", 3),              # ~주는 + 명사
        (r'오는$', "-오는", 3),              # ~오는 + 명사
        (r'가는$', "-가는", 3),              # ~가는 + 명사
        (r'나는$', "-나는", 3),              # ~나는 + 명사 (발생하는)
        (r'된$', "-된", 3),                  # ~된 + 명사 (과거 연체형)
        (r'한$', "-한", 3),                  # ~한 + 명사 (과거 연체형)
        # 간접인용/의문 패턴 (다음에 동사 필요)
        (r'는지를$', "-는지를", 3),          # ~하는지를 + 동사 (결정하다 등)
        (r'는지$', "-는지", 3),              # ~하는지 + 동사
        (r'ㄴ지를$', "-ㄴ지를", 3),          # ~한지를 + 동사
        (r'ㄴ지$', "-ㄴ지", 3),              # ~한지 + 동사
    ]
    for pattern, name, pts in strong_incomplete:
        if re.search(pattern, text, re.IGNORECASE):
            score += pts
            reasons.append(f"{name}:+{pts}")
            break

    # 3. 약한 불완전 종결 패턴 → score +1
    weak_incomplete = [
        r'에$', r'에서$', r'으로$', r'로서$', r'에게$',  # "에" 추가
        r'와$', r'과$', r'의$', r'를$', r'을$',
        r'이$', r'가$', r'는$', r'은$',
        r'할$', r'한$', r'인$', r'된$',
        r'관$', r'대$', r'중$',  # "...에 관", "...에 대", "...하는 중" 등
        # 의문/부사 어미 (다음에 동사 필요)
        r'어떻게$', r'무엇을$', r'얼마나$', r'왜$',
        r'어디서$', r'언제$', r'누가$', r'어떤$',
    ]
    for pattern in weak_incomplete:
        if re.search(pattern, text):
            score += 1
            reasons.append(f"weak:+1")
            break

    # 4. colon definition 패턴 체크 (용어: 설명..., 용어(English): 설명...)
    # 콜론 이후 텍스트가 있고, 완전한 종결이 아니면 +2
    if has_colon_definition_pattern(text) and score > 0:
        score += 2
        reasons.append("colon_def:+2")

    return score, ",".join(reasons) if reasons else "none"


def is_incomplete_sentence(text: str) -> bool:
    """문장이 불완전한지 검사 (하위 호환용 wrapper)"""
    score, _ = get_incomplete_sentence_score(text)
    return score >= 3


# 병합 정책
MERGE_POLICY = {
    "paragraph": "allow",
    "title": "allow_same_title",
    "subtitle": "allow_same_title",
    "bullet_head": "allow_continuation",
    "bullet_continuation": "allow_with_previous_bullet",
    "bullet_candidate": "allow_with_bullet_types",
    "table_cell": "allow_same_cell",
    "diagram_label": "deny",
    "footer": "deny",
    "copyright": "deny",
    "page_number": "deny",
    "affiliation": "allow_same_affiliation",
    "person_name": "deny",
    "list_number": "deny",
    "section_number": "deny",
    "code": "custom",      # 1차에서는 deny로 처리
    "formula": "custom",   # 1차에서는 deny로 처리
    "url": "deny",
    "mixed": "deny",
}


def build_translation_blocks(
    regions: list[dict],
    image_size: tuple[int, int],
    page_no: int = 1,
    page_type: str = "paragraph_or_bullet"
) -> list[dict]:
    """region들을 번역 블록으로 그룹화

    Args:
        regions: 정렬된 region 리스트 (_sorted_index 포함)
        image_size: (page_w, page_h)
        page_no: 페이지 번호 (prompt_id 생성용)
        page_type: 페이지 타입 ("diagram_or_label_dense", "paragraph_or_bullet", "agenda_or_toc")

    Returns:
        블록 리스트 (각 블록에 region들 포함)

    Note:
        _classification이 "preserve_original"인 region은 번역 대상에서 제외됩니다.
        단, 별도 블록으로 생성되어 원본 텍스트가 유지됩니다.
    """
    if not regions:
        return []

    # preserve_original 영역 분리 (번역하지 않고 원본 유지)
    translate_regions = []
    preserve_regions = []
    for r in regions:
        classification = r.get("_classification", "translate_target")
        if classification == "preserve_original":
            preserve_regions.append(r)
        else:
            translate_regions.append(r)

    if preserve_regions:
        print(f"[BlockBuilding] 페이지 {page_no}: {len(preserve_regions)}개 preserve_original 영역 제외")

    # 번역 대상 영역만으로 블록 생성
    regions = translate_regions

    # diagram_or_label_dense 페이지는 병합 최소화
    minimize_merge = (page_type == "diagram_or_label_dense")
    if minimize_merge:
        print(f"[BlockBuilding] 페이지 {page_no}: diagram/label dense 모드 - 병합 최소화")

    original_region_count = len(regions)
    blocks = []
    current_block_regions = []
    merge_debug = []
    merge_count = 0  # 병합 횟수 카운트

    for region in regions:
        if not current_block_regions:
            # 새 블록 시작
            current_block_regions = [region]
            continue

        prev_region = current_block_regions[-1]

        # diagram/label dense 모드: OCR fragment 병합만 허용
        if minimize_merge:
            should_merge_result, reason = should_merge_minimal(
                prev_region, region, current_block_regions, image_size, regions
            )
        else:
            # 일반 모드: 기존 병합 로직
            should_merge_result, reason = should_merge(
                prev_region, region, current_block_regions, image_size, regions
            )

        merge_debug.append({
            "prev_index": prev_region.get("_sorted_index"),
            "curr_index": region.get("_sorted_index"),
            "merged": should_merge_result,
            "reason": reason
        })

        if should_merge_result:
            current_block_regions.append(region)
            merge_count += 1
        else:
            # 현재 블록 완료, 새 블록 시작
            blocks.append(_create_block(current_block_regions, len(blocks), page_no, page_type))
            current_block_regions = [region]

    # 마지막 블록
    if current_block_regions:
        blocks.append(_create_block(current_block_regions, len(blocks), page_no, page_type))

    # 디버그 정보 저장 (첫 블록에)
    if blocks:
        blocks[0]["_merge_debug"] = merge_debug

    # 병합 결과 로그 출력
    final_block_count = len(blocks)
    merged_regions = original_region_count - final_block_count
    mode_str = "[minimal]" if minimize_merge else ""
    print(f"[BlockBuilding] 페이지 {page_no}{mode_str}: {original_region_count}개 region → {final_block_count}개 block (병합: {merged_regions}개, 병합횟수: {merge_count})")

    # 2개 이상 region이 병합된 블록 상세 로그
    multi_region_blocks = [b for b in blocks if b.get("region_count", 1) > 1]
    if multi_region_blocks:
        for b in multi_region_blocks:
            print(f"  [Merged] {b['prompt_id']}: {b['region_count']}개 region 병합 → '{b['source_text'][:40]}...'")

    return blocks


def should_merge_minimal(
    prev_region: dict,
    curr_region: dict,
    current_block_regions: list[dict],
    image_size: tuple[int, int],
    all_regions: list[dict]
) -> tuple[bool, str]:
    """스마트 최소 병합 정책 (diagram/label dense 페이지용)

    병합 허용 케이스:
    1. OCR fragment (한글 1글자 분리)
    2. prev가 강하게 불완전 (쉼표, 조사 등)하고 curr가 연속 텍스트로 보일 때
    3. curr가 문장 시작이 아닌 연속 텍스트로 보일 때

    병합 금지 케이스:
    - curr가 bullet로 시작 (■, •, 1., 가. 등)
    - curr가 독립적인 제목/라벨로 보일 때
    - prev가 완전한 문장으로 끝날 때
    - union bbox가 안전 범위를 초과
    """
    prev_text = prev_region.get("ocr_text", "")
    curr_text = curr_region.get("ocr_text", "")

    # 기본 레이아웃 체크
    prev_bbox = prev_region.get("bbox", [0, 0, 0, 0])
    curr_bbox = curr_region.get("bbox", [0, 0, 0, 0])
    prev_h = prev_bbox[3] - prev_bbox[1]
    page_w, _ = image_size

    # Y 간격 - 너무 멀면 병합 안 함
    y_gap = curr_bbox[1] - prev_bbox[3]
    if prev_h > 0 and y_gap > prev_h * 2.0:
        return False, "minimal_y_gap_too_large"

    # X 간격 - 너무 멀면 병합 안 함 (같은 컬럼이 아님)
    x_diff = abs(curr_bbox[0] - prev_bbox[0])
    if page_w > 0 and x_diff > page_w * 0.15:
        return False, "minimal_x_diff_too_large"

    # === 병합 금지 조건 ===

    # curr가 bullet/목록으로 시작하면 새 항목
    if starts_with_bullet(curr_text):
        return False, "minimal_curr_is_bullet"

    # curr가 독립 라벨로 보이면 병합 안 함
    if _is_standalone_label(curr_text):
        return False, "minimal_curr_is_standalone"

    # prev가 완전한 문장으로 끝나면 병합 안 함
    prev_incomplete_score, _ = get_incomplete_sentence_score(prev_text)
    if prev_incomplete_score == 0 and not is_ocr_fragment_like(curr_text):
        return False, "minimal_prev_complete"

    # === 병합 허용 조건 ===
    should_merge = False
    merge_reason = "minimal_no_merge_signal"

    # 1. OCR fragment면 병합
    if is_ocr_fragment_like(curr_text):
        if prev_incomplete_score >= 1:
            should_merge = True
            merge_reason = "minimal_ocr_fragment"

    # 2. prev가 강하게 불완전하면 병합 (score >= 3: 쉼표, 연결어미 등)
    elif prev_incomplete_score >= 3:
        should_merge = True
        merge_reason = "minimal_prev_strongly_incomplete"

    # 3. curr가 연속 텍스트로 보이면 병합
    elif _looks_like_continuation(curr_text):
        if prev_incomplete_score >= 1:
            should_merge = True
            merge_reason = "minimal_curr_is_continuation"

    # 4. prev가 strong_incomplete(score >= 3)이고 curr가 짧은 종결 텍스트면 병합
    elif prev_incomplete_score >= 3 and len(curr_text.strip()) < 30:
        # curr가 bullet/title/footer 등이 아닌지 체크
        if not starts_with_bullet(curr_text) and not _is_standalone_label(curr_text):
            should_merge = True
            merge_reason = "minimal_strong_incomplete_completion"

    # === 병합 허용 시 safety check 적용 ===
    if should_merge:
        safety_result = check_merge_safety(current_block_regions, curr_region, image_size, all_regions)
        if not safety_result["safe"]:
            return False, f"minimal_blocked_by_safety:{safety_result['reason']}"
        return True, merge_reason

    return False, merge_reason


def _is_standalone_label(text: str) -> bool:
    """독립적인 라벨/제목인지 판단"""
    text = text.strip()
    if not text:
        return False

    # 물음표로 끝나는 짧은 텍스트 (제목)
    if text.endswith("?") and len(text) < 30:
        return True

    # "~이란?", "~란?" 패턴 (정의 제목)
    if re.search(r'[이란란][\?？]?$', text) and len(text) < 20:
        return True

    # 영어 제목 패턴
    if re.match(r'^[A-Z][A-Za-z\s]+$', text) and len(text) < 40:
        return True

    # 숫자만 있는 경우 (페이지 번호)
    if re.match(r'^\d+$', text):
        return True

    return False


def _looks_like_continuation(text: str) -> bool:
    """연속 텍스트(문장 중간)로 보이는지 판단"""
    text = text.strip()
    if not text:
        return False

    # 소문자/조사로 시작하면 연속 텍스트
    # 예: "단어 등)이...", "명사, 동사하는...", "주어를 동작해야..."
    continuation_starts = [
        r'^[가-힣]{1,2}[)）]',  # "정부 등)이" 패턴
        r'^[을를이가은는의에서로]',  # 조사로 시작
        r'^[a-z]',  # 소문자 영어로 시작
        r'^[,，、]',  # 쉼표로 시작
    ]

    for pattern in continuation_starts:
        if re.match(pattern, text):
            return True

    return False


def _ends_with_verb_or_noun(text: str) -> bool:
    """동사/명사로 끝나는지 (문장 종결 가능성)

    minimal 모드에서만 사용. prev_incomplete_score와 함께 판단해야 함.
    """
    text = text.strip()
    if not text:
        return False

    # 동사/형용사 종결 패턴
    verb_endings = [
        r'[다요음임]$',  # ~다, ~요, ~음, ~임
        r'[것점]$',  # ~것, ~점
    ]

    for pattern in verb_endings:
        if re.search(pattern, text):
            return True

    return False


def _create_block(
    regions: list[dict],
    block_index: int,
    page_no: int = 1,
    page_type: str = "paragraph_or_bullet"
) -> dict:
    """region들로 블록 생성

    Args:
        regions: 병합된 region 리스트
        block_index: 페이지 내 블록 인덱스 (0-based)
        page_no: 페이지 번호
        page_type: 페이지 타입

    Returns:
        블록 dict (prompt_id 포함)
    """
    # 텍스트 합치기
    texts = [r.get("ocr_text", "") for r in regions]
    combined_text = " ".join(t for t in texts if t)

    # union bbox 계산
    union_bbox = calculate_union_bbox(regions)

    # 블록 타입 결정 (첫 region의 타입 기준)
    block_type = determine_block_type(regions)

    # diagram/label dense 페이지의 짧은 텍스트는 short_label로 마킹
    is_short_label = (
        page_type == "diagram_or_label_dense" and
        len(combined_text.strip()) < 30
    )

    # prompt_id: 페이지별 인덱스 (p1_b01, p1_b02, p2_b01, ...)
    prompt_id = f"p{page_no}_b{block_index + 1:02d}"

    return {
        "block_id": f"block_{block_index:03d}",
        "prompt_id": prompt_id,  # 전체 파이프라인에서 사용할 고유 ID
        "page_no": page_no,
        "page_type": page_type,
        "block_type": block_type,
        "source_text": combined_text,
        "union_bbox": union_bbox,
        "region_count": len(regions),
        "region_ids": [r.get("_sorted_index") for r in regions],
        "regions": regions,
        "translation_available": False,  # 기본값 False, 번역 성공 시 True로 변경
        "is_short_label": is_short_label,  # short label translation mode 적용 여부
    }


def determine_block_type(regions: list[dict]) -> str:
    """블록 타입 결정 (region 타입들로부터)"""
    if not regions:
        return "paragraph"

    # 첫 region 타입 우선
    first_type = regions[0].get("_type", "paragraph")

    # bullet 블록인 경우
    if first_type in {"bullet_head", "bullet_candidate"}:
        return "bullet"

    # title 블록
    if first_type in {"title", "subtitle"}:
        return "title"

    return first_type


def should_merge(
    prev_region: dict,
    curr_region: dict,
    current_block_regions: list[dict],
    image_size: tuple[int, int],
    all_regions: list[dict]
) -> tuple[bool, str]:
    """병합 여부 최종 결정 (모든 병합에 safety check 적용)"""
    prev_type = prev_region.get("_type", "paragraph")
    curr_type = curr_region.get("_type", "paragraph")
    prev_text = prev_region.get("ocr_text", "")
    curr_text = curr_region.get("ocr_text", "")
    page_w, page_h = image_size

    # bullet 관련 early return 디버그 로그
    is_bullet_context = (
        prev_type in {"bullet_head", "bullet_candidate"} or
        curr_type in {"bullet_head", "bullet_candidate"} or
        starts_with_bullet(prev_text) or
        starts_with_bullet(curr_text)
    )

    # 0. 절대 병합 금지 타입 먼저 처리
    no_merge_types = {"footer", "copyright", "page_number", "url", "code", "formula"}
    if prev_type in no_merge_types or curr_type in no_merge_types:
        if is_bullet_context:
            print(f"  [EarlyReturn] no_merge_type: prev[{prev_type}]='{prev_text[:20]}' curr[{curr_type}]='{curr_text[:20]}'")
        return False, "no_merge_type"

    # bullet_head끼리는 절대 병합 금지 (각각 독립적인 bullet point)
    if prev_type == "bullet_head" and curr_type == "bullet_head":
        if is_bullet_context:
            print(f"  [EarlyReturn] bullet_head_no_merge: '{prev_text[:20]}' + '{curr_text[:20]}'")
        return False, "bullet_head_no_merge"

    # title끼리가 아닌 경우 title 병합 금지
    if (prev_type == "title" and curr_type != "title") or (prev_type != "title" and curr_type == "title"):
        return False, "title_type_mismatch"

    # 새 bullet_head가 오면 이전 블록과 병합하지 않음
    if curr_type == "bullet_head" and prev_type not in {"bullet_head"}:
        if is_bullet_context:
            print(f"  [EarlyReturn] new_bullet_head: prev[{prev_type}]='{prev_text[:20]}' → curr[bullet_head]='{curr_text[:20]}'")
        return False, "new_bullet_head"

    # 1. 정책 조회
    prev_policy = MERGE_POLICY.get(prev_type, "deny")
    curr_policy = MERGE_POLICY.get(curr_type, "deny")

    # 2. deny 정책
    if prev_policy == "deny" or curr_policy == "deny":
        if is_bullet_context:
            print(f"  [EarlyReturn] policy_deny: prev[{prev_type}]={prev_policy}, curr[{curr_type}]={curr_policy}")
        return False, "policy_deny"

    # 3. custom 정책 (1차에서는 skip)
    if prev_policy == "custom" or curr_policy == "custom":
        return False, "custom_type_skip_in_phase1"

    # 4. continuation 병합 (score 기반)
    prev_bbox = prev_region.get("bbox", [0, 0, 0, 0])
    curr_bbox = curr_region.get("bbox", [0, 0, 0, 0])
    prev_h = prev_bbox[3] - prev_bbox[1]
    curr_h = curr_bbox[3] - curr_bbox[1]

    # 불완전 문장 점수
    incomplete_score, incomplete_reason = get_incomplete_sentence_score(prev_text)

    # OCR fragment 판정
    is_ocr_fragment = is_ocr_fragment_like(curr_text)

    # ========================================
    # 핵심 원칙: 의미적 연속 신호가 없으면 병합 금지
    # 레이아웃(y/x/height)만으로는 절대 병합하지 않음
    # ========================================

    # 의미적 연속 신호 체크
    has_semantic_signal = False
    semantic_reason = "none"

    # 신호 1: prev가 불완전 문장 (incomplete_score >= 2)
    if incomplete_score >= 2:
        has_semantic_signal = True
        semantic_reason = f"prev_incomplete({incomplete_score})"

    # 신호 2: OCR fragment (공백으로 분리된 한글 조각)
    if is_ocr_fragment and incomplete_score >= 1:
        has_semantic_signal = True
        semantic_reason = f"ocr_fragment+prev_weak_incomplete({incomplete_score})"

    # 신호 3: bullet continuation (prev가 bullet_head이고 curr가 bullet 아님)
    if prev_type == "bullet_head" and not starts_with_bullet(curr_text):
        # bullet_head 다음에 오는 non-bullet은 continuation 가능성
        # 단, incomplete_score >= 1 이어야 함
        if incomplete_score >= 1:
            has_semantic_signal = True
            semantic_reason = f"bullet_continuation({incomplete_reason})"

    # NOTE: curr 단어 자체로 병합 결정하지 않음
    # "연구"를 병합하는 이유는 prev가 "관한"으로 끝나서 (strong_incomplete +3)
    # incomplete_score >= 2 조건(신호 1)을 충족하기 때문임

    # 의미적 신호 없으면 즉시 거부
    if not has_semantic_signal:
        # 디버그 로그 (bullet 관련이거나 score가 높을 것 같은 경우만)
        is_bullet_context = prev_type in {"bullet_head", "bullet_candidate"}
        if is_bullet_context or is_ocr_fragment:
            print(f"  [NoSemanticSignal] prev[{prev_type}]: '{prev_text[:20]}' → curr: '{curr_text[:20]}'")
            print(f"    incomplete={incomplete_score}({incomplete_reason}), ocr_frag={is_ocr_fragment}")
        return False, "no_semantic_signal"

    # ========================================
    # 의미적 신호가 있는 경우에만 레이아웃 점수 계산
    # ========================================

    score_details = {}
    merge_score = 0

    # 4.1 Y 간격 체크 (상대값: prev_h 기준)
    y_gap = curr_bbox[1] - prev_bbox[3]
    max_y_gap = prev_h * cfg("block.continuation_y_gap_ratio", 1.2) if prev_h > 0 else 40
    y_ok = -5 <= y_gap <= max_y_gap
    if y_ok:
        merge_score += 2
    score_details["y_gap"] = f"{y_gap:.0f}px (max={max_y_gap:.0f}) → {'+2' if y_ok else '+0'}"

    # 4.2 X 정렬 체크 (bullet_head는 content_x 기준)
    if prev_type == "bullet_head" and starts_with_bullet(prev_text):
        prev_content_x = estimate_text_start_after_bullet(prev_region)
        x_diff = abs(curr_bbox[0] - prev_content_x)
        score_details["x_ref"] = f"bullet content_x={prev_content_x:.0f}"
    else:
        prev_content_x = prev_bbox[0]
        x_diff = abs(curr_bbox[0] - prev_bbox[0])
        score_details["x_ref"] = f"bbox[0]={prev_bbox[0]:.0f}"

    max_x_diff = max(prev_h * 2, page_w * cfg("block.continuation_x_diff_ratio", 0.05)) if page_w > 0 else 80
    x_ok = x_diff < max_x_diff
    if x_ok:
        merge_score += 2
    score_details["x_diff"] = f"{x_diff:.0f}px (max={max_x_diff:.0f}) → {'+2' if x_ok else '+0'}"

    # 4.3 높이 유사성 (상대값)
    height_ok = False
    if prev_h > 0 and curr_h > 0:
        height_ratio = min(prev_h, curr_h) / max(prev_h, curr_h)
        height_ok = height_ratio > 0.7
        if height_ok:
            merge_score += 1
        score_details["height"] = f"ratio={height_ratio:.2f} → {'+1' if height_ok else '+0'}"
    else:
        score_details["height"] = "skip (h=0)"

    # 4.4 불완전 문장 점수 (의미적 신호의 강도)
    merge_score += incomplete_score
    score_details["incomplete"] = f"+{incomplete_score}({incomplete_reason})"

    # 4.5 OCR fragment 보너스 (+1, 조건부)
    if is_ocr_fragment and y_ok and x_ok:
        merge_score += 1
        score_details["ocr_fragment"] = "+1"
    else:
        score_details["ocr_fragment"] = "+0"

    # NOT_BULLET은 점수가 아닌 필터로만 사용 (이미 위에서 처리됨)
    # curr가 bullet이면 이미 "new_bullet_head"로 거부됨
    score_details["semantic"] = semantic_reason

    # continuation 병합 결정 (threshold 기반)
    continuation_threshold = cfg("block.continuation_merge_threshold", 6)

    # OCR fragment는 threshold 완화 (4점)
    if is_ocr_fragment:
        continuation_threshold = 4

    # 상세 로그 출력
    should_log = merge_score >= 3 or prev_type in {"bullet_head", "bullet_candidate"} or is_ocr_fragment
    if should_log:
        status = "✓MERGE" if merge_score >= continuation_threshold else f"✗({merge_score}<{continuation_threshold})"
        fragment_info = f" [OCR_FRAG]" if is_ocr_fragment else ""
        print(f"  [ContScore] {merge_score}/{continuation_threshold} {status}{fragment_info}")
        print(f"    prev[{prev_type}]: '{prev_text[:25]}' → curr: '{curr_text[:25]}'")
        print(f"    semantic: {score_details['semantic']}")
        print(f"    y: {score_details['y_gap']} | x: {score_details['x_diff']}")
        print(f"    h: {score_details['height']} | incomplete: {score_details['incomplete']} | ocr_frag: {score_details['ocr_fragment']}")

    if merge_score >= continuation_threshold:
        safety_result = check_merge_safety(current_block_regions, curr_region, image_size, all_regions)
        if safety_result["safe"]:
            print(f"    → MERGE!")
            return True, f"continuation_score_{merge_score}"
        else:
            print(f"    → BLOCKED by safety: {safety_result['reason']}")

    # 5. 타입별 특수 로직으로 병합 제안
    proposed = False
    reason = ""

    # bullet_candidate 승격
    if prev_type == "bullet_candidate" and curr_type == "bullet_continuation":
        if is_bullet_continuation(prev_region, curr_region):
            prev_region["_original_type"] = "bullet_candidate"
            prev_region["_type"] = "bullet_head"
            prev_region["_promoted_from"] = "bullet_candidate"
            proposed = True
            reason = "bullet_candidate_promoted"

    # bullet_candidate는 이전 block에 붙이지 않음 (보수적 정책)
    elif curr_type == "bullet_candidate":
        return False, "new_bullet_candidate"

    # 일반 bullet_continuation 처리
    elif curr_type == "bullet_continuation" and prev_type in {"bullet_head", "bullet_continuation"}:
        if is_bullet_continuation(prev_region, curr_region):
            proposed = True
            reason = "bullet_continuation"

    # bullet_head 다음에 continuation 가능
    elif prev_type == "bullet_head" and not starts_with_bullet(curr_text):
        if is_bullet_continuation(prev_region, curr_region):
            proposed = True
            reason = "bullet_head_continuation"

    elif prev_type == "title" and curr_type == "title":
        if is_same_title_block(prev_region, curr_region):
            proposed = True
            reason = "same_title"

    elif prev_type == "table_cell" and curr_type == "table_cell":
        if is_same_table_cell(prev_region, curr_region):
            proposed = True
            reason = "same_table_cell"

    elif prev_type == "affiliation" and curr_type == "affiliation":
        if is_same_affiliation(prev_region, curr_region):
            proposed = True
            reason = "same_affiliation"

    # else 블록 제거: paragraph 등은 섹션 4의 의미적 신호 기반 병합으로만 처리
    # calculate_merge_score는 레이아웃만으로 병합하므로 오병합 위험이 높음

    if not proposed:
        return False, "not_proposed"

    # 6. 모든 병합에 safety check 적용
    safety_result = check_merge_safety(current_block_regions, curr_region, image_size, all_regions)
    if not safety_result["safe"]:
        return False, safety_result["reason"]

    return True, reason


def check_merge_safety(
    current_block_regions: list[dict],
    curr_region: dict,
    image_size: tuple[int, int],
    all_regions: list[dict]
) -> dict:
    """병합 안전성 종합 체크"""
    page_w, page_h = image_size

    # 1. union bbox 면적 체크
    if would_exceed_bbox_limit(current_block_regions, curr_region, image_size):
        return {"safe": False, "reason": "union_bbox_area_exceeded"}

    # 2. union bbox 높이 체크
    union = calculate_union_bbox(current_block_regions + [curr_region])
    union_h = union[3] - union[1]
    max_height_ratio = cfg("block.max_union_height_ratio", 0.25)
    if page_h > 0 and union_h / page_h > max_height_ratio:
        return {"safe": False, "reason": "union_bbox_height_exceeded"}

    # 3. 수직 gap 체크
    if current_block_regions:
        last_bbox = current_block_regions[-1].get("bbox", [0, 0, 0, 0])
        curr_bbox = curr_region.get("bbox", [0, 0, 0, 0])
        gap = curr_bbox[1] - last_bbox[3]
        last_h = last_bbox[3] - last_bbox[1]
        max_gap_ratio = cfg("block.max_y_gap_ratio", 0.05)
        if page_h > 0 and gap / page_h > max_gap_ratio:
            return {"safe": False, "reason": "vertical_gap_too_large"}

    # 4. 중간에 방해 region 체크
    if cfg("block.check_intervening_regions", True):
        if has_intervening_region(current_block_regions, curr_region, all_regions):
            return {"safe": False, "reason": "intervening_region_exists"}

    return {"safe": True, "reason": ""}


def has_intervening_region(
    current_block_regions: list[dict],
    curr_region: dict,
    all_regions: list[dict]
) -> bool:
    """병합 시 중간에 방해 region이 있는지 체크"""
    if not current_block_regions:
        return False

    union = calculate_union_bbox(current_block_regions + [curr_region])
    block_region_ids = set(r.get("_sorted_index") for r in current_block_regions)
    block_region_ids.add(curr_region.get("_sorted_index"))

    # 방해 타입만 체크
    blocking_types = {"diagram_label", "table_cell", "code", "formula"}
    min_overlap_ratio = cfg("block.intervening_overlap_ratio", 0.3)

    for r in all_regions:
        if r.get("_sorted_index") in block_region_ids:
            continue
        if r.get("_type") not in blocking_types:
            continue

        overlap = calculate_overlap_ratio(r.get("bbox", [0, 0, 0, 0]), union)
        if overlap >= min_overlap_ratio:
            return True

    return False


def would_exceed_bbox_limit(
    current_regions: list[dict],
    new_region: dict,
    image_size: tuple[int, int]
) -> bool:
    """병합 시 면적 한도 초과 여부"""
    page_w, page_h = image_size
    page_area = page_w * page_h

    if page_area == 0:
        return False

    union = calculate_union_bbox(current_regions + [new_region])
    union_area = (union[2] - union[0]) * (union[3] - union[1])

    max_ratio = cfg("block.max_union_area_ratio", 0.15)
    return union_area / page_area > max_ratio


def calculate_union_bbox(regions: list[dict]) -> list:
    """region들의 union bbox 계산"""
    if not regions:
        return [0, 0, 0, 0]

    bboxes = [r.get("bbox", [0, 0, 0, 0]) for r in regions]
    x1 = min(b[0] for b in bboxes)
    y1 = min(b[1] for b in bboxes)
    x2 = max(b[2] for b in bboxes)
    y2 = max(b[3] for b in bboxes)

    return [x1, y1, x2, y2]


def calculate_overlap_ratio(bbox1: list, bbox2: list) -> float:
    """두 bbox의 겹침 비율 계산"""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])

    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])

    if area1 == 0:
        return 0.0

    return intersection / area1


def is_bullet_continuation(prev_region: dict, curr_region: dict) -> bool:
    """bullet continuation 여부 판단"""
    prev_bbox = prev_region.get("bbox", [0, 0, 0, 0])
    curr_bbox = curr_region.get("bbox", [0, 0, 0, 0])

    # 1. y 간격이 가까움
    if not close_y_gap(prev_bbox, curr_bbox):
        return False

    # 2. curr가 bullet로 시작하면 새 bullet_head
    if starts_with_bullet(curr_region.get("ocr_text", "")):
        return False

    # 3. x 위치 판정
    curr_x = curr_bbox[0]
    prev_text_x = estimate_text_start_after_bullet(prev_region)
    indent_tolerance = 80

    x_ok = (
        abs(curr_x - prev_text_x) < indent_tolerance
        or (prev_text_x <= curr_x <= prev_text_x + indent_tolerance)
    )

    if not x_ok:
        return False

    # 4. font height가 비슷해야 함
    prev_h = prev_bbox[3] - prev_bbox[1]
    curr_h = curr_bbox[3] - curr_bbox[1]
    if prev_h > 0 and abs(prev_h - curr_h) > prev_h * 0.3:
        return False

    return True


def close_y_gap(bbox1: list, bbox2: list) -> bool:
    """두 bbox가 y방향으로 가까운지"""
    gap = bbox2[1] - bbox1[3]
    height = bbox1[3] - bbox1[1]

    if height <= 0:
        return gap < 50

    # gap이 높이의 1.5배 이내
    return gap < height * 1.5


def estimate_text_start_after_bullet(region: dict) -> int:
    """bullet 기호 이후 텍스트 시작 x 좌표 추정"""
    bbox = region.get("bbox", [0, 0, 0, 0])
    text = region.get("ocr_text", "")
    height = bbox[3] - bbox[1]

    if starts_with_bullet(text):
        # height 기반 추정 (대략 글자 1개 너비)
        return bbox[0] + int(height * 1.5)

    return bbox[0]


def is_same_title_block(prev_region: dict, curr_region: dict) -> bool:
    """같은 title 블록인지 (줄바꿈된 제목)"""
    prev_bbox = prev_region.get("bbox", [0, 0, 0, 0])
    curr_bbox = curr_region.get("bbox", [0, 0, 0, 0])

    # y 간격 체크
    if not close_y_gap(prev_bbox, curr_bbox):
        return False

    # x 위치가 비슷 (중앙 정렬된 제목)
    prev_center = (prev_bbox[0] + prev_bbox[2]) / 2
    curr_center = (curr_bbox[0] + curr_bbox[2]) / 2

    return abs(prev_center - curr_center) < 100


def is_same_table_cell(prev_region: dict, curr_region: dict) -> bool:
    """같은 table cell인지"""
    # 같은 셀 내 여러 줄인 경우
    prev_bbox = prev_region.get("bbox", [0, 0, 0, 0])
    curr_bbox = curr_region.get("bbox", [0, 0, 0, 0])

    # x 범위가 겹치고, y가 가까움
    x_overlap = min(prev_bbox[2], curr_bbox[2]) - max(prev_bbox[0], curr_bbox[0])
    prev_width = prev_bbox[2] - prev_bbox[0]

    if prev_width > 0 and x_overlap / prev_width < 0.7:
        return False

    return close_y_gap(prev_bbox, curr_bbox)


def is_same_affiliation(prev_region: dict, curr_region: dict) -> bool:
    """같은 소속 블록인지"""
    return close_y_gap(
        prev_region.get("bbox", [0, 0, 0, 0]),
        curr_region.get("bbox", [0, 0, 0, 0])
    )


def calculate_merge_score(prev_region: dict, curr_region: dict) -> int:
    """병합 점수 계산 (paragraph 등 일반 영역용)"""
    score = 0
    prev_bbox = prev_region.get("bbox", [0, 0, 0, 0])
    curr_bbox = curr_region.get("bbox", [0, 0, 0, 0])

    # y 간격이 가까우면 +3
    if close_y_gap(prev_bbox, curr_bbox):
        score += 3

    # x 정렬이 비슷하면 +2
    if abs(prev_bbox[0] - curr_bbox[0]) < 30:
        score += 2

    # 높이가 비슷하면 +1
    prev_h = prev_bbox[3] - prev_bbox[1]
    curr_h = curr_bbox[3] - curr_bbox[1]
    if prev_h > 0 and abs(prev_h - curr_h) < prev_h * 0.2:
        score += 1

    return score


def save_blocks(blocks: list[dict], output_path: str):
    """블록 저장"""
    import json

    # 저장용 복사 (regions 참조 제거)
    blocks_for_save = []
    for block in blocks:
        block_copy = {k: v for k, v in block.items() if k != "regions"}
        blocks_for_save.append(block_copy)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "blocks": blocks_for_save,
            "count": len(blocks)
        }, f, ensure_ascii=False, indent=2)
