"""
VLM 기반 Bbox 분석 모듈

페이지 이미지와 텍스트 블록 정보를 VLM에 전달하여:
1. 이미지/다이어그램 위 텍스트 감지 (확장 금지)
2. 병합해야 할 텍스트 블록 판단
3. 기호/prefix 처리 방식 결정

사용법:
    from .bbox_analyzer import analyze_page_layout

    analysis = analyze_page_layout(
        page_image,  # PIL Image or numpy array
        text_blocks  # list of {block_id, text, bbox, ...}
    )
"""
import os
import json
import re
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# VLM 모델 로드를 위한 전역 변수
_vlm_model = None
_vlm_processor = None


def get_vlm_for_analysis():
    """VLM 모델 로드 (translate_slide_v3와 공유)"""
    global _vlm_model, _vlm_processor

    if _vlm_model is not None:
        return _vlm_model, _vlm_processor

    try:
        # translate_slide_v3의 VLM 모델 재사용 시도
        import sys
        sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))))
        from translate_slide_v3 import get_vlm_model
        _vlm_model, _vlm_processor = get_vlm_model()
        return _vlm_model, _vlm_processor
    except Exception as e:
        print(f"[BboxAnalyzer] VLM 로드 실패: {e}")
        return None, None


def draw_bboxes_on_image(
    image: Image.Image,
    text_blocks: list[dict],
    show_labels: bool = True
) -> Image.Image:
    """이미지에 bbox 표시 (VLM 입력용)"""
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)

    # 폰트 로드
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    except:
        font = ImageFont.load_default()

    colors = [
        (255, 0, 0),    # 빨강
        (0, 255, 0),    # 초록
        (0, 0, 255),    # 파랑
        (255, 165, 0),  # 주황
        (128, 0, 128),  # 보라
        (0, 128, 128),  # 청록
    ]

    for idx, block in enumerate(text_blocks):
        bbox = block.get("bbox", [0, 0, 0, 0])
        block_id = block.get("block_id", f"b{idx}")

        color = colors[idx % len(colors)]
        x0, y0, x1, y1 = [int(v) for v in bbox]

        # bbox 그리기
        draw.rectangle([x0, y0, x1, y1], outline=color, width=2)

        # 라벨 그리기
        if show_labels:
            label = f"[{idx}]"
            draw.text((x0 + 2, y0 - 16), label, fill=color, font=font)

    return img_copy


def create_block_description(text_blocks: list[dict]) -> str:
    """텍스트 블록 설명 생성 (VLM 프롬프트용)"""
    lines = []
    for idx, block in enumerate(text_blocks):
        text = block.get("text", "")[:50]  # 50자로 제한
        bbox = block.get("bbox", [0, 0, 0, 0])
        role = block.get("role", "body")
        prefix = block.get("prefix", "")

        lines.append(f"[{idx}] text=\"{text}\" role={role} prefix=\"{prefix}\"")

    return "\n".join(lines)


