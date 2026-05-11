"""
Visual Feature 기반 Render Role 추론 모듈
"""
from typing import Optional

# Bullet prefix 패턴 - '' 추가
BULLET_PREFIXES = (
    "•", "■", "▪", "▶", "►", "○", "●", "◆", "◇",
    "-", "–", "—", "*", "·", "∙", "⁃", "‣", "⦿", "⦾",
    "□", "▫", "◻", "◽", "▢",  # 빈 사각형
    "△", "▷", "▹", "→", "⇒",  # 화살표/삼각형
    "",  # 한글 동그라미 숫자
)
NUMBERED_PATTERN_STARTS = ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "0.", "1)", "2)", "3)", "(1)", "(2)", "(3)")

# Footer 키워드
FOOTER_KEYWORDS = ("copyright", "©", "all rights reserved", "page", "페이지", "출처", "source:", "ref:")


def infer_render_role(
    text_item: dict,
    image_size: tuple,
    bg_brightness: float = None
) -> dict:
    """Visual feature 기반 render role 추론

    Args:
        text_item: 텍스트 정보 (bbox, region_type, source_text, english, page_type 등)
        image_size: (width, height)
        bg_brightness: 배경 밝기 (0-255, None이면 자동 판단 안함)

    Returns:
        {
            "render_role": "title" | "heading" | "bullet" | "body" | "label" | "caption" | "footer",
            "alignment": "left" | "center" | "right",
            "padding_level": "small" | "medium" | "large",
            "font_priority": "large" | "medium" | "small",
            "is_dark_bg": bool,
            "visual_prominence": float (0-1),
            "is_bullet": bool,
            "hanging_indent": int (bullet일 때 들여쓰기 픽셀)
        }
    """
    bbox = text_item.get("bbox") or text_item.get("union_bbox", [0, 0, 100, 100])
    region_type = text_item.get("region_type", text_item.get("block_type", ""))
    source_text = text_item.get("source_text", text_item.get("korean", ""))
    english = text_item.get("english", "")
    page_type = text_item.get("page_type", "")

    img_w, img_h = image_size
    x1, y1, x2, y2 = [float(v) for v in bbox]
    box_w = x2 - x1
    box_h = y2 - y1

    # ====== Feature 계산 ======

    # 1. Area ratio (bbox가 이미지에서 차지하는 비율)
    area_ratio = (box_w * box_h) / (img_w * img_h) if img_w * img_h > 0 else 0

    # 2. Width ratio (가로 폭 비율)
    width_ratio = box_w / img_w if img_w > 0 else 0

    # 3. Position (상단/중단/하단)
    y_center = (y1 + y2) / 2
    y_position = y_center / img_h if img_h > 0 else 0.5  # 0=상단, 1=하단

    # 4. X position (좌/중/우)
    x_center = (x1 + x2) / 2
    x_position = x_center / img_w if img_w > 0 else 0.5  # 0=좌측, 1=우측

    # 5. Text length
    text_len = len(english) if english else len(source_text)

    # 6. 텍스트 내용 (소문자로)
    text_lower = (english or source_text or "").lower()

    # 7. Bullet 여부 (source_text 기반 - 더 정확한 판정)
    source_stripped = source_text.strip() if source_text else ""
    english_stripped = english.strip() if english else ""

    is_bullet = (
        source_stripped.startswith(BULLET_PREFIXES) or
        source_stripped.startswith(NUMBERED_PATTERN_STARTS) or
        english_stripped.startswith(BULLET_PREFIXES) or
        english_stripped.startswith(NUMBERED_PATTERN_STARTS) or
        region_type in ["bullet_head", "bullet_body", "bullet"]
    )

    # Bullet prefix 길이 계산 (hanging indent용)
    bullet_prefix_len = 0
    if is_bullet:
        for prefix in BULLET_PREFIXES + NUMBERED_PATTERN_STARTS:
            if source_stripped.startswith(prefix):
                bullet_prefix_len = len(prefix)
                break

    # 8. 배경 밝기 판단
    is_dark_bg = bg_brightness is not None and bg_brightness < 80

    # 9. Footer/Caption 키워드 체크
    is_footer_text = any(kw in text_lower for kw in FOOTER_KEYWORDS)

    # ====== Visual prominence (시각적 중요도) 계산 ======
    visual_prominence = 0.0

    # 큰 영역 = 높은 중요도
    if area_ratio > 0.05:
        visual_prominence += 0.3
    elif area_ratio > 0.02:
        visual_prominence += 0.2

    # 상단 위치 = 높은 중요도
    if y_position < 0.25:
        visual_prominence += 0.3
    elif y_position < 0.4:
        visual_prominence += 0.15

    # 넓은 가로폭 = 높은 중요도
    if width_ratio > 0.6:
        visual_prominence += 0.2
    elif width_ratio > 0.4:
        visual_prominence += 0.1

    # 짧은 텍스트 + 큰 영역 = 제목 가능성
    if text_len < 50 and area_ratio > 0.01:
        visual_prominence += 0.2

    # ====== Role 결정 (순서 중요!) ======
    render_role = "body"  # 기본값

    # 1순위: Footer (하단 + footer 키워드 or 아주 작은 영역)
    if y_position > 0.9 and (is_footer_text or area_ratio < 0.008):
        render_role = "footer"

    # 2순위: Caption (하단 + 작은 영역 + 짧은 텍스트)
    elif y_position > 0.85 and area_ratio < 0.015 and text_len < 100:
        render_role = "caption"

    # 3순위: Label (아주 작은 영역 - diagram label 등)
    elif area_ratio < 0.005 or (box_w < 80 and box_h < 25):
        render_role = "label"

    # 4순위: Bullet (bullet prefix 있음)
    elif is_bullet:
        render_role = "bullet"

    # 5순위: Title (상단 + 큰 영역 + 짧은 텍스트)
    elif (y_position < 0.3 and
          (area_ratio > 0.02 or (box_h > 40 and text_len < 80)) and
          not is_bullet):
        render_role = "title"

    # 6순위: Heading (중요도 높음 + 짧은 텍스트)
    elif visual_prominence > 0.5 and text_len < 100 and not is_bullet:
        render_role = "heading"

    # page_type 힌트 반영
    if page_type == "diagram_or_label_dense" and render_role == "body":
        # diagram 페이지에서는 작은 텍스트가 label일 가능성 높음
        if area_ratio < 0.01:
            render_role = "label"

    # region_type 힌트 반영 (최종 override)
    if region_type == "title" and visual_prominence > 0.3:
        render_role = "title"
    elif region_type == "heading" and visual_prominence > 0.2:
        render_role = "heading"
    elif region_type == "footer":
        render_role = "footer"
    elif region_type == "caption":
        render_role = "caption"

    # ====== Alignment 추론 (원본 bbox 위치 기반) ======
    alignment = "left"  # 기본값

    # x 위치로 정렬 추정
    left_margin = x1 / img_w if img_w > 0 else 0
    right_margin = (img_w - x2) / img_w if img_w > 0 else 0

    if abs(left_margin - right_margin) < 0.1:
        # 좌우 여백 비슷 → 중앙 정렬
        alignment = "center"
    elif left_margin > right_margin + 0.15:
        # 왼쪽 여백이 더 큼 → 우측 정렬
        alignment = "right"
    # else: 좌측 정렬 유지

    # Title/Heading은 중앙 정렬 경향
    if render_role in ["title", "heading"] and abs(left_margin - right_margin) < 0.2:
        alignment = "center"

    # Footer/Caption은 보통 중앙
    if render_role in ["footer", "caption"] and abs(left_margin - right_margin) < 0.25:
        alignment = "center"

    # Bullet은 항상 좌측 정렬
    if render_role == "bullet":
        alignment = "left"

    # ====== Padding Level 결정 (render_role + 배경 밝기) ======
    if is_dark_bg:
        padding_level = "large"
    elif render_role in ["title", "heading"]:
        padding_level = "small"
    elif render_role in ["label", "caption", "footer"]:
        padding_level = "small"
    elif render_role == "bullet":
        padding_level = "medium"
    else:
        padding_level = "medium"

    # ====== Font Priority 결정 (bbox height + visual prominence) ======
    if box_h > 60 or (render_role == "title" and box_h > 40):
        font_priority = "large"
    elif box_h > 30 or render_role in ["title", "heading"]:
        font_priority = "medium"
    elif render_role in ["label", "caption", "footer"]:
        font_priority = "small"
    else:
        font_priority = "medium"

    # ====== Hanging indent 계산 (bullet용) ======
    hanging_indent = 0
    if is_bullet and bullet_prefix_len > 0:
        # 대략 prefix 길이에 비례한 indent
        hanging_indent = max(15, bullet_prefix_len * 8)

    return {
        "render_role": render_role,
        "alignment": alignment,
        "padding_level": padding_level,
        "font_priority": font_priority,
        "is_dark_bg": is_dark_bg,
        "visual_prominence": min(1.0, visual_prominence),
        "is_bullet": is_bullet,
        "hanging_indent": hanging_indent,
        # 디버깅용
        "_features": {
            "area_ratio": round(area_ratio, 4),
            "width_ratio": round(width_ratio, 2),
            "y_position": round(y_position, 2),
            "x_position": round(x_position, 2),
            "is_bullet": is_bullet,
            "text_len": text_len,
            "page_type": page_type,
            "region_type": region_type,
        }
    }


