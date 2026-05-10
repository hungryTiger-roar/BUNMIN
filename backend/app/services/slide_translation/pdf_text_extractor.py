"""
PDF 텍스트 레이어 추출기

PDF에서 텍스트 레이어를 직접 추출하여 정확한 위치/폰트/스타일 정보 획득
OCR 방식보다 훨씬 정확한 텍스트 추출 가능
"""
import fitz  # PyMuPDF
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class TextSpan:
    """텍스트 스팬 (단일 스타일의 텍스트 조각)"""
    text: str
    bbox: tuple  # (x0, y0, x1, y1)
    font: str
    size: float
    color: int  # RGB as integer
    flags: int  # bold, italic 등
    origin: tuple  # (x, y) baseline origin

    @property
    def is_korean(self) -> bool:
        """한글 포함 여부"""
        import re
        return bool(re.search(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', self.text))

    @property
    def is_bold(self) -> bool:
        return bool(self.flags & 2**4)  # bit 4 = bold

    @property
    def is_italic(self) -> bool:
        return bool(self.flags & 2**1)  # bit 1 = italic


@dataclass
class TextBlock:
    """텍스트 블록 (여러 스팬의 그룹)"""
    spans: list[TextSpan] = field(default_factory=list)
    bbox: tuple = None  # 전체 블록의 bbox
    block_type: str = "text"  # text, title, bullet 등

    @property
    def full_text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def has_korean(self) -> bool:
        return any(s.is_korean for s in self.spans)

    @property
    def avg_font_size(self) -> float:
        if not self.spans:
            return 0
        return sum(s.size for s in self.spans) / len(self.spans)


@dataclass
class PageTextLayer:
    """페이지의 텍스트 레이어"""
    page_num: int
    width: float
    height: float
    blocks: list[TextBlock] = field(default_factory=list)
    has_text_layer: bool = True

    @property
    def korean_blocks(self) -> list[TextBlock]:
        return [b for b in self.blocks if b.has_korean]

    @property
    def korean_ratio(self) -> float:
        if not self.blocks:
            return 0
        return len(self.korean_blocks) / len(self.blocks)


def extract_text_layer(pdf_path: str) -> list[PageTextLayer]:
    """
    PDF에서 텍스트 레이어 추출

    Args:
        pdf_path: PDF 파일 경로

    Returns:
        페이지별 텍스트 레이어 리스트
    """
    doc = fitz.open(pdf_path)
    pages_data = []

    for page_num, page in enumerate(doc):
        page_layer = PageTextLayer(
            page_num=page_num + 1,
            width=page.rect.width,
            height=page.rect.height
        )

        # 텍스트 추출 (dict 모드 - 상세 정보 포함)
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # 0 = 텍스트, 1 = 이미지
                continue

            text_block = TextBlock(bbox=tuple(block["bbox"]))

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue

                    text_span = TextSpan(
                        text=span.get("text", ""),
                        bbox=tuple(span.get("bbox", (0, 0, 0, 0))),
                        font=span.get("font", ""),
                        size=span.get("size", 12),
                        color=span.get("color", 0),
                        flags=span.get("flags", 0),
                        origin=tuple(span.get("origin", (0, 0)))
                    )
                    text_block.spans.append(text_span)

            if text_block.spans:
                # 블록 타입 추론
                text_block.block_type = _infer_block_type(text_block, page.rect)
                page_layer.blocks.append(text_block)

        # 텍스트 레이어 존재 여부 판단
        page_layer.has_text_layer = len(page_layer.blocks) > 0
        pages_data.append(page_layer)

    doc.close()
    return pages_data


def _infer_block_type(block: TextBlock, page_rect) -> str:
    """블록 타입 추론 (title, body, caption 등)"""
    if not block.spans:
        return "text"

    avg_size = block.avg_font_size
    bbox = block.bbox
    page_width = page_rect.width
    page_height = page_rect.height

    # 위치 기반 추론
    y_ratio = bbox[1] / page_height if page_height > 0 else 0
    x_center = (bbox[0] + bbox[2]) / 2
    is_centered = abs(x_center - page_width / 2) < page_width * 0.1

    # 크기 기반 추론
    if avg_size >= 24 and y_ratio < 0.2:
        return "title"
    elif avg_size >= 18 and is_centered:
        return "heading"
    elif avg_size <= 10:
        return "caption"
    elif bbox[0] > page_width * 0.1:  # 들여쓰기
        return "bullet"
    else:
        return "body"


def check_pdf_has_text_layer(pdf_path: str) -> dict:
    """
    PDF에 텍스트 레이어가 있는지 확인

    Returns:
        {
            "has_text_layer": bool,
            "total_pages": int,
            "pages_with_text": int,
            "total_text_blocks": int,
            "korean_blocks": int,
            "recommendation": "pdf_layer" | "ocr" | "hybrid"
        }
    """
    doc = fitz.open(pdf_path)

    total_pages = len(doc)
    pages_with_text = 0
    total_blocks = 0
    korean_blocks = 0

    for page in doc:
        text_dict = page.get_text("dict")
        text_blocks = [b for b in text_dict.get("blocks", []) if b.get("type") == 0]

        if text_blocks:
            pages_with_text += 1
            total_blocks += len(text_blocks)

            # 한글 블록 카운트
            for block in text_blocks:
                full_text = ""
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        full_text += span.get("text", "")

                import re
                if re.search(r'[\uac00-\ud7af]', full_text):
                    korean_blocks += 1

    doc.close()

    # 추천 방식 결정
    text_ratio = pages_with_text / total_pages if total_pages > 0 else 0

    if text_ratio >= 0.8:
        recommendation = "pdf_layer"
    elif text_ratio >= 0.3:
        recommendation = "hybrid"
    else:
        recommendation = "ocr"

    return {
        "has_text_layer": pages_with_text > 0,
        "total_pages": total_pages,
        "pages_with_text": pages_with_text,
        "text_coverage_ratio": round(text_ratio, 2),
        "total_text_blocks": total_blocks,
        "korean_blocks": korean_blocks,
        "recommendation": recommendation
    }


def extract_korean_texts_for_translation(
    pdf_path: str,
    group_lines: bool = True
) -> list[dict]:
    """
    번역을 위한 한글 텍스트 추출 (스마트 그룹화 지원)

    Args:
        pdf_path: PDF 파일 경로
        group_lines: True면 인접 라인을 그룹화, False면 라인 단위

    Returns:
        [
            {
                "page_num": 1,
                "block_id": "p1_b0",
                "text": "한글 텍스트",
                "bbox": (x0, y0, x1, y1),
                "font": "맑은고딕",
                "size": 24,
                "role": "title",  # title, heading, body, bullet, caption, footer
                "color": 0,
            },
            ...
        ]
    """
    import re
    doc = fitz.open(pdf_path)
    all_texts = []

    # 심볼 폰트 목록 (bullet point 등)
    SYMBOL_FONTS = {"wingdings", "symbol", "webdings", "zapfdingbats"}

    for page_num, page in enumerate(doc):
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        page_rect = page.rect
        page_lines = []  # 이 페이지의 모든 라인
        block_idx = 0

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # 텍스트 블록만
                continue

            block_bbox = block.get("bbox", (0, 0, 0, 0))

            for line in block.get("lines", []):
                line_bbox = line.get("bbox", (0, 0, 0, 0))
                line_texts = []
                line_font = ""
                line_size = 12.0
                line_color = 0
                has_bullet = False

                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    span_font = span.get("font", "")

                    # 심볼 폰트 체크 (Wingdings 등)
                    if any(sf in span_font.lower() for sf in SYMBOL_FONTS):
                        has_bullet = True
                        # bullet point를 "- "로 변환 (ASCII, 폰트 호환성)
                        if span_text.strip():
                            line_texts.append("- ")
                        continue

                    if span_text.strip():
                        line_texts.append(span_text)
                        if not line_font:
                            line_font = span_font
                            line_size = span.get("size", 12.0)
                            line_color = span.get("color", 0)

                # 라인 텍스트 합치기
                full_text = "".join(line_texts).strip()
                if not full_text:
                    continue

                # 한글 포함 여부 확인
                has_korean = bool(re.search(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', full_text))
                if not has_korean:
                    continue

                # 숫자/페이지 번호 스킵 (숫자가 주된 내용인 경우)
                text_without_numbers = re.sub(r'[0-9.,/:%\s-]', '', full_text)
                if len(text_without_numbers) < 2:  # 거의 숫자로만 구성된 경우
                    continue


                # 자모 분리된 한글 감지 (폰트 인코딩 문제)
                # 정상 한글: 가-힣 (완성형), 문제 한글: ㄱ-ㅎ, ㅏ-ㅣ (자모)
                jamo_count = len(re.findall(r'[\u1100-\u11ff\u3130-\u318f]', full_text))
                complete_count = len(re.findall(r'[\uac00-\ud7af]', full_text))
                # 자모가 완성형보다 많으면 깨진 텍스트로 판단
                if jamo_count > complete_count * 2 and jamo_count > 3:
                    continue

                # bbox가 페이지 영역 밖인 경우 스킵 (숨겨진 텍스트)
                x0, y0, x1, y1 = line_bbox
                if y0 < 0 or x0 < 0 or y1 > page_rect.height + 10 or x1 > page_rect.width + 10:
                    continue

                # bbox 크기가 너무 작은 경우 스킵
                if (x1 - x0) < 5 or (y1 - y0) < 5:
                    continue

                # role 추론
                role = _infer_line_role(
                    full_text, line_bbox, line_size,
                    page_rect, has_bullet
                )

                page_lines.append({
                    "page_num": page_num + 1,
                    "text": full_text,
                    "bbox": tuple(line_bbox),
                    "block_bbox": tuple(block_bbox),  # PDF block 영역
                    "block_idx": block_idx,  # PDF block 인덱스
                    "font": line_font,
                    "size": line_size,
                    "color": line_color,
                    "role": role,
                    "has_bullet": has_bullet,
                })

            block_idx += 1

        # 그룹화 여부에 따라 처리
        if group_lines and page_lines:
            grouped = _group_adjacent_lines(page_lines, page_rect)
            all_texts.extend(grouped)
        else:
            # 라인 단위로 block_id 부여
            for idx, line in enumerate(page_lines):
                line["block_id"] = f"p{page_num + 1}_l{idx}"
                del line["has_bullet"]  # 내부용 필드 제거
                all_texts.append(line)

    doc.close()
    return all_texts


def _infer_line_role(
    text: str,
    bbox: tuple,
    font_size: float,
    page_rect,
    has_bullet: bool
) -> str:
    """라인의 role 추론"""
    x0, y0, x1, y1 = bbox
    page_width = page_rect.width
    page_height = page_rect.height

    # 위치 비율
    y_ratio = y0 / page_height if page_height > 0 else 0
    x_center = (x0 + x1) / 2
    is_centered = abs(x_center - page_width / 2) < page_width * 0.15

    # bullet point
    if has_bullet or text.startswith("- ") or text.startswith("• "):
        return "bullet"

    # 페이지 상단 + 큰 폰트 = title
    if y_ratio < 0.15 and font_size >= 20:
        return "title"

    # 중간 크기 + 중앙 정렬 = heading
    if font_size >= 16 and is_centered:
        return "heading"

    # 페이지 하단 = footer/source
    if y_ratio > 0.85:
        if font_size <= 10:
            return "footer"
        return "source"

    # 작은 폰트 = caption
    if font_size <= 10:
        return "caption"

    # 기본 = body
    return "body"


def _is_sentence_end(text: str) -> bool:
    """문장이 종결되었는지 확인"""
    text = text.rstrip()
    if not text:
        return False
    # 한국어/영어 문장 종결 부호
    return text[-1] in '.!?。？！'


def _is_continuation(text: str) -> bool:
    """이전 문장의 continuation인지 확인"""
    text = text.lstrip()
    if not text:
        return False
    if text[0].islower():
        return True
    continuation_starts = ['고', '며', '면', '니', '라', '를', '을', '는', '은', '이', '가', '에', '로', '와', '과']
    if text[0] in continuation_starts:
        return True
    return False


def _is_text_char(c: str) -> bool:
    """한글, 영어, 숫자인지 확인"""
    if not c:
        return False
    # 한글 (완성형 + 자모)
    if '\uac00' <= c <= '\ud7af' or '\u1100' <= c <= '\u11ff' or '\u3130' <= c <= '\u318f':
        return True
    # 영어
    if 'a' <= c <= 'z' or 'A' <= c <= 'Z':
        return True
    # 숫자
    if '0' <= c <= '9':
        return True
    return False


def _separate_prefix(text: str, font_size: float) -> tuple[str, str, float]:
    """텍스트에서 prefix 특수기호 분리 (한글/영어/숫자 아닌 것들)"""
    if not text:
        return text, "", 0.0
    prefix = ""
    i = 0
    while i < len(text):
        c = text[i]
        if c in (' ', '\t'):
            if prefix:  # 기호 뒤 공백은 prefix에 포함
                prefix += c
                i += 1
                break
            else:
                break
        elif _is_text_char(c):
            break  # 텍스트 시작
        else:
            prefix += c  # 특수기호
            i += 1
    if not prefix:
        return text, "", 0.0
    text_without = text[len(prefix):].lstrip()
    width = len([c for c in prefix if c not in ' \t']) * font_size * 0.8
    return text_without, prefix, width


def _group_adjacent_lines(
    lines: list[dict],
    page_rect
) -> list[dict]:
    """
    인접 라인을 paragraph 단위로 그룹화 (강화 버전)

    그룹화 조건:
    - 같은 PDF text block (block_idx)
    - Y 좌표 차이가 line height의 1.8배 이내
    - X 좌표가 비슷하거나 들여쓰기 (continuation)
    - font size/color가 비슷
    - 앞 line이 문장 종결로 끝나지 않음
    - bullet 첫 줄은 개별, 그 뒤 continuation은 병합
    """
    if not lines:
        return []

    # Y 좌표로 정렬
    sorted_lines = sorted(lines, key=lambda x: (x["bbox"][1], x["bbox"][0]))

    groups = []
    current_group = None

    for line in sorted_lines:
        role = line["role"]
        text = line["text"]
        has_bullet = line.get("has_bullet", False)

        # 새 그룹 시작 조건 확인
        start_new_group = False

        if current_group is None:
            start_new_group = True
        else:
            prev_line = current_group["lines"][-1]
            prev_text = prev_line["text"]
            prev_bbox = prev_line["bbox"]
            curr_bbox = line["bbox"]

            # 같은 PDF block인지
            same_block = line.get("block_idx") == prev_line.get("block_idx")

            # Y 간격 확인
            y_gap = curr_bbox[1] - prev_bbox[3]
            line_height = prev_line["size"] * 1.2
            y_close = -5 < y_gap < line_height * 1.8

            # X 좌표 확인 (같은 위치 또는 들여쓰기)
            x_diff = curr_bbox[0] - prev_bbox[0]
            x_similar = abs(x_diff) < 30  # 거의 같은 위치
            x_indented = 0 < x_diff < 100  # 들여쓰기 (continuation)

            # font size 비슷
            size_similar = abs(line["size"] - prev_line["size"]) < 2

            # color 같음
            color_same = line["color"] == prev_line["color"]

            # 이전 줄이 문장 종결인지
            prev_ends_sentence = _is_sentence_end(prev_text)

            # 현재 줄이 continuation인지
            curr_is_continuation = _is_continuation(text)

            # title/heading은 개별 유지 (단, 이전 줄이 문장 미종결이고 Y가 가까우면 continuation)
            if role in ("title", "heading"):
                # 이전 줄이 문장 종결이 아니고, Y가 가깝고, 폰트가 비슷하면 continuation으로 병합
                if not prev_ends_sentence and y_close and size_similar:
                    start_new_group = False
                else:
                    start_new_group = True
            # bullet 첫 줄은 새 그룹 (단, 이전 bullet의 continuation은 병합)
            elif has_bullet or text.startswith("- "):
                start_new_group = True
            # 이전 줄이 bullet이고 현재 줄이 continuation인 경우 병합
            elif current_group.get("is_bullet") and not prev_ends_sentence and y_close and size_similar:
                start_new_group = False
            # 같은 block이고, Y가 가깝고, X가 비슷하거나 들여쓰기
            elif same_block and y_close and (x_similar or x_indented):
                # 폰트/색상이 같고, 문장 종결이 아니면 병합
                if size_similar and color_same:
                    if not prev_ends_sentence or curr_is_continuation:
                        start_new_group = False
                    else:
                        start_new_group = True
                else:
                    start_new_group = True
            # 다른 block이지만 연속 가능성 체크
            elif y_close and x_indented and not prev_ends_sentence:
                if size_similar and color_same:
                    start_new_group = False
                else:
                    start_new_group = True
            else:
                start_new_group = True

        if start_new_group:
            if current_group:
                groups.append(current_group)
            current_group = {
                "lines": [line],
                "role": role,
                "is_bullet": has_bullet or text.startswith("- "),
            }
        else:
            current_group["lines"].append(line)

    if current_group:
        groups.append(current_group)

    # 그룹을 최종 포맷으로 변환
    result = []
    page_num = lines[0]["page_num"] if lines else 1

    for idx, group in enumerate(groups):
        group_lines = group["lines"]
        role = group["role"]
        is_bullet = group.get("is_bullet", False)

        # bbox 병합 (전체 영역)
        x0 = min(l["bbox"][0] for l in group_lines)
        y0 = min(l["bbox"][1] for l in group_lines)
        x1 = max(l["bbox"][2] for l in group_lines)
        y1 = max(l["bbox"][3] for l in group_lines)

        # 텍스트 병합
        texts = [l["text"] for l in group_lines]
        if is_bullet:
            # bullet: 첫 줄 유지하고 continuation 병합
            text = " ".join(texts)
        else:
            # 일반 텍스트: 공백으로 연결
            text = " ".join(texts)

        # 대표 폰트/크기/색상 (첫 번째 라인 기준)
        first_line = group_lines[0]

        # 여러 줄 병합 시 role 재결정
        if len(group_lines) > 1:
            role = "body" if not is_bullet else "bullet"

        # prefix 분리 (•, ■ 등 Helvetica 비호환 기호)
        text_for_trans, prefix, prefix_width = _separate_prefix(text, first_line["size"])

        # 라인별 색상/텍스트 정보 보존 (다중 색상 span 처리용)
        line_colors = [l["color"] for l in group_lines]
        line_texts = [l["text"] for l in group_lines]
        has_multi_color = len(set(line_colors)) > 1

        result.append({
            "page_num": page_num,
            "block_id": f"p{page_num}_b{idx}",
            "text": text,
            "text_for_translation": text_for_trans if text_for_trans else text,
            "prefix": prefix,
            "prefix_width": prefix_width,
            "bbox": (x0, y0, x1, y1),
            "font": first_line["font"],
            "size": first_line["size"],
            "color": first_line["color"],
            "role": role,
            # 다중 색상 span 정보
            "line_colors": line_colors,
            "line_texts": line_texts,
            "has_multi_color": has_multi_color,
        })

    return result


if __name__ == "__main__":
    # 테스트
    import sys
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]

        print("=== PDF 텍스트 레이어 분석 ===")
        info = check_pdf_has_text_layer(pdf_path)
        for k, v in info.items():
            print(f"  {k}: {v}")

        print("\n=== 한글 텍스트 추출 ===")
        korean_texts = extract_korean_texts_for_translation(pdf_path)
        for item in korean_texts[:5]:
            print(f"  [{item['block_id']}] {item['text'][:50]}...")