def analyze_page_layout(
    page_image,
    text_blocks: list[dict],
    use_vlm: bool = True
) -> dict:
    """
    VLM으로 페이지 레이아웃 분석

    Args:
        page_image: PIL Image 또는 numpy array
        text_blocks: 텍스트 블록 리스트
            [{"block_id": "p1_b0", "text": "...", "bbox": [x0,y0,x1,y1], "role": "body", "prefix": ""}, ...]
        use_vlm: VLM 사용 여부 (False면 휴리스틱만 사용)

    Returns:
        {
            "blocks": [
                {
                    "block_id": "p1_b0",
                    "on_image_background": True/False,  # 이미지 위 텍스트인지
                    "expand_allowed": True/False,       # bbox 확장 허용
                    "merge_with": [],                   # 병합할 block_id 리스트
                    "keep_prefix": True/False,          # 기호 유지
                },
                ...
            ],
            "merge_groups": [[block_ids], ...],  # 병합 그룹
        }
    """
    # PIL Image로 변환
    if isinstance(page_image, np.ndarray):
        page_image = Image.fromarray(page_image)

    if not use_vlm:
        # VLM 없이 기본값 반환
        return _default_analysis(text_blocks)

    # VLM 로드
    model, processor = get_vlm_for_analysis()
    if model is None:
        print("[BboxAnalyzer] VLM 없음, 기본 분석 사용")
        return _default_analysis(text_blocks)

    # bbox 표시된 이미지 생성
    annotated_image = draw_bboxes_on_image(page_image, text_blocks)

    # 블록 설명 생성
    block_desc = create_block_description(text_blocks)

    # VLM 프롬프트 (보수적으로 - on_image는 매우 제한적으로만)
    prompt = f"""Analyze this slide image with numbered text boxes.

TEXT BLOCKS:
{block_desc}

For each numbered block [0], [1], [2], etc., determine:
1. on_image: Is the text DIRECTLY ON a photo, diagram, chart, or illustration?
   - on_image=true ONLY for: labels inside flowcharts, text on photos, captions on diagrams
   - on_image=false for: slide titles, bullet points, normal text, text on colored slide backgrounds
2. expand_ok: Can the text box expand without covering other content?
3. merge_with: Should this block merge with another block? (give block numbers)
4. keep_prefix: Does this block start with a bullet/symbol that should be preserved?

Return JSON format:
{{
  "blocks": [
    {{"idx": 0, "on_image": false, "expand_ok": true, "merge_with": [], "keep_prefix": false}},
    ...
  ]
}}

CRITICAL RULES for on_image:
- Slide titles → on_image: FALSE (even if on colored header bar)
- Bullet points → on_image: FALSE
- Normal body text → on_image: FALSE
- Text on solid color backgrounds → on_image: FALSE
- ONLY text inside actual diagrams/photos/charts → on_image: TRUE

Default to on_image=false unless clearly inside a diagram.

Return JSON only:"""

    try:
        import torch

        # 이미지를 VLM에 전달 (qwen_vl_utils 없이 직접 처리)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": annotated_image},
                    {"type": "text", "text": prompt}
                ]
            }
        ]

        # Qwen2.5-VL 형식으로 처리 (직접 이미지 전달)
        try:
            text = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
        except TypeError:
            text = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )

        # 이미지를 리스트로 전달
        inputs = processor(
            text=[text],
            images=[annotated_image],
            padding=True,
            return_tensors="pt"
        ).to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=1024,
                temperature=0.1,
                do_sample=False,
            )

        input_len = inputs["input_ids"].shape[1]
        response = processor.decode(outputs[0][input_len:], skip_special_tokens=True).strip()

        # JSON 파싱
        result = _parse_vlm_response(response, text_blocks)
        return result

    except Exception as e:
        print(f"[BboxAnalyzer] VLM 분석 실패: {e}")
        return _default_analysis(text_blocks)


def _parse_vlm_response(response: str, text_blocks: list[dict]) -> dict:
    """VLM 응답 파싱 (강화된 버전)"""
    try:
        # JSON 추출 - 여러 패턴 시도
        data = None

        # 방법 1: {"blocks": [...]} 형태 직접 매칭
        json_match = re.search(r'\{\s*"blocks"\s*:\s*\[[\s\S]*?\]\s*\}', response)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 방법 2: 일반적인 JSON 객체 매칭 (greedy 방지를 위해 balanced bracket 사용)
        if data is None:
            # 코드 블록 안의 JSON 추출
            code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
            if code_block_match:
                try:
                    data = json.loads(code_block_match.group(1).strip())
                except json.JSONDecodeError:
                    pass

        # 방법 3: 첫 번째 { 부터 매칭되는 } 찾기
        if data is None:
            start_idx = response.find('{')
            if start_idx >= 0:
                bracket_count = 0
                end_idx = start_idx
                for i, char in enumerate(response[start_idx:], start_idx):
                    if char == '{':
                        bracket_count += 1
                    elif char == '}':
                        bracket_count -= 1
                        if bracket_count == 0:
                            end_idx = i + 1
                            break
                try:
                    data = json.loads(response[start_idx:end_idx])
                except json.JSONDecodeError:
                    pass

        if data is None:
            print(f"[BboxAnalyzer] JSON 추출 실패. 응답: {response[:200]}...")
            return _default_analysis(text_blocks)

        # VLM이 리스트를 직접 반환하는 경우 처리
        if isinstance(data, list):
            blocks_list = data
        elif isinstance(data, dict):
            blocks_list = data.get("blocks", [])
        else:
            print(f"[BboxAnalyzer] 예상치 못한 데이터 타입: {type(data)}")
            return _default_analysis(text_blocks)

        # VLM 결과를 인덱스 기준으로 매핑
        vlm_blocks_by_idx = {}
        for vlm_block in blocks_list:
            idx = vlm_block.get("idx")
            if idx is not None:
                vlm_blocks_by_idx[idx] = vlm_block

        # 결과 구성
        blocks = []
        for idx, block in enumerate(text_blocks):
            block_id = block.get("block_id", f"unknown_{idx}")

            # block_id에서 인덱스 추출 시도 (p1_b0 → 0)
            block_idx = idx  # 기본값: 리스트 내 위치
            idx_match = re.search(r'b(\d+)', block_id)
            if idx_match:
                block_idx = int(idx_match.group(1))

            # VLM 결과에서 해당 인덱스 찾기
            vlm_block = vlm_blocks_by_idx.get(block_idx, vlm_blocks_by_idx.get(idx, {}))

            # 결과 추가
            blocks.append({
                "block_id": block_id,
                "on_image_background": bool(vlm_block.get("on_image", False)),
                "expand_allowed": bool(vlm_block.get("expand_ok", True)),
                "merge_with": vlm_block.get("merge_with", []) or [],
                "keep_prefix": bool(vlm_block.get("keep_prefix", False)),
            })

        # 병합 그룹 생성
        merge_groups = _build_merge_groups(blocks)

        return {
            "blocks": blocks,
            "merge_groups": merge_groups
        }

    except Exception as e:
        print(f"[BboxAnalyzer] 응답 파싱 실패: {e}")
        import traceback
        traceback.print_exc()

    return _default_analysis(text_blocks)


