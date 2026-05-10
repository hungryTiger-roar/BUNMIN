"""
Reading Order Sorting

페이지 내 region들을 읽기 순서대로 정렬

입력:
- regions.classified.json

출력:
- regions.sorted.json

정렬 방식:
1. full-width region 분리 (제목, footer 등)
2. 컬럼/y-band 기반 정렬
3. _sorted_index 부여
"""
import re
from typing import Optional
from .config import cfg
from .region_classification import starts_with_bullet


def sort_regions_reading_order(
    regions: list[dict],
    image_size: tuple[int, int],
    page_layout: Optional[str] = None
) -> list[dict]:
    """읽기 순서로 정렬 (full-width → column/y-band)"""
    page_w, page_h = image_size

    # 1. full-width region 분리
    full_width = []
    column_candidates = []

    full_width_ratio = cfg("block.full_width_ratio", 0.55)

    for r in regions:
        bbox = r.get("bbox")
        if not bbox:
            column_candidates.append(r)
            continue

        width = bbox[2] - bbox[0]
        y_top = bbox[1]
        text = r.get("ocr_text", "")
        region_type = r.get("_type", "")

        # bullet으로 시작하는 region은 full_width로 분류하지 않음
        # (정의형 bullet은 폭이 넓어도 본문 컨텐츠임)
        is_bullet = starts_with_bullet(text)

        # bullet_candidate (continuation line)도 full_width에서 제외
        # 이들은 폭이 넓어도 본문 컨텐츠의 연속임
        is_continuation = region_type == "bullet_candidate"

        # 페이지 중간에 위치한 wide region은 full_width로 분류하지 않음
        # (title/footer가 아닌 본문 continuation일 가능성 높음)
        is_middle_of_page = page_h > 0 and 0.15 < y_top / page_h < 0.85

        is_wide = page_w > 0 and width / page_w > full_width_ratio

        if is_wide and not is_bullet and not is_continuation and not is_middle_of_page:
            full_width.append(r)
        else:
            column_candidates.append(r)

    # 2. full-width는 y순 정렬
    full_width_sorted = sorted(full_width, key=lambda r: r.get("bbox", [0, 0, 0, 0])[1])

    # 3. page_layout에 따라 정렬 방식 결정
    if page_layout == "diagram" or page_layout == "mixed":
        # y-band 방식
        column_sorted = sort_by_y_bands(column_candidates, page_w)
    else:
        # 기본: 좌/우 컬럼 방식
        column_sorted = sort_by_columns(column_candidates, page_w)

    # 4. 상단 full-width + columns + 하단 full-width
    result = []

    for r in full_width_sorted:
        bbox = r.get("bbox", [0, 0, 0, 0])
        if bbox[1] < page_h * 0.3:  # 상단 full-width (제목)
            result.append(r)

    result.extend(column_sorted)

    for r in full_width_sorted:
        bbox = r.get("bbox", [0, 0, 0, 0])
        if bbox[1] >= page_h * 0.3:  # 하단 full-width (footer)
            result.append(r)

    # 5. sorted index 부여
    for i, r in enumerate(result):
        r["_sorted_index"] = i

    return result


def _is_ocr_fragment_like(text: str) -> bool:
    """OCR fragment로 보이는지 판단 (reading order용)

    True 케이스:
    - "직 면", "희 소 성" 등 한글 1글자들이 공백으로 분리된 경우
    - 1자 한글만 있는 경우
    """
    if not text:
        return False

    stripped = text.strip()
    if not stripped:
        return False

    no_space = stripped.replace(" ", "")

    # 조건 1: 한글 1글자들이 공백으로 분리 ("직 면", "희 소 성")
    if re.match(r'^[가-힣](\s+[가-힣])+$', stripped):
        return True

    # 조건 2: 2-3자 한글인데 공백이 포함된 경우
    if len(no_space) <= 3 and ' ' in stripped:
        if re.match(r'^[가-힣]+$', no_space):
            return True

    # 조건 3: 1자 한글만 있는 경우
    if len(no_space) == 1 and re.match(r'^[가-힣]$', no_space):
        return True

    return False


