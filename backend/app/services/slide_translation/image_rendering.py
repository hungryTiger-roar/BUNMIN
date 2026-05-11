"""
Image Inpainting + Rendering (Phase 2)

이미지 내 텍스트 영역 인페인팅 및 영어 텍스트 렌더링

핵심 원칙:
- erase_bbox: original_bbox + padding (원본 한글만 지움)
- render_bbox: final_bbox (확장된 영역에 렌더링)
- quality check: font_scale은 original 기준, overflow는 final 기준
"""
import os
import re
import json
from typing import Optional, Any
from PIL import Image, ImageDraw, ImageFont
import numpy as np


def contains_korean(text: str) -> bool:
    """텍스트에 한글이 포함되어 있는지 확인"""
    if not text:
        return False
    return bool(re.search(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', text))


from .render_role import (
    infer_render_role,
    get_font_size_for_role,
    get_bg_brightness,
    start_render_report,
    get_current_report,
    finish_render_report,
)

# 상수 - 한글 완전 제거를 위한 패딩 증가
PADDING_RATIO = 0.25  # 15% → 25% (한글 완전 제거)
MIN_PADDING = 8       # 4 → 8
MAX_PADDING = 40      # 20 → 40
SOLID_BG_THRESHOLD = 15
INPAINT_RADIUS = 7
TITLE_INPAINT_RADIUS = 6
TITLE_ROLES = {"title", "heading", "cover"}
TITLE_PADDING_RATIO = 0.20  # 12% → 20%


# ============================================================================
# 유틸리티 함수들
# ============================================================================

def _normalize_bbox(bbox: list, image_size: tuple) -> tuple:
    """bbox 정규화"""
    w, h = image_size
    x1 = max(0, min(int(bbox[0]), w - 1))
    y1 = max(0, min(int(bbox[1]), h - 1))
    x2 = max(x1 + 1, min(int(bbox[2]), w))
    y2 = max(y1 + 1, min(int(bbox[3]), h))
    return x1, y1, x2, y2


def _bbox_intersection_ratio(bbox1: list, bbox2: list) -> float:
    """두 bbox의 겹침 비율 (bbox1 기준)"""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])

    if x1 >= x2 or y1 >= y2:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    bbox1_area = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])

    return intersection / bbox1_area if bbox1_area > 0 else 0.0


def _is_same_bbox(bbox1: list, bbox2: list, threshold: float = 0.95) -> bool:
    """두 bbox가 같은 블록인지 확인 (intersection ratio 기준)"""
    ratio1 = _bbox_intersection_ratio(bbox1, bbox2)
    ratio2 = _bbox_intersection_ratio(bbox2, bbox1)
    return ratio1 > threshold and ratio2 > threshold