def _build_merge_groups(blocks: list[dict]) -> list[list[str]]:
    """병합 그룹 생성 (강화된 버전)"""
    groups = []
    visited = set()

    # block_id → 인덱스 매핑 생성
    id_to_block = {b["block_id"]: b for b in blocks}

    for block in blocks:
        block_id = block.get("block_id", "")
        if not block_id or block_id in visited:
            continue

        merge_with = block.get("merge_with", [])
        if not merge_with:
            continue

        # 페이지 번호 추출 (p1_b0 → 1)
        page_match = re.search(r'p(\d+)', block_id)
        page_num = page_match.group(1) if page_match else "1"

        group = [block_id]
        visited.add(block_id)

        for merge_idx in merge_with:
            # merge_idx가 숫자인지 확인
            if not isinstance(merge_idx, int):
                try:
                    merge_idx = int(merge_idx)
                except (ValueError, TypeError):
                    continue

            # 병합 대상 block_id 생성
            merge_block_id = f"p{page_num}_b{merge_idx}"

            # 실제 존재하는 block_id인지 확인
            if merge_block_id in id_to_block and merge_block_id not in visited:
                group.append(merge_block_id)
                visited.add(merge_block_id)

        if len(group) > 1:
            groups.append(group)

    return groups


def _default_analysis(text_blocks: list[dict]) -> dict:
    """VLM 없을 때 기본 분석 (휴리스틱)"""
    blocks = []

    for block in text_blocks:
        block_id = block.get("block_id", "")
        text = block.get("text", "")
        prefix = block.get("prefix", "")
        role = block.get("role", "body")
        size = block.get("size", 12)

        # 휴리스틱 규칙
        # 1. 작은 텍스트(<=12pt)이면서 body role = 다이어그램 라벨일 가능성
        on_image = size <= 12 and role == "body" and len(text) < 20

        # 2. 라벨은 확장 금지
        expand_allowed = not on_image

        # 3. prefix가 있으면 유지
        keep_prefix = bool(prefix)

        blocks.append({
            "block_id": block_id,
            "on_image_background": on_image,
            "expand_allowed": expand_allowed,
            "merge_with": [],
            "keep_prefix": keep_prefix,
        })

    return {
        "blocks": blocks,
        "merge_groups": []
    }


# 테스트용
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python bbox_analyzer.py <image_path> [json_blocks_path]")
        sys.exit(1)

    image_path = sys.argv[1]
    image = Image.open(image_path)

    # 테스트 블록
    test_blocks = [
        {"block_id": "p1_b0", "text": "제목 텍스트", "bbox": [100, 50, 500, 100], "role": "title", "prefix": ""},
        {"block_id": "p1_b1", "text": "- 내용 1", "bbox": [100, 150, 600, 200], "role": "bullet", "prefix": "- "},
        {"block_id": "p1_b2", "text": "사용자", "bbox": [250, 300, 300, 320], "role": "body", "prefix": "", "size": 12},
    ]

    if len(sys.argv) > 2:
        with open(sys.argv[2], 'r', encoding='utf-8') as f:
            test_blocks = json.load(f)

    result = analyze_page_layout(image, test_blocks)
    print(json.dumps(result, indent=2, ensure_ascii=False))