def _attach_short_fragments(regions: list[dict]) -> list[dict]:
    """짧은 OCR fragment를 visual predecessor에 attach (metadata 기반 stable reorder)

    1단계: 각 fragment에 _attach_after_id metadata 부여
    2단계: metadata 기반으로 stable sort

    예: "■ 본문 텍스트가 이어지다가 다음 줄로" → "넘어감"
    """
    if len(regions) < 2:
        return regions

    # 각 region에 고유 ID 부여 (없으면)
    for i, r in enumerate(regions):
        if "_temp_id" not in r:
            r["_temp_id"] = i

    # 1단계: fragment들에 _attach_after_id 부여
    for r in regions:
        text = r.get("ocr_text", "").strip()

        # OCR fragment인지 체크
        if not _is_ocr_fragment_like(text):
            continue

        print(f"[ReadingOrder] Evaluating OCR fragment: '{text}'")

        bbox = r.get("bbox")
        if not bbox:
            continue

        # visual predecessor 찾기
        best_pred = None
        best_score = 0

        for pred in regions:
            if pred is r:
                continue

            pred_bbox = pred.get("bbox")
            if not pred_bbox:
                continue

            pred_text = pred.get("ocr_text", "").strip()
            if not pred_text:
                continue

            # 점수 계산
            score = 0

            # 1. Y 위치 근접성 (위에 있어야 함)
            y_gap = bbox[1] - pred_bbox[3]  # current top - pred bottom
            if y_gap < -10:  # pred가 확실히 아래에 있음 (약간의 overlap 허용)
                continue
            if y_gap > 80:  # 너무 멀면 제외
                continue

            # y_gap 점수 (가까울수록 높음)
            if y_gap <= 15:
                score += 5
            elif y_gap <= 30:
                score += 3
            elif y_gap <= 50:
                score += 2

            # 2. X 위치 유사성 (같은 컬럼)
            x_diff = abs(bbox[0] - pred_bbox[0])
            if x_diff <= 50:
                score += 3
            elif x_diff <= 100:
                score += 1

            # 3. predecessor가 미완성 문장인지 (한국어 조사/어미)
            if pred_text.endswith(("에", "를", "을", "의", "와", "과", "에서", "으로", "로", "이", "가")):
                score += 4  # 한국어 조사로 끝남 → continuation 가능성 높음
            elif pred_text.endswith((",", "，")):
                score += 3

            # 4. predecessor가 bullet으로 시작하면 가산 (starts_with_bullet 사용)
            if starts_with_bullet(pred_text):
                score += 2

            if score > best_score:
                best_score = score
                best_pred = pred
                # 디버그: OCR fragment의 best candidate 정보
                if score >= 5:
                    print(f"  [FragmentDebug] '{text}' ← '{pred_text[:20]}...' score={score} (y={y_gap:.0f}, x_diff={x_diff:.0f})")

        # threshold: 8점 이상이면 attach metadata 부여
        if best_pred is not None and best_score >= 8:
            r["_attach_after_id"] = best_pred["_temp_id"]
            r["_attach_score"] = best_score
            pred_text_short = best_pred.get("ocr_text", "")[:30]
            print(f"[ReadingOrder] Will attach '{text}' after '{pred_text_short}...' (score={best_score})")
        elif best_pred is not None:
            # 디버그: threshold 미달 케이스
            pred_text_short = best_pred.get("ocr_text", "")[:25]
            print(f"[ReadingOrder] Fragment '{text}' best_pred='{pred_text_short}...' score={best_score}<8 (NOT attached)")

    # 2단계: metadata 기반 stable sort
    # _attach_after_id가 있는 region은 해당 predecessor 바로 뒤로
    result = []
    attached_ids = {r["_temp_id"] for r in regions if "_attach_after_id" in r}

    for r in regions:
        # attach될 fragment는 스킵 (나중에 predecessor 뒤에 삽입)
        if r["_temp_id"] in attached_ids:
            continue

        result.append(r)

        # 이 region을 predecessor로 하는 fragment들 찾아서 바로 뒤에 삽입
        for frag in regions:
            if frag.get("_attach_after_id") == r["_temp_id"]:
                result.append(frag)

    # cleanup: 임시 metadata 제거
    for r in result:
        r.pop("_temp_id", None)
        r.pop("_attach_after_id", None)
        r.pop("_attach_score", None)

    return result