def get_padding_for_role(render_info: dict) -> dict:
    """render_role 기반 패딩 반환"""
    padding_level = render_info.get("padding_level", "medium")
    is_dark = render_info.get("is_dark_bg", False)

    if is_dark:
        return {"x": 15, "y": 20, "y_bottom": 25}

    padding_map = {
        "small": {"x": 5, "y": 6, "y_bottom": 8},
        "medium": {"x": 8, "y": 10, "y_bottom": 12},
        "large": {"x": 12, "y": 15, "y_bottom": 18},
    }
    return padding_map.get(padding_level, padding_map["medium"])


def get_font_size_for_role(render_info: dict, box_height: int, text_len: int, source_text_len: int = 0) -> int:
    """render_role 기반 폰트 크기 반환

    핵심 원칙:
    - 원본 한글 텍스트의 시각적 크기를 기준으로 폰트 계산
    - 영어가 길어도 과도하게 축소하지 않음
    - 최소 폰트 크기 보장으로 가독성 유지
    """
    font_priority = render_info.get("font_priority", "medium")
    render_role = render_info.get("render_role", "body")

    # 원본 한글 길이 기준으로 계산 (없으면 영어 길이의 50%로 추정)
    korean_len = source_text_len if source_text_len > 0 else max(1, text_len // 2)

    # 기본 크기 계산 (bbox 높이 + 원본 한글 기준)
    if render_role == "title":
        # 제목: 높이의 60-70% (크게 유지)
        base = int(box_height * 0.65)
        min_size, max_size = 28, 72
    elif render_role == "heading":
        base = int(box_height * 0.6)
        min_size, max_size = 22, 56
    elif render_role == "label":
        base = int(box_height * 0.7)
        min_size, max_size = 12, 24
    elif render_role in ["caption", "footer"]:
        base = int(box_height * 0.6)
        min_size, max_size = 10, 20
    elif render_role == "bullet":
        # bullet: 한글 기준 줄 수 추정 (35자당 1줄)
        estimated_lines = max(1, korean_len // 35)
        base = int(box_height * 0.75 / estimated_lines)
        min_size, max_size = 14, 36
    else:
        # body: 한글 기준 줄 수 추정 (35자당 1줄)
        estimated_lines = max(1, korean_len // 35)
        base = int(box_height * 0.8 / estimated_lines)
        min_size, max_size = 16, 48

    # font_priority 조정
    if font_priority == "large":
        base = int(base * 1.15)
    elif font_priority == "small":
        base = int(base * 0.95)

    return max(min_size, min(max_size, base))


def get_bg_brightness(image, bbox: list) -> float:
    """bbox 영역의 평균 밝기 반환"""
    import numpy as np

    if hasattr(image, 'convert'):
        # PIL Image
        img_array = np.array(image.convert('L'))
    else:
        # numpy array
        if len(image.shape) == 3:
            img_array = np.mean(image, axis=2)
        else:
            img_array = image

    x1, y1, x2, y2 = [int(v) for v in bbox]
    h, w = img_array.shape[:2]

    x1 = max(0, min(x1, w-1))
    x2 = max(0, min(x2, w))
    y1 = max(0, min(y1, h-1))
    y2 = max(0, min(y2, h))

    if x2 <= x1 or y2 <= y1:
        return 128.0

    region = img_array[y1:y2, x1:x2]
    return float(np.mean(region))


# ============================================================================
# Render Quality Report
# ============================================================================

class RenderQualityReport:
    """렌더링 품질 리포트 수집기"""

    def __init__(self):
        self.warnings = []
        self.errors = []
        self.skipped_renders = []  # 렌더링 스킵된 블록 추적
        self.needs_review = []  # 검토 필요 블록 추적
        self.stats = {
            "total_blocks": 0,
            "rendered_ok": 0,
            "render_skipped": 0,  # 폰트 크기로 인한 렌더링 스킵
            "font_too_small": 0,
            "overflow": 0,
            "overlap_risk": 0,
            "title_too_small": 0,
            "block_overlap": 0,  # 블록 간 겹침
            "needs_review": 0,  # 검토 필요 블록 수
        }
        # 페이지별 렌더된 블록 bbox 추적
        self._rendered_blocks_by_page: dict[int, list[dict]] = {}

    def check_render_quality(
        self,
        block_id: str,
        render_info: dict,
        actual_font_size: int,
        box_height: int,
        wrapped_lines: list,
        box_width: int,
        source_text_len: int = 0
    ):
        """렌더링 품질 체크 - font_scale_ratio 기반

        핵심 원칙:
        - 원본 시각적 위계 유지가 중요
        - title/heading/body는 원본 대비 축소 비율 제한
        - caption/footer만 작아도 허용
        """
        self.stats["total_blocks"] += 1
        render_role = render_info.get("render_role", "body")
        has_issue = False

        # ====== 1. 원본 추정 폰트 크기 계산 ======
        # 한글 텍스트가 bbox에 맞게 렌더링됐을 때의 추정 크기
        korean_len = source_text_len if source_text_len > 0 else 10

        if render_role == "title":
            # 제목: bbox 높이의 60-70%
            original_estimated = int(box_height * 0.65)
        elif render_role == "heading":
            original_estimated = int(box_height * 0.55)
        elif render_role in ["caption", "footer", "label"]:
            original_estimated = int(box_height * 0.6)
        else:
            # body/bullet: 한글 줄 수 기반
            korean_lines = max(1, korean_len // 35)
            original_estimated = int(box_height * 0.75 / korean_lines)

        # ====== 2. font_scale_ratio 계산 ======
        font_scale_ratio = actual_font_size / max(1, original_estimated)

        # ====== 3. render_role별 최소 scale_ratio 기준 (엄격) ======
        # 원본 시각 위계 유지가 핵심
        # title/heading/body는 원본 크기의 70%+ 유지 필요
        scale_thresholds = {
            "title": {"fail": 0.70, "warning": 0.85},      # 제목: 70% 미만 실패
            "heading": {"fail": 0.65, "warning": 0.80},    # 헤딩: 65% 미만 실패
            "body": {"fail": 0.55, "warning": 0.70},       # 본문: 55% 미만 실패
            "bullet": {"fail": 0.55, "warning": 0.70},     # 불릿: 55% 미만 실패
            "label": {"fail": 0.40, "warning": 0.55},      # 라벨: 40% 미만 실패
            "caption": {"fail": 0.30, "warning": 0.45},    # 캡션: 작아도 허용
            "footer": {"fail": 0.30, "warning": 0.45},     # 푸터: 작아도 허용
        }
        thresholds = scale_thresholds.get(render_role, {"fail": 0.55, "warning": 0.70})

        # ====== 4. Scale ratio 기반 품질 체크 ======
        if font_scale_ratio < thresholds["fail"]:
            # 심각한 축소 - warning only (확대로 해결 가능)
            # 이전: error였지만 사용자 피드백 반영하여 warning으로 변경
            severity = "warning"
            self.warnings.append({
                "block_id": block_id,
                "type": "font_scale_too_low",
                "message": f"Font scale {font_scale_ratio:.2f} < {thresholds['fail']} for {render_role} "
                          f"(original~{original_estimated}px → actual {actual_font_size}px)",
                "severity": severity,
                "font_scale_ratio": round(font_scale_ratio, 2),
                "original_estimated": original_estimated,
                "actual_font": actual_font_size,
                "render_role": render_role,
            })
            self.stats["font_too_small"] += 1
            # 더 이상 errors에 추가하지 않음 (warning only)
            # has_issue는 title/heading에서만 설정
            if render_role in ["title", "heading"]:
                has_issue = True

        elif font_scale_ratio < thresholds["warning"]:
            # 경미한 축소 - warning
            severity = "warning" if render_role in ["title", "heading", "body"] else "info"
            self.warnings.append({
                "block_id": block_id,
                "type": "font_scale_reduced",
                "message": f"Font scale {font_scale_ratio:.2f} < {thresholds['warning']} for {render_role}",
                "severity": severity,
                "font_scale_ratio": round(font_scale_ratio, 2),
                "original_estimated": original_estimated,
                "actual_font": actual_font_size,
            })
            if severity == "warning":
                has_issue = True

        # ====== 5. Overflow 체크 ======
        line_height = actual_font_size + 2
        total_height = len(wrapped_lines) * line_height
        if total_height > box_height * 1.15:
            self.warnings.append({
                "block_id": block_id,
                "type": "overflow",
                "message": f"Text height {total_height}px > box height {box_height}px",
                "severity": "warning",
            })
            self.stats["overflow"] += 1
            has_issue = True

        # ====== 6. 절대 최소 크기 체크 (가독성) ======
        absolute_min = {
            "title": 20, "heading": 16, "body": 12, "bullet": 12,
            "label": 8, "caption": 8, "footer": 8
        }
        min_size = absolute_min.get(render_role, 10)

        if actual_font_size < min_size:
            # caption/footer면 info, 그 외는 warning
            severity = "info" if render_role in ["caption", "footer", "label"] else "warning"
            self.warnings.append({
                "block_id": block_id,
                "type": "font_below_minimum",
                "message": f"Font {actual_font_size}px < absolute minimum {min_size}px for {render_role}",
                "severity": severity,
                "actual_font": actual_font_size,
            })
            if render_role in ["title", "heading"]:
                self.stats["title_too_small"] += 1
                has_issue = True

        if not has_issue:
            self.stats["rendered_ok"] += 1

    def register_rendered_block(
        self,
        page_no: int,
        block_id: str,
        bbox: list,
        english_text: str = ""
    ):
        """렌더된 블록 등록 (overlap 체크용)"""
        if page_no not in self._rendered_blocks_by_page:
            self._rendered_blocks_by_page[page_no] = []

        self._rendered_blocks_by_page[page_no].append({
            "block_id": block_id,
            "bbox": bbox,
            "text": english_text[:50] if english_text else "",
        })

    def check_page_overlaps(self, page_no: int):
        """페이지 내 블록 간 겹침 체크"""
        blocks = self._rendered_blocks_by_page.get(page_no, [])
        if len(blocks) < 2:
            return

        def bbox_overlap_area(bbox1, bbox2):
            """두 bbox의 겹침 면적 계산"""
            if not bbox1 or not bbox2 or len(bbox1) < 4 or len(bbox2) < 4:
                return 0
            x1 = max(bbox1[0], bbox2[0])
            y1 = max(bbox1[1], bbox2[1])
            x2 = min(bbox1[2], bbox2[2])
            y2 = min(bbox1[3], bbox2[3])
            if x1 >= x2 or y1 >= y2:
                return 0
            return (x2 - x1) * (y2 - y1)

        def bbox_area(bbox):
            if not bbox or len(bbox) < 4:
                return 0
            return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

        # 모든 블록 쌍에 대해 겹침 체크
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                b1, b2 = blocks[i], blocks[j]
                overlap = bbox_overlap_area(b1["bbox"], b2["bbox"])
                if overlap > 0:
                    # 겹침 비율 계산 (작은 bbox 기준)
                    area1, area2 = bbox_area(b1["bbox"]), bbox_area(b2["bbox"])
                    smaller_area = min(area1, area2) if area1 > 0 and area2 > 0 else 1
                    overlap_ratio = overlap / smaller_area

                    # 10% 이상 겹치면 warning
                    if overlap_ratio > 0.1:
                        self.stats["block_overlap"] += 1
                        severity = "error" if overlap_ratio > 0.5 else "warning"
                        self.warnings.append({
                            "page": page_no,
                            "type": "block_overlap",
                            "message": f"Blocks {b1['block_id']} and {b2['block_id']} overlap by {overlap_ratio*100:.1f}%",
                            "blocks": [b1["block_id"], b2["block_id"]],
                            "overlap_ratio": round(overlap_ratio, 2),
                            "severity": severity,
                        })
                        if severity == "error":
                            self.errors.append(self.warnings[-1])

    def finalize_page(self, page_no: int):
        """페이지 처리 완료 시 호출 - overlap 체크 실행"""
        self.check_page_overlaps(page_no)

    def record_skipped_render(
        self,
        block_id: str,
        reason: str,
        estimated_font: int,
        bbox: list,
        english: str = ""
    ):
        """렌더링 스킵된 블록 기록

        폰트가 너무 작아서 읽을 수 없는 경우 렌더링을 스킵하고 원본 유지
        """
        self.stats["render_skipped"] += 1

        skip_info = {
            "block_id": block_id,
            "reason": reason,
            "estimated_font": estimated_font,
            "bbox": bbox,
            "text_preview": english,
        }
        self.skipped_renders.append(skip_info)

        # warning으로도 기록 (리포트에 표시되도록)
        self.warnings.append({
            "block_id": block_id,
            "type": "render_skipped",
            "message": f"Skipped render: font would be {estimated_font}px (< 8px minimum)",
            "severity": "info",  # error가 아닌 info - 의도적 스킵
            "reason": reason,
        })

    def add_review_needed(self, block_id: str, reason: str):
        """검토 필요 블록 기록

        bbox 확장 등으로 인해 수동 검토가 필요한 블록을 기록
        """
        self.stats["needs_review"] += 1

        review_info = {
            "block_id": block_id,
            "reason": reason,
        }
        self.needs_review.append(review_info)

        # warning으로도 기록
        self.warnings.append({
            "block_id": block_id,
            "type": "needs_review",
            "message": f"Needs manual review: {reason}",
            "severity": "warning",
            "reason": reason,
        })

    def get_report(self) -> dict:
        """최종 리포트 반환

        Success 기준:
        - font_scale_too_low (title/heading/body): 실패 조건 - 원본 시각적 위계 파괴
        - overflow: 실패 조건 (확대해도 잘린 텍스트 복구 불가)
        - block_overlap: 실패 조건 (확대해도 겹침 해결 불가)
        - font_scale_too_low (caption/footer): info - 원래 작은 텍스트는 허용
        """
        total = self.stats["total_blocks"]
        ok = self.stats["rendered_ok"]

        # ====== 실패 조건 분류 ======

        # 1. font_scale_too_low (title/heading/body) - 원본 시각 위계 파괴
        scale_errors = [
            e for e in self.errors
            if e.get("type") == "font_scale_too_low"
            and e.get("render_role") in ["title", "heading", "body", "bullet"]
        ]

        # 2. overflow, block_overlap - 레이아웃 문제
        layout_errors = [
            e for e in self.errors
            if e.get("type") in ["overflow", "block_overlap"]
        ]

        # 3. warnings 중 중요한 것
        important_warnings = [
            w for w in self.warnings
            if (w.get("type") in ["overflow", "block_overlap", "font_scale_too_low"]
                and w.get("severity") in ["warning", "error"]
                and w.get("render_role", "body") in ["title", "heading", "body", "bullet"])
        ]

        # ====== 문제 카운트 ======
        scale_issue_count = len(scale_errors)
        layout_issue_count = len(layout_errors)
        warning_count = len(important_warnings)

        total_critical = scale_issue_count + layout_issue_count
        critical_ratio = total_critical / total if total > 0 else 0
        warning_ratio = warning_count / total if total > 0 else 0

        # ====== Success 판정 ======
        # 심각한 scale 문제 또는 레이아웃 문제가 10% 이상이면 실패
        # warning이 20% 이상이면 partial
        if critical_ratio >= 0.1:
            success = False
            status = "fail"
        elif warning_ratio >= 0.2:
            success = False
            status = "partial"
        else:
            success = True
            status = "pass"

        return {
            "stats": self.stats,
            "warnings": self.warnings,
            "errors": self.errors,
            "skipped_renders": self.skipped_renders,
            "needs_review": self.needs_review,
            "needs_review_count": self.stats.get("needs_review", 0),
            "success": success,
            "status": status,
            "scale_issue_count": scale_issue_count,
            "layout_issue_count": layout_issue_count,
            "critical_issue_count": total_critical,
            "critical_ratio": round(critical_ratio, 2),
            "warning_ratio": round(warning_ratio, 2),
            "ok_ratio": round(ok / total, 2) if total > 0 else 1.0,
        }


# 전역 리포트 인스턴스
_current_report: Optional[RenderQualityReport] = None


def start_render_report():
    """새 렌더링 리포트 시작"""
    global _current_report
    _current_report = RenderQualityReport()
    return _current_report


def get_current_report() -> Optional[RenderQualityReport]:
    """현재 리포트 반환"""
    return _current_report


def finish_render_report() -> dict:
    """렌더링 리포트 종료 및 결과 반환"""
    global _current_report
    if _current_report is None:
        return {"stats": {}, "warnings": [], "errors": [], "success": True}
    report = _current_report.get_report()
    _current_report = None
    return report