def _is_region_empty_strict(img_np: np.ndarray, bbox: list) -> bool:
    """영역이 여백인지 확인 (확장 가능 여부 판단)

    Returns:
        True if region is light/uniform background (safe to expand)
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    h, w = img_np.shape[:2]

    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return True

    region = img_np[y1:y2, x1:x2]
    if region.size == 0:
        return True

    if len(region.shape) == 3:
        brightness = np.mean(0.299 * region[:,:,0] + 0.587 * region[:,:,1] + 0.114 * region[:,:,2])
        color_std = np.mean([np.std(region[:,:,i]) for i in range(3)])
    else:
        brightness = np.mean(region)
        color_std = np.std(region)

    # 완화된 조건: 연한 배경이면 확장 허용
    # brightness > 220: 연한 회색까지 허용
    # color_std < 40: 약간의 그라데이션까지 허용
    return brightness > 220 and color_std < 40


def _is_expansion_safe(
    expansion_bbox: list,
    occupied_bboxes: list,
    img_np: np.ndarray,
    current_idx: int
) -> tuple:
    """확장 영역이 안전한지 확인 (index 기반 자기 제외)"""
    # 1. 다른 블록과 겹침 체크
    for i, occ_bbox in enumerate(occupied_bboxes):
        if i == current_idx:
            continue

        overlap = _bbox_intersection_ratio(expansion_bbox, occ_bbox)
        # 15% 이상 겹치면 차단 (기존 5% → 15%로 완화)
        if overlap > 0.15:
            return False, f"overlaps_other_block_{overlap:.2f}"

    return True, "safe"


def _check_expansion_region_empty(
    expansion_bbox: list,
    original_bbox: list,
    img_np: np.ndarray
) -> tuple:
    """확장 영역이 비어있는지 확인"""
    # 왼쪽 확장
    if expansion_bbox[0] < original_bbox[0]:
        left = [expansion_bbox[0], expansion_bbox[1], original_bbox[0], expansion_bbox[3]]
        if not _is_region_empty_strict(img_np, left):
            return False, "left_not_empty"

    # 오른쪽 확장
    if expansion_bbox[2] > original_bbox[2]:
        right = [original_bbox[2], expansion_bbox[1], expansion_bbox[2], expansion_bbox[3]]
        if not _is_region_empty_strict(img_np, right):
            return False, "right_not_empty"

    # 아래쪽 확장
    if expansion_bbox[3] > original_bbox[3]:
        bottom = [expansion_bbox[0], original_bbox[3], expansion_bbox[2], expansion_bbox[3]]
        if not _is_region_empty_strict(img_np, bottom):
            return False, "bottom_not_empty"

    return True, "empty"


# ============================================================================
# 렌더링 시뮬레이션
# ============================================================================

def _wrap_text(text: str, font, max_width: int) -> list:
    """텍스트 줄바꿈"""
    if not text:
        return []

    words = text.split()
    if not words:
        return [text]

    lines = []
    current_line = []
    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)

    for word in words:
        test_line = ' '.join(current_line + [word])
        try:
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]
        except Exception:
            line_width = len(test_line) * 8

        if line_width <= max_width * 0.95:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]

    if current_line:
        lines.append(' '.join(current_line))

    return lines if lines else [text]


def _try_render_with_font(text: str, font_size: int, box_width: int, box_height: int, font_path: str = None) -> tuple:
    """폰트 크기로 렌더링 시뮬레이션"""
    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
        wrapped_lines = _wrap_text(text, font, box_width)
        line_height = font_size + 2
        total_height = len(wrapped_lines) * line_height
        fits = total_height <= box_height * 1.05
        return fits, wrapped_lines, total_height
    except Exception:
        return False, [text], box_height + 1


def _calculate_expanded_bbox_with_simulation(
    text: str,
    original_bbox: list,
    target_font_size: int,
    image_size: tuple,
    render_role: str,
    font_path: str,
    occupied_bboxes: list,
    img_np: np.ndarray,
    current_idx: int
) -> dict:
    """Render simulation 기반 bbox 확장 (안전 검사 + fallback)"""
    x1, y1, x2, y2 = original_bbox
    img_w, img_h = image_size
    box_width = x2 - x1
    box_height = y2 - y1

    result = {
        "final_bbox": list(original_bbox),
        "render_bbox": list(original_bbox),  # 렌더링 영역
        "erase_bbox": list(original_bbox),   # 인페인팅 영역 (원본 기준)
        "final_font_size": target_font_size,
        "wrapped_lines": [],
        "needs_review": False,
        "expansion_applied": False,
        "expansion_reason": "none",
        "expansion_safe": True,
        "used_fallback": False
    }

    # === Step 1: 목표 폰트로 원본 bbox에 맞는지 ===
    fits, wrapped_lines, _ = _try_render_with_font(text, target_font_size, box_width, box_height, font_path)
    if fits:
        result["wrapped_lines"] = wrapped_lines
        result["expansion_reason"] = "fits_original"
        return result

    # === Step 2: bbox 확장 계산 ===
    # 영어는 한글보다 1.5-2배 길어지므로 매우 공격적으로 확장
    right_margin = max(0, img_w - x2 - 10)  # 경계 마진 축소 (20→10)
    left_margin = max(0, x1 - 10)
    bottom_margin = max(0, img_h - y2 - 10)

    if render_role in ["title", "heading"]:
        # 제목: 좌우로 크게 확장, 아래로도 약간 확장 허용
        max_expand_w = min(right_margin + left_margin, int(box_width * 2.5))
        expand_left = min(left_margin, max_expand_w // 3)
        expand_right = min(right_margin, max_expand_w * 2 // 3)
        expand_bottom = min(bottom_margin, int(box_height * 0.5))  # 제목도 아래 확장 허용
    else:
        # 일반 텍스트: 매우 공격적으로 확장
        expand_left = 0
        expand_right = min(right_margin, int(box_width * 2.0))  # 1.5 → 2.0
        # 한 줄 한글 → 3-4줄 영어 가능하도록 아래로 충분히 확장
        expand_bottom = min(bottom_margin, int(box_height * 3.0))  # 2.0 → 3.0

    new_x1 = max(10, x1 - expand_left)  # 경계 마진 축소
    new_x2 = min(img_w - 10, x2 + expand_right)
    new_y2 = min(img_h - 10, y2 + expand_bottom)
    expanded_bbox = [new_x1, y1, new_x2, new_y2]

    # === Step 3: 확장 안전 검사 ===
    safe_overlap, overlap_reason = _is_expansion_safe(expanded_bbox, occupied_bboxes, img_np, current_idx)
    safe_empty, empty_reason = _check_expansion_region_empty(expanded_bbox, original_bbox, img_np)

    expansion_safe = safe_overlap and safe_empty
    if not expansion_safe:
        result["expansion_safe"] = False
        result["expansion_reason"] = f"blocked_{overlap_reason if not safe_overlap else empty_reason}"

    # === Step 4: 확장이 안전하면 시도 ===
    if expansion_safe:
        new_width = new_x2 - new_x1
        new_height = new_y2 - y1
        fits, wrapped_lines, _ = _try_render_with_font(text, target_font_size, new_width, new_height, font_path)
        if fits:
            result["final_bbox"] = expanded_bbox
            result["render_bbox"] = expanded_bbox
            # erase_bbox는 원본 유지 (확장 영역은 흰 여백이므로 지울 필요 없음)
            result["wrapped_lines"] = wrapped_lines
            result["expansion_applied"] = True
            result["expansion_reason"] = "expanded_fits"
            return result

    # === Step 5: Fallback - 폰트 축소 ===
    result["used_fallback"] = not expansion_safe

    # 확장이 안전하면 확장 bbox, 아니면 원본 bbox 사용
    if expansion_safe:
        use_bbox = expanded_bbox
        use_width = new_x2 - new_x1
        use_height = new_y2 - y1
    else:
        use_bbox = original_bbox
        use_width = box_width
        use_height = box_height

    # 폰트 축소: 60%까지 허용 (기존 80%)
    min_font = max(int(target_font_size * 0.60), 10)
    for font_size in range(target_font_size - 1, min_font - 1, -1):
        fits, wrapped_lines, _ = _try_render_with_font(text, font_size, use_width, use_height, font_path)
        if fits:
            result["final_bbox"] = use_bbox
            result["render_bbox"] = use_bbox
            result["final_font_size"] = font_size
            result["wrapped_lines"] = wrapped_lines
            result["expansion_applied"] = (use_bbox != original_bbox)
            if not result["expansion_applied"]:
                result["expansion_reason"] = "font_reduced_original"
            return result

    # === Step 6: 최소 폰트 + review_needed ===
    # 최소 폰트: 8px로 통일 (가독성 최저선)
    absolute_min = 8
    for font_size in range(min_font - 1, absolute_min - 1, -1):
        fits, wrapped_lines, _ = _try_render_with_font(text, font_size, use_width, use_height, font_path)
        if fits:
            result["final_bbox"] = use_bbox
            result["render_bbox"] = use_bbox
            result["final_font_size"] = font_size
            result["wrapped_lines"] = wrapped_lines
            result["needs_review"] = True
            result["expansion_applied"] = (use_bbox != original_bbox)
            result["expansion_reason"] = "minimum_font"
            return result

    # 최소 폰트로도 안 맞음
    _, wrapped_lines, _ = _try_render_with_font(text, absolute_min, use_width, use_height, font_path)
    result["final_bbox"] = use_bbox
    result["render_bbox"] = use_bbox
    result["final_font_size"] = absolute_min
    result["wrapped_lines"] = wrapped_lines
    result["needs_review"] = True
    result["expansion_applied"] = (use_bbox != original_bbox)
    result["expansion_reason"] = "overflow_allowed"

    return result


# ============================================================================
# 인페인팅 함수들
# ============================================================================

def _calculate_dynamic_padding(box_height: int, render_role: str = None) -> dict:
    """동적 패딩 계산"""
    if render_role and render_role in TITLE_ROLES:
        base_pad = int(box_height * TITLE_PADDING_RATIO)
        pad = max(4, min(base_pad, 18))
        return {"x": pad, "y": max(3, pad - 1), "y_bottom": pad + 2}

    base_pad = int(box_height * PADDING_RATIO)
    pad = max(MIN_PADDING, min(base_pad, MAX_PADDING))
    return {"x": pad, "y": max(2, pad - 1), "y_bottom": pad + 2}


def is_solid_background(img_np: np.ndarray, bbox: list, threshold: int = SOLID_BG_THRESHOLD) -> tuple:
    """bbox 주변 배경이 단색인지 확인"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    h, w = img_np.shape[:2]

    samples = []
    margin = 5
    positions = [
        (max(0, x1 - margin), y1 + (y2 - y1) // 2),
        (min(w - 1, x2 + margin), y1 + (y2 - y1) // 2),
        (x1 + (x2 - x1) // 2, max(0, y1 - margin)),
        (x1 + (x2 - x1) // 2, min(h - 1, y2 + margin)),
    ]

    for px, py in positions:
        if 0 <= px < w and 0 <= py < h:
            samples.append(img_np[py, px])

    if len(samples) < 2:
        return False, None

    samples = np.array(samples)
    std = np.std(samples) if len(samples.shape) == 1 else np.mean([np.std(samples[:, i]) for i in range(samples.shape[1])])

    if std < threshold:
        avg_color = tuple(int(v) for v in np.mean(samples, axis=0).astype(int))
        if len(avg_color) == 1:
            avg_color = (avg_color[0], avg_color[0], avg_color[0])
        return True, avg_color
    return False, None


def _inpaint_solid_color(image: Image.Image, bbox: list, bg_color: tuple, render_role: str = None) -> Image.Image:
    """단색 인페인팅"""
    x1, y1, x2, y2 = _normalize_bbox(bbox, image.size)
    padding = _calculate_dynamic_padding(y2 - y1, render_role)

    x1_p = max(0, x1 - padding["x"])
    y1_p = max(0, y1 - padding["y"])
    x2_p = min(image.width, x2 + padding["x"])
    y2_p = min(image.height, y2 + padding["y_bottom"])

    draw = ImageDraw.Draw(image)
    draw.rectangle([x1_p, y1_p, x2_p, y2_p], fill=bg_color)
    return image


def _get_edge_dominant_color(np_image: np.ndarray, bbox: list, margin: int = 10) -> tuple:
    """가장자리 색상 추출"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    h, w = np_image.shape[:2]
    edge_pixels = []

    for x in range(max(0, x1), min(w, x2)):
        if max(0, y1 - margin) < h:
            edge_pixels.append(np_image[max(0, y1 - margin), x])
        if min(h - 1, y2 + margin) < h:
            edge_pixels.append(np_image[min(h - 1, y2 + margin), x])

    for y in range(max(0, y1), min(h, y2)):
        if max(0, x1 - margin) < w:
            edge_pixels.append(np_image[y, max(0, x1 - margin)])
        if min(w - 1, x2 + margin) < w:
            edge_pixels.append(np_image[y, min(w - 1, x2 + margin)])

    if not edge_pixels:
        return (0, 0, 0)

    edge_pixels = np.array(edge_pixels)
    avg_color = tuple(int(v) for v in np.mean(edge_pixels, axis=0))
    return avg_color if len(avg_color) > 1 else (avg_color[0], avg_color[0], avg_color[0])


def _inpaint_opencv(image: Image.Image, bbox: list, render_role: str = None) -> Image.Image:
    """OpenCV 인페인팅"""
    try:
        import cv2
        x1, y1, x2, y2 = _normalize_bbox(bbox, image.size)
        padding = _calculate_dynamic_padding(y2 - y1, render_role)

        x1_p = max(0, x1 - padding["x"])
        y1_p = max(0, y1 - padding["y"])
        x2_p = min(image.width, x2 + padding["x"])
        y2_p = min(image.height, y2 + padding["y_bottom"])

        np_image = np.array(image)
        mask = np.zeros(np_image.shape[:2], dtype=np.uint8)
        mask[y1_p:y2_p, x1_p:x2_p] = 255

        np_bgr = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR) if len(np_image.shape) == 3 else np_image
        inpaint_radius = TITLE_INPAINT_RADIUS if render_role in TITLE_ROLES else INPAINT_RADIUS
        result = cv2.inpaint(np_bgr, mask, inpaint_radius, cv2.INPAINT_TELEA)
        if len(result.shape) == 3:
            result = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
        return Image.fromarray(result)
    except ImportError:
        np_image = np.array(image)
        edge_color = _get_edge_dominant_color(np_image, bbox, margin=5)
        return _inpaint_solid_color(image, bbox, edge_color, render_role)


def _get_contrasting_text_color(image: Image.Image, bbox: list) -> tuple:
    """대비 텍스트 색상"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.width, x2), min(image.height, y2)

    np_image = np.array(image)
    region = np_image[y1:y2, x1:x2]

    if region.size == 0:
        return (255, 255, 255)

    if len(region.shape) == 3:
        brightness = np.mean(0.299 * region[:,:,0] + 0.587 * region[:,:,1] + 0.114 * region[:,:,2])
    else:
        brightness = np.mean(region)

    return (255, 255, 255) if brightness < 128 else (0, 0, 0)


# ============================================================================
# 렌더링 함수
# ============================================================================

def render_english_text(
    image: Image.Image,
    render_bbox: list,
    english: str,
    text_item: dict,
    report=None,
    block_idx: int = 0,
    precomputed_font_size: int = None,
    precomputed_lines: list = None,
    precomputed_render_info: dict = None,
    original_bbox: list = None,  # 품질 체크용 원본 bbox
) -> tuple:
    """영어 텍스트 렌더링

    Args:
        render_bbox: 렌더링할 영역 (확장된 bbox)
        original_bbox: 품질 체크용 원본 bbox

    Returns:
        (image, skipped_line_count, overflow)
    """
    x1, y1, x2, y2 = _normalize_bbox(render_bbox, image.size)
    box_width = x2 - x1
    box_height = y2 - y1

    skipped_line_count = 0
    overflow = False

    if box_width < 20 or box_height < 10:
        return image, 0, False

    if precomputed_render_info:
        render_info = precomputed_render_info
    else:
        bg_brightness = get_bg_brightness(image, [x1, y1, x2, y2])
        render_info = infer_render_role(text_item, image.size, bg_brightness)

    alignment = render_info["alignment"]
    source_text = text_item.get("source_text", text_item.get("korean", ""))
    source_text_len = len(source_text) if source_text else 0

    actual_font_size = precomputed_font_size if precomputed_font_size else get_font_size_for_role(
        render_info, int(box_height), len(english), source_text_len
    )
    wrapped_lines = precomputed_lines

    draw = ImageDraw.Draw(image)
    text_color = text_item.get("text_color") or _get_contrasting_text_color(image, [x1, y1, x2, y2])

    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    font_path = next((p for p in font_paths if os.path.exists(p)), None)

    try:
        font = ImageFont.truetype(font_path, actual_font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
        actual_font_size = 10

    if wrapped_lines is None:
        wrapped_lines = _wrap_text(english, font, box_width)

    if not wrapped_lines:
        return image, 0, False

    line_height = actual_font_size + 2
    total_height = len(wrapped_lines) * line_height

    # 품질 체크 - original_bbox 기준으로 font_scale 계산
    if report is not None:
        block_id = text_item.get("block_id") or text_item.get("prompt_id") or f"block_{block_idx}"

        # font_scale_check는 original_bbox 기준
        if original_bbox:
            orig_height = original_bbox[3] - original_bbox[1]
            orig_width = original_bbox[2] - original_bbox[0]
        else:
            orig_height = box_height
            orig_width = box_width

        report.check_render_quality(
            block_id=block_id,
            render_info=render_info,
            actual_font_size=actual_font_size,
            box_height=orig_height,  # font_scale은 원본 기준
            wrapped_lines=wrapped_lines,
            box_width=orig_width,
            source_text_len=source_text_len
        )

    img_width, img_height = image.size

    # overflow 체크
    if total_height > box_height * 1.1:
        overflow = True
        # overflow 시: 상단 정렬 (bbox 시작점부터)
        start_y = y1
    else:
        # 정상: 중앙 정렬
        start_y = y1 + max(0, (box_height - total_height) // 2)

    start_y = max(0, min(start_y, img_height - line_height))

    for i, line in enumerate(wrapped_lines):
        if not line.strip():
            continue

        line_bbox = draw.textbbox((0, 0), line, font=font)
        line_width = line_bbox[2] - line_bbox[0]

        if alignment == "center":
            line_x = x1 + max(0, (box_width - line_width) // 2)
        elif alignment == "right":
            line_x = x2 - line_width - 5
        else:
            line_x = x1 + 5

        line_y = start_y + i * line_height

        # overflow 허용: bbox가 아닌 이미지 경계만 체크
        # overflow 허용 - 텍스트가 bbox를 넘어도 완전히 렌더링
        if line_y >= 0 and line_y + line_height <= img_height:
            line_x = max(0, min(line_x, img_width - line_width))
            draw.text((line_x, line_y), line, font=font, fill=text_color)
        else:
            skipped_line_count += 1

    return image, skipped_line_count, overflow


# ============================================================================
# 메인 처리 함수
# ============================================================================

def process_image_texts_phase2(
    image: Any,
    translated_texts: list[dict],
    image_type: str = "unknown",
    page_no: int = 1,
    output_dir: str = None
) -> tuple:
    """이미지 텍스트 처리 (인페인팅 + 렌더링)"""
    if isinstance(image, Image.Image):
        img_np = np.array(image)
        pil_image = image.copy()
    else:
        img_np = image.copy()
        pil_image = Image.fromarray(img_np)

    processed_count = 0
    skipped_count = 0
    skipped_no_korean = 0
    skipped_overlap = 0
    needs_review_count = 0

    report = get_current_report()
    rendered_bboxes = []
    render_debug_list = []

    # 모든 원본 bbox 수집 (확장 안전 검사용)
    all_original_bboxes = []
    for text_item in translated_texts:
        bbox = text_item.get("bbox")
        if bbox and len(bbox) == 4:
            all_original_bboxes.append(list(bbox))

    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    font_path = next((p for p in font_paths if os.path.exists(p)), None)

    def check_overlap_with_rendered(new_bbox, threshold=0.5):
        for rendered_bbox in rendered_bboxes:
            if _bbox_intersection_ratio(new_bbox, rendered_bbox) > threshold:
                return True
        return False

    for idx, text_item in enumerate(translated_texts):
        block_id = text_item.get("prompt_id", f"p{page_no}_b{idx:02d}")

        debug_info = {
            "page_no": page_no,
            "block_id": block_id,
            "source_text": "",
            "english": "",
            "render_role": "",
            "original_bbox": None,
            "final_bbox": None,
            "render_bbox": None,
            "erase_bbox": None,
            "target_font_size": 0,
            "actual_font_size": 0,
            "wrapped_lines": [],
            "skipped_line_count": 0,
            "overflow": False,
            "expansion_applied": False,
            "expansion_reason": "none",
            "expansion_safe": True,
            "used_fallback": False,
            "needs_review": False,
            "skipped": False,
            "skip_reason": ""
        }

        if not text_item.get("translation_available", False):
            skipped_count += 1
            debug_info["skipped"], debug_info["skip_reason"] = True, "no_translation"
            render_debug_list.append(debug_info)
            continue

        bbox = text_item.get("bbox")
        english = text_item.get("english", "")

        if not bbox or not english or len(bbox) != 4:
            skipped_count += 1
            debug_info["skipped"], debug_info["skip_reason"] = True, "invalid_input"
            render_debug_list.append(debug_info)
            continue

        source_text = text_item.get("source_text", text_item.get("korean", ""))
        if not contains_korean(source_text):
            skipped_no_korean += 1
            debug_info["skipped"], debug_info["skip_reason"] = True, "no_korean"
            render_debug_list.append(debug_info)
            continue

        debug_info["source_text"] = source_text[:100]
        debug_info["english"] = english[:100]

        bg_brightness = get_bg_brightness(pil_image, bbox)
        render_info = infer_render_role(text_item, pil_image.size, bg_brightness)
        render_role = render_info.get("render_role", "body")
        debug_info["render_role"] = render_role

        x1, y1, x2, y2 = _normalize_bbox(bbox, pil_image.size)
        original_bbox = [x1, y1, x2, y2]
        original_bbox_height = y2 - y1
        original_bbox_width = x2 - x1
        debug_info["original_bbox"] = original_bbox

        text_len = len(english)
        source_text_len = len(source_text) if source_text else 0
        target_font_size = get_font_size_for_role(render_info, original_bbox_height, text_len, source_text_len)
        debug_info["target_font_size"] = target_font_size

        # bbox 확장 시뮬레이션
        if render_role in ["title", "heading", "body", "bullet"]:
            expansion_result = _calculate_expanded_bbox_with_simulation(
                english, original_bbox, target_font_size, pil_image.size,
                render_role, font_path,
                all_original_bboxes + rendered_bboxes,
                img_np, idx
            )
            final_bbox = expansion_result["final_bbox"]
            render_bbox = expansion_result["render_bbox"]
            erase_bbox = original_bbox  # 항상 원본만 지움
            actual_font_size = expansion_result["final_font_size"]
            wrapped_lines = expansion_result["wrapped_lines"]
            needs_review = expansion_result["needs_review"]

            debug_info["expansion_applied"] = expansion_result["expansion_applied"]
            debug_info["expansion_reason"] = expansion_result["expansion_reason"]
            debug_info["expansion_safe"] = expansion_result["expansion_safe"]
            debug_info["used_fallback"] = expansion_result["used_fallback"]
        else:
            final_bbox = original_bbox
            render_bbox = original_bbox
            erase_bbox = original_bbox
            actual_font_size = target_font_size
            wrapped_lines = None
            needs_review = False

        debug_info["final_bbox"] = final_bbox
        debug_info["render_bbox"] = render_bbox
        debug_info["erase_bbox"] = erase_bbox
        debug_info["actual_font_size"] = actual_font_size
        debug_info["wrapped_lines"] = wrapped_lines or []
        debug_info["needs_review"] = needs_review

        # overlap 체크 (final_bbox 기준) - fallback 포함
        if check_overlap_with_rendered(final_bbox, threshold=0.5):
            # Fallback: 원본 bbox로 재시도
            if final_bbox != original_bbox:
                final_bbox = original_bbox
                render_bbox = original_bbox
                debug_info["used_fallback"] = True
                debug_info["expansion_applied"] = False
                debug_info["final_bbox"] = final_bbox
                debug_info["render_bbox"] = render_bbox

                # 원본으로 다시 overlap 체크
                if check_overlap_with_rendered(final_bbox, threshold=0.5):
                    skipped_overlap += 1
                    debug_info["skipped"], debug_info["skip_reason"] = True, "overlap_after_fallback"
                    render_debug_list.append(debug_info)
                    continue
            else:
                skipped_overlap += 1
                debug_info["skipped"], debug_info["skip_reason"] = True, "overlap_with_rendered"
                render_debug_list.append(debug_info)
                continue

        processed_count += 1

        # 인페인팅 (erase_bbox = original_bbox 기준)
        is_solid, bg_color = is_solid_background(img_np, erase_bbox)

        if render_role in TITLE_ROLES:
            pil_image = _inpaint_opencv(pil_image, erase_bbox, render_role=render_role)
        elif is_solid and bg_color:
            pil_image = _inpaint_solid_color(pil_image, erase_bbox, bg_color, render_role=render_role)
        else:
            pil_image = _inpaint_opencv(pil_image, erase_bbox, render_role=render_role)

        img_np = np.array(pil_image)

        # 텍스트 렌더링 (render_bbox 기준)
        pil_image, skipped_lines, overflow = render_english_text(
            pil_image, render_bbox, english, text_item, report, idx,
            precomputed_font_size=actual_font_size,
            precomputed_lines=wrapped_lines,
            precomputed_render_info=render_info,
            original_bbox=original_bbox
        )

        debug_info["skipped_line_count"] = skipped_lines
        debug_info["overflow"] = overflow

        if skipped_lines > 0 or overflow:
            debug_info["needs_review"] = True
            needs_review = True

        if needs_review:
            needs_review_count += 1

        rendered_bboxes.append(final_bbox)

        if report:
            report.register_rendered_block(page_no, block_id, final_bbox, english)
            if needs_review:
                report.add_review_needed(block_id, debug_info["expansion_reason"])

        render_debug_list.append(debug_info)

    if report:
        report.finalize_page(page_no)

    print(f"[ImageRendering] 처리: {processed_count}, 스킵: {skipped_count}, 한글없음: {skipped_no_korean}, 중복: {skipped_overlap}, 검토필요: {needs_review_count}")

    return pil_image, render_debug_list


def process_page_images(
    images: list[Any],
    translated_texts_by_page: dict[int, list[dict]],
    image_types_by_page: Optional[dict[int, str]] = None,
    output_dir: str = None
) -> tuple:
    """페이지별 이미지 처리"""
    start_render_report()

    result_images = []
    all_debug_info = []
    total_needs_review = 0

    for page_no, image in enumerate(images, 1):
        texts = translated_texts_by_page.get(page_no, [])
        image_type = (image_types_by_page or {}).get(page_no, "unknown")

        if texts:
            processed, debug_list = process_image_texts_phase2(
                image, texts, image_type, page_no=page_no, output_dir=output_dir
            )
            all_debug_info.extend(debug_list)
            total_needs_review += sum(1 for d in debug_list if d.get("needs_review") and not d.get("skipped"))
        else:
            processed = image if isinstance(image, Image.Image) else Image.fromarray(image)

        result_images.append(processed)

    render_report = finish_render_report()

    # needs_review를 render_report에 반영
    if render_report:
        render_report["stats"]["needs_review"] = total_needs_review
        if total_needs_review > 0:
            render_report["has_review_needed"] = True

    if output_dir and all_debug_info:
        os.makedirs(output_dir, exist_ok=True)
        debug_path = os.path.join(output_dir, "render_debug.json")
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(all_debug_info, f, ensure_ascii=False, indent=2)
            print(f"[ImageRendering] Saved render_debug.json: {debug_path}")
        except Exception as e:
            print(f"[ImageRendering] Failed to save render_debug.json: {e}")

    return result_images, render_report, all_debug_info


def save_processed_image(image: Image.Image, output_path: str):
    image.save(output_path)


def save_processed_images(images: list[Image.Image], output_dir: str, prefix: str = "page"):
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for i, image in enumerate(images, 1):
        path = os.path.join(output_dir, f"{prefix}_{i:03d}.png")
        image.save(path)
        paths.append(path)
    return paths