def sort_by_columns(regions: list[dict], page_w: int) -> list[dict]:
    """좌/우 컬럼 기반 정렬

    NOTE: center_x 대신 bbox[0] (left edge) 기준 사용
    넓은 bullet이 center_x 때문에 잘못 분류되는 것 방지
    """
    if not regions:
        return []

    # 컬럼 분리 기준점 (페이지 중앙보다 약간 오른쪽)
    column_threshold = page_w * 0.4  # left edge가 40% 이상이면 오른쪽 컬럼

    left_column = []
    right_column = []

    for r in regions:
        bbox = r.get("bbox", [0, 0, 0, 0])
        left_x = bbox[0]  # left edge 기준

        if left_x < column_threshold:
            left_column.append(r)
        else:
            right_column.append(r)

    # 각 컬럼 내에서 y순 정렬
    left_column.sort(key=lambda r: r.get("bbox", [0, 0, 0, 0])[1])
    right_column.sort(key=lambda r: r.get("bbox", [0, 0, 0, 0])[1])

    # 왼쪽 컬럼 먼저, 그다음 오른쪽
    result = left_column + right_column

    # 후처리: 짧은 fragment를 visual predecessor에 attach
    result = _attach_short_fragments(result)

    return result


def sort_by_y_bands(regions: list[dict], page_w: int) -> list[dict]:
    """y-band 기반 정렬 (다이어그램/혼합 레이아웃용)

    같은 y 대역에 있는 region들은 x순으로 정렬
    """
    if not regions:
        return []

    # y 좌표로 1차 정렬
    sorted_by_y = sorted(regions, key=lambda r: r.get("bbox", [0, 0, 0, 0])[1])

    # y-band로 그룹화
    bands = []
    current_band = []
    band_y_max = 0

    band_threshold = 30  # y 차이가 이 이하면 같은 band

    for r in sorted_by_y:
        bbox = r.get("bbox", [0, 0, 0, 0])
        y = bbox[1]

        if not current_band:
            current_band = [r]
            band_y_max = bbox[3]
        elif y < band_y_max + band_threshold:
            current_band.append(r)
            band_y_max = max(band_y_max, bbox[3])
        else:
            bands.append(current_band)
            current_band = [r]
            band_y_max = bbox[3]

    if current_band:
        bands.append(current_band)

    # 각 band 내에서 x순 정렬
    result = []
    for band in bands:
        band_sorted = sorted(band, key=lambda r: r.get("bbox", [0, 0, 0, 0])[0])
        result.extend(band_sorted)

    # 후처리: 짧은 fragment를 visual predecessor에 attach
    result = _attach_short_fragments(result)

    return result


def estimate_page_layout(regions: list[dict], image_size: tuple[int, int]) -> str:
    """페이지 레이아웃 추정"""
    page_w, page_h = image_size

    if not regions:
        return "single_column"

    # 통계 수집
    has_two_columns = False
    diagram_count = 0
    table_count = 0

    mid_x = page_w / 2
    left_count = 0
    right_count = 0

    for r in regions:
        bbox = r.get("bbox", [0, 0, 0, 0])
        center_x = (bbox[0] + bbox[2]) / 2
        width = bbox[2] - bbox[0]

        # 좁은 영역만 컬럼 판단에 사용
        if page_w > 0 and width / page_w < 0.5:
            if center_x < mid_x - 50:
                left_count += 1
            elif center_x > mid_x + 50:
                right_count += 1

        # 타입 체크
        region_type = r.get("_type", "")
        if region_type == "diagram_label":
            diagram_count += 1
        elif region_type == "table_cell":
            table_count += 1

    # 2단 컬럼 체크
    if left_count >= 3 and right_count >= 3:
        has_two_columns = True

    # 레이아웃 결정
    if diagram_count >= 3:
        return "diagram"
    if table_count >= 5:
        return "table"
    if has_two_columns:
        return "two_column_text"

    return "single_column"


def save_sorted_regions(regions: list[dict], output_path: str):
    """정렬된 region 저장"""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "regions": regions,
            "count": len(regions)
        }, f, ensure_ascii=False, indent=2)
