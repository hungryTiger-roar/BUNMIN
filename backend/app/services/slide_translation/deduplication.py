"""
OCR ↔ Image Text Deduplication (v2)

OCR 영역과 이미지 텍스트 영역의 중복을 제거

중복 제거 기준:
1. OCR이 이미지 영역 내부에 있으면 제거
2. OCR과 image_text의 bbox IoU + text similarity 기반 중복 제거
"""
import re
from typing import Optional
from .config import cfg


def normalize_for_comparison(text: str) -> str:
    """비교용 텍스트 정규화"""
    if not text:
        return ""
    text = re.sub(r'\s+', '', text)
    text = re.sub(r'[^\w가-힣]', '', text)
    return text.lower()


def calculate_text_similarity(text1: str, text2: str) -> float:
    """두 텍스트의 유사도 계산 (0.0 ~ 1.0)"""
    norm1 = normalize_for_comparison(text1)
    norm2 = normalize_for_comparison(text2)
    if not norm1 or not norm2:
        return 0.0
    if norm1 == norm2:
        return 1.0
    if norm1 in norm2:
        return 0.8 + 0.2 * (len(norm1) / len(norm2))
    if norm2 in norm1:
        return 0.8 + 0.2 * (len(norm2) / len(norm1))
    set1 = set(norm1)
    set2 = set(norm2)
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def calculate_bbox_iou(bbox1: list, bbox2: list) -> float:
    """두 bbox의 IoU 계산"""
    if not bbox1 or not bbox2:
        return 0.0
    x1, y1 = max(bbox1[0], bbox2[0]), max(bbox1[1], bbox2[1])
    x2, y2 = min(bbox1[2], bbox2[2]), min(bbox1[3], bbox2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersection = (x2 - x1) * (y2 - y1)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    union = area1 + area2 - intersection
    return intersection / union if union > 0 else 0.0


def is_duplicate_region(
    region1: dict,
    region2: dict,
    iou_threshold: float = 0.5,
    text_sim_threshold: float = 0.7
) -> tuple[bool, dict]:
    """두 영역이 중복인지 판단 (IoU + text similarity)"""
    bbox1 = region1.get("bbox") or region1.get("bbox_page")
    bbox2 = region2.get("bbox") or region2.get("bbox_page")
    text1 = region1.get("ocr_text") or region1.get("text", "")
    text2 = region2.get("ocr_text") or region2.get("text", "")

    iou = calculate_bbox_iou(bbox1, bbox2)
    text_sim = calculate_text_similarity(text1, text2)

    match_info = {
        "iou": iou,
        "text_similarity": text_sim,
        "combined_score": (iou + text_sim) / 2
    }

    if (iou >= iou_threshold and text_sim >= text_sim_threshold) or iou >= 0.9 or text_sim >= 0.95:
        return True, match_info
    return False, match_info


def is_bbox_inside(inner: list, outer: list, threshold: float = 0.7) -> bool:
    """inner bbox가 outer bbox 내부에 있는지 판단"""
    if not inner or not outer:
        return False
    ix1, iy1, ix2, iy2 = inner
    ox1, oy1, ox2, oy2 = outer
    overlap_x1 = max(ix1, ox1)
    overlap_y1 = max(iy1, oy1)
    overlap_x2 = min(ix2, ox2)
    overlap_y2 = min(iy2, oy2)
    if overlap_x2 <= overlap_x1 or overlap_y2 <= overlap_y1:
        return False
    overlap_area = (overlap_x2 - overlap_x1) * (overlap_y2 - overlap_y1)
    inner_area = (ix2 - ix1) * (iy2 - iy1)
    if inner_area == 0:
        return False
    return overlap_area / inner_area >= threshold


def deduplicate_ocr_and_image_texts(
    ocr_regions: list[dict],
    image_regions: list[dict],
    image_texts: list[dict]
) -> tuple[list[dict], list[dict], dict]:
    """OCR 영역과 이미지 텍스트 영역의 중복 제거

    규칙:
    1. OCR 영역이 image_region 내부에 있으면 → OCR에서 제거
       (단, 전체 페이지를 덮는 이미지 영역은 제외)
    2. OCR과 image_text가 위치+텍스트 유사하면 → OCR 우선 유지, image_text 제거
    """
    threshold = cfg("image_text.overlap_threshold", 0.7)
    
    # 전체 페이지를 덮는 이미지 영역 필터링 (배경 이미지 등)
    # 페이지 면적의 80% 이상을 차지하면 제외
    MAX_IMAGE_AREA_RATIO = 0.8
    filtered_image_regions = []
    for img_region in image_regions:
        img_bbox = img_region.get("bbox")
        if img_bbox:
            img_area = (img_bbox[2] - img_bbox[0]) * (img_bbox[3] - img_bbox[1])
            # 일반적인 슬라이드 크기 기준 (1920x1080 또는 1440x1080 등)
            # bbox가 (0,0)에서 시작하고 면적이 크면 전체 배경으로 간주
            is_full_page = (
                img_bbox[0] <= 10 and img_bbox[1] <= 10 and  # 좌상단 근처에서 시작
                img_area > 1000000  # 대략 1000x1000 이상 면적
            )
            if is_full_page:
                print(f"[Dedup] 전체 페이지 이미지 영역 제외: {img_region.get('id')} bbox={img_bbox}")
                continue
        filtered_image_regions.append(img_region)

    deduplicated_ocr = []
    removed_ocr = []

    # Phase 1: OCR이 이미지 영역 내부에 있는지 체크
    for ocr_region in ocr_regions:
        ocr_bbox = ocr_region.get("bbox")
        if not ocr_bbox:
            deduplicated_ocr.append(ocr_region)
            continue

        is_inside_image = False
        parent_image_id = None

        ocr_page = ocr_region.get("page_no")

        for img_region in filtered_image_regions:
            img_bbox = img_region.get("bbox")
            img_page = img_region.get("page_no")

            # 같은 페이지의 영역만 비교
            if ocr_page != img_page:
                continue

            if img_bbox and is_bbox_inside(ocr_bbox, img_bbox, threshold):
                is_inside_image = True
                parent_image_id = img_region["id"]
                break

        if is_inside_image:
            ocr_region["_dedup_status"] = "removed"
            ocr_region["_removed_by"] = parent_image_id
            ocr_region["_skip_reason"] = "inside_image_region"
            removed_ocr.append(ocr_region)
        else:
            ocr_region["_dedup_status"] = "kept"
            deduplicated_ocr.append(ocr_region)

    # Phase 2: OCR과 image_text의 IoU + text similarity 기반 중복 제거
    deduplicated_image_texts = []
    removed_image_texts = []
    dup_matches = []

    for img_text in image_texts:
        is_dup = False
        matched_ocr = None
        best_match_info = None
        img_text_page = img_text.get("page_no")

        for ocr in deduplicated_ocr:
            # 같은 페이지의 영역만 비교
            if ocr.get("page_no") != img_text_page:
                continue

            is_duplicate, match_info = is_duplicate_region(ocr, img_text)
            if is_duplicate:
                is_dup = True
                matched_ocr = ocr
                best_match_info = match_info
                break

        if is_dup:
            img_text["_dedup_status"] = "removed"
            img_text["_duplicate_of_ocr"] = matched_ocr.get("id") or matched_ocr.get("ocr_text", "")[:20]
            img_text["_match_info"] = best_match_info
            img_text["_skip_reason"] = "duplicate_of_ocr"
            removed_image_texts.append(img_text)
            dup_matches.append({
                "image_text": img_text.get("text", ""),
                "ocr_text": matched_ocr.get("ocr_text", ""),
                "iou": best_match_info["iou"],
                "text_similarity": best_match_info["text_similarity"],
            })
        else:
            img_text["_dedup_status"] = "kept"
            deduplicated_image_texts.append(img_text)

    report = {
        "ocr_total": len(ocr_regions),
        "ocr_kept": len(deduplicated_ocr),
        "ocr_removed": len(removed_ocr),
        "image_text_total": len(image_texts),
        "image_text_kept": len(deduplicated_image_texts),
        "image_text_removed_as_dup": len(removed_image_texts),
        "removed_ocr_details": [
            {"ocr_text": r.get("ocr_text", ""), "ocr_bbox": r.get("bbox"), "removed_by": r.get("_removed_by")}
            for r in removed_ocr
        ],
        "removed_image_text_duplicates": dup_matches,
    }

    return deduplicated_ocr, deduplicated_image_texts, report


def save_dedup_results(
    ocr_regions: list[dict],
    image_texts: list[dict],
    report: dict,
    output_dir: str
):
    """중복 제거 결과 저장"""
    import json
    import os

    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "regions.deduplicated.json"), "w", encoding="utf-8") as f:
        json.dump({"regions": ocr_regions, "count": len(ocr_regions)}, f, ensure_ascii=False, indent=2)

    with open(os.path.join(output_dir, "image_texts.deduplicated.json"), "w", encoding="utf-8") as f:
        json.dump({"image_texts": image_texts, "count": len(image_texts)}, f, ensure_ascii=False, indent=2)

    with open(os.path.join(output_dir, "deduplication_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
