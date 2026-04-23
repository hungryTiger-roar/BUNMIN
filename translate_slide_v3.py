"""
강의 슬라이드 번역 파이프라인 v3
- 서비스 통합용 (함수 호출 가능)
- 숫자/영어 전용 영역 스킵
- 텍스트 오버플로우 방지

사용법:
    python translate_slide_v3.py --image slide.png

서비스 통합:
    from translate_slide_v3 import translate_slide
    result = translate_slide("slide.png", "output.png")
"""

import argparse
import gc
import json
import os
import re
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# .env 로드
load_dotenv(Path(__file__).parent / ".env")

# VLM 설정 (환경변수 또는 기본값)
VLM_BASE_MODEL = os.environ.get("VLM_BASE_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
VLM_LORA_PATH = Path(__file__).parent / os.environ.get("VLM_LORA_PATH", "models/qwen3/qwen3-vl-8b-lora-r64-e3-final")
VLM_DEVICE = os.environ.get("VLM_DEVICE", "cuda")
VLM_MAX_GPU_MEMORY = os.environ.get("VLM_MAX_GPU_MEMORY", "7GB")
VLM_USE_4BIT = os.environ.get("VLM_USE_4BIT", "true").lower() == "true"

# ============================================================
# 전역 모델 (싱글톤) - 한 번만 로드
# ============================================================
_vlm_model = None
_vlm_processor = None


def get_vlm_model():
    """VLM 모델 싱글톤 - 최초 1회만 로드"""
    global _vlm_model, _vlm_processor

    if _vlm_model is not None:
        return _vlm_model, _vlm_processor

    from transformers import AutoProcessor, AutoModelForImageTextToText, BitsAndBytesConfig
    from peft import PeftModel

    print(f"[VLM] 모델 최초 로드 중... (4bit={VLM_USE_4BIT})")
    print(f"[VLM] Base: {VLM_BASE_MODEL}")
    print(f"[VLM] LoRA: {VLM_LORA_PATH}")

    if VLM_USE_4BIT:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            llm_int8_enable_fp32_cpu_offload=True,
        )
        model_kwargs = {
            "quantization_config": bnb_config,
            "device_map": "auto",
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
            "max_memory": {0: VLM_MAX_GPU_MEMORY, "cpu": "16GB"},
        }
    else:
        model_kwargs = {
            "torch_dtype": torch.float16,
            "device_map": "auto",
            "trust_remote_code": True,
        }

    _vlm_processor = AutoProcessor.from_pretrained(
        str(VLM_LORA_PATH),
        trust_remote_code=True,
        min_pixels=256 * 28 * 28,
        max_pixels=512 * 28 * 28,
    )

    base_model = AutoModelForImageTextToText.from_pretrained(
        VLM_BASE_MODEL,
        **model_kwargs,
    )

    _vlm_model = PeftModel.from_pretrained(base_model, str(VLM_LORA_PATH))
    _vlm_model.eval()

    print("[VLM] 모델 로드 완료! (전역 캐시됨)")
    return _vlm_model, _vlm_processor


def is_vlm_loaded() -> bool:
    """VLM 모델 로드 여부 확인"""
    return _vlm_model is not None


def unload_vlm_model():
    """VLM 모델 언로드 (GPU 메모리 해제)"""
    global _vlm_model, _vlm_processor

    if _vlm_model is None:
        print("[VLM] 언로드할 모델 없음")
        return

    print("[VLM] 모델 언로드 중...")
    del _vlm_model
    del _vlm_processor
    _vlm_model = None
    _vlm_processor = None

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print("[VLM] 모델 언로드 완료, GPU 메모리 해제됨")


def is_number_or_english_only(text: str) -> bool:
    """숫자, 영어, 기호만 있는지 확인 (번역 불필요)"""
    # 한글이 하나라도 있으면 False
    if re.search(r'[가-힣]', text):
        return False
    # 숫자, 영어, 공백, 기호만 있으면 True
    return bool(re.match(r'^[0-9a-zA-Z\s\.\,\-\_\:\;\!\?\@\#\$\%\&\*\(\)\[\]\{\}\/\\]+$', text))


# ============================================================
# 1단계: OCR - 텍스트 영역(박스) 추출
# ============================================================
def stage_ocr(image_path: str) -> list:
    """EasyOCR로 텍스트 영역 좌표 추출"""
    print("\n" + "=" * 60)
    print("[1/3] OCR: 텍스트 영역 감지")
    print("=" * 60)

    import easyocr

    print("  OCR 모델 로드 중...")
    reader = easyocr.Reader(['ko', 'en'], gpu=True)

    print("  텍스트 영역 추출 중...")
    result = reader.readtext(image_path)

    regions = []
    for detection in result:
        box = detection[0]
        text = detection[1]
        confidence = detection[2]

        x_coords = [float(p[0]) for p in box]
        y_coords = [float(p[1]) for p in box]
        bbox = [min(x_coords), min(y_coords), max(x_coords), max(y_coords)]

        # 숫자/영어만 있는 영역 표시
        skip_translate = is_number_or_english_only(text)

        regions.append({
            "bbox": bbox,
            "ocr_text": text,
            "confidence": float(confidence),
            "skip_translate": skip_translate,
        })

        status = "(스킵)" if skip_translate else ""
        print(f"  영역 {len(regions)}: '{text[:20]}' {status}")

    print(f"\n  총 {len(regions)}개 영역 감지")

    # GPU 메모리 해제
    del reader
    gc.collect()
    torch.cuda.empty_cache()
    print("  GPU 메모리 해제 완료")

    return regions


# ============================================================
# 2단계: 번역 - 전체 이미지 + OCR 텍스트 활용
# ============================================================
def stage_translate(image_path: str, regions: list) -> list:
    """전체 슬라이드 맥락 + OCR 텍스트로 번역 (환각 방지)"""
    print("\n" + "=" * 60)
    print("[2/3] 번역: 전체 슬라이드 맥락 + OCR 텍스트 (Qwen3-VL)")
    print("=" * 60)

    # 번역할 텍스트 필터링
    to_translate = []
    for i, region in enumerate(regions):
        if region.get("skip_translate", False):
            region["english"] = region["ocr_text"]
            print(f"  [{i+1}] 스킵 (영어/숫자): '{region['ocr_text'][:20]}'")
            continue

        bbox = region["bbox"]
        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min

        MIN_AREA = 500
        if width * height < MIN_AREA:
            region["english"] = region["ocr_text"]
            print(f"  [{i+1}] 스킵 (작음): '{region['ocr_text'][:20]}'")
            continue

        to_translate.append((i, region))

    if not to_translate:
        print("  번역할 텍스트 없음")
        return regions

    print(f"\n  번역 대상: {len(to_translate)}개 텍스트")

    # 전역 모델 사용
    model, processor = get_vlm_model()
    print("  모델 준비 완료 (캐시됨)")

    # 전체 슬라이드 이미지 로드
    original_image = Image.open(image_path).convert("RGB")

    # OCR 텍스트 목록 생성
    text_list = "\n".join([f"{idx+1}. {region['ocr_text']}" for idx, (_, region) in enumerate(to_translate)])

    PROMPT = f"""This is a Korean lecture slide. Below are Korean texts extracted by OCR.
Translate each text to English.

Korean texts:
{text_list}

Rules:
- Translate Korean to English meanings (not romanization)
- Keep numbers as-is: "01" stays "01"
- Keep English words unchanged
- IT terms: "목업"→"Mockup", "데모"→"Demo", "알고리즘"→"Algorithm"
- University names: "명지대학교"→"Myongji University"

Output format (one translation per line, same order):
1. [English translation]
2. [English translation]
..."""

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": PROMPT},
            ],
        },
    ]

    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[original_image], return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=500,
            temperature=0.3,
            do_sample=True,
        )

    input_len = inputs["input_ids"].shape[1]
    response = processor.decode(outputs[0][input_len:], skip_special_tokens=True).strip()

    print(f"\n  VLM 응답:\n{response[:300]}...")

    # 응답 파싱
    lines = response.strip().split("\n")
    translations = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # "1. Translation" 형태에서 번역만 추출
        if line and line[0].isdigit() and "." in line:
            parts = line.split(".", 1)
            if len(parts) > 1:
                trans = parts[1].strip().strip('"\'')
                translations.append(trans)
        else:
            # 숫자 없이 바로 번역만 있는 경우
            translations.append(line.strip('"\''))

    # 번역 결과 매핑
    for idx, (region_idx, region) in enumerate(to_translate):
        if idx < len(translations):
            region["english"] = translations[idx]
            print(f"  [{region_idx+1}] '{region['ocr_text'][:15]}' → '{translations[idx][:30]}'")
        else:
            # 번역 실패 시 원본 유지
            region["english"] = region["ocr_text"]
            print(f"  [{region_idx+1}] '{region['ocr_text'][:15]}' → (번역 실패, 원본 유지)")

    print(f"\n  {len(to_translate)}개 영역 번역 완료")

    return regions


# ============================================================
# 3단계: 오버레이 (텍스트 클리핑 + 줄바꿈)
# ============================================================
def stage_overlay(image_path: str, regions: list, output_path: str):
    """번역된 텍스트 오버레이 (영역 내 제한)"""
    print("\n" + "=" * 60)
    print("[3/3] 오버레이: 이미지 생성")
    print("=" * 60)

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    def get_font(size):
        for font_path in ["arial.ttf", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/malgun.ttf"]:
            try:
                return ImageFont.truetype(font_path, size)
            except:
                continue
        return ImageFont.load_default()

    def wrap_text(text: str, max_width: float, font, draw) -> list:
        """텍스트를 박스 너비에 맞게 줄바꿈"""
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip() if current_line else word
            bbox = draw.textbbox((0, 0), test_line, font=font)
            text_width = bbox[2] - bbox[0]

            if text_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return lines if lines else [text]

    def fit_text_to_box(text: str, max_width: float, max_height: float, font_size: int, draw) -> tuple:
        """텍스트를 박스에 맞게 조정 (줄바꿈 + 폰트 축소)"""
        font = get_font(font_size)

        # 폰트 크기 줄이면서 박스에 맞추기 (최소 6pt까지)
        while font_size > 6:
            font = get_font(font_size)
            lines = wrap_text(text, max_width, font, draw)

            # 총 높이 계산
            line_height = font_size + 2
            total_height = line_height * len(lines)

            if total_height <= max_height:
                return lines, font, font_size, line_height

            font_size -= 1

        # 최소 폰트로도 안 맞으면 그냥 반환
        font = get_font(font_size)
        lines = wrap_text(text, max_width, font, draw)
        line_height = font_size + 2
        return lines, font, font_size, line_height

    for region in regions:
        # 스킵 조건
        if region.get("skip_translate", False):
            print(f"  원본 유지: '{region['ocr_text'][:15]}'")
            continue

        bbox = region["bbox"]
        english = region.get("english", region["ocr_text"])

        x_min, y_min, x_max, y_max = bbox
        width = x_max - x_min
        height = y_max - y_min

        if width * height < 500:
            continue

        # 번역이 원본과 같으면 스킵
        if english.strip() == region["ocr_text"].strip():
            print(f"  원본 유지: '{english[:20]}'")
            continue

        # 배경색 샘플링
        try:
            sample_x = max(0, int(x_min) - 5)
            sample_y = int((y_min + y_max) / 2)
            bg_color = img.getpixel((sample_x, sample_y))
            if isinstance(bg_color, int):
                bg_color = (bg_color, bg_color, bg_color)
        except:
            bg_color = (255, 255, 255)

        # 원본 영역만 덮기 (정확한 크기)
        draw.rectangle([x_min, y_min, x_max, y_max], fill=bg_color)

        # 텍스트 맞추기 (줄바꿈 + 폰트 축소)
        initial_font_size = max(12, int(height * 0.7))
        lines, font, final_font_size, line_height = fit_text_to_box(
            english, width - 4, height - 4, initial_font_size, draw
        )

        # 텍스트 색상
        brightness = sum(bg_color) / 3
        text_color = (0, 0, 0) if brightness > 127 else (255, 255, 255)

        # 텍스트 그리기 (왼쪽 정렬, 세로 중앙)
        total_text_height = line_height * len(lines)
        start_y = y_min + (height - total_text_height) / 2

        for i, line in enumerate(lines):
            text_x = x_min + 2  # 왼쪽 여백 2px
            text_y = start_y + (i * line_height)
            draw.text((text_x, text_y), line, font=font, fill=text_color)

        fitted_text = " ".join(lines)
        if len(lines) > 1:
            print(f"  '{region['ocr_text'][:15]}' → '{fitted_text[:25]}' ({len(lines)}줄)")
        else:
            print(f"  '{region['ocr_text'][:15]}' → '{fitted_text[:25]}'")

    img.save(output_path)
    print(f"\n  저장됨: {output_path}")

    return output_path


# ============================================================
# 서비스 통합용 함수
# ============================================================
def translate_slide(image_path: str, output_path: str = None) -> dict:
    """
    슬라이드 번역 (서비스 통합용)

    Args:
        image_path: 입력 이미지 경로
        output_path: 출력 이미지 경로 (기본: {이름}_translated_v3.png)

    Returns:
        dict: {
            "input": 입력 경로,
            "output": 출력 경로,
            "regions": 번역된 영역 리스트,
            "success": 성공 여부
        }
    """
    try:
        if output_path is None:
            p = Path(image_path)
            output_path = str(p.parent / f"{p.stem}_translated_v3{p.suffix}")

        # 파이프라인 실행
        regions = stage_ocr(image_path)
        regions = stage_translate(image_path, regions)
        stage_overlay(image_path, regions, output_path)

        return {
            "input": image_path,
            "output": output_path,
            "regions": regions,
            "success": True,
        }

    except Exception as e:
        return {
            "input": image_path,
            "output": None,
            "error": str(e),
            "success": False,
        }


# ============================================================
# 메인
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="강의 슬라이드 번역 v3")
    parser.add_argument("--image", type=str, required=True, help="입력 이미지")
    parser.add_argument("--output", type=str, default=None, help="출력 이미지")
    args = parser.parse_args()

    image_path = args.image
    if args.output:
        output_path = args.output
    else:
        p = Path(image_path)
        output_path = str(p.parent / f"{p.stem}_translated_v3{p.suffix}")

    print("=" * 60)
    print("강의 슬라이드 번역 파이프라인 v3")
    print("=" * 60)
    print(f"입력: {image_path}")
    print(f"출력: {output_path}")

    # 1단계: OCR
    regions = stage_ocr(image_path)

    with open(Path(image_path).stem + "_regions.json", "w", encoding="utf-8") as f:
        json.dump(regions, f, ensure_ascii=False, indent=2)

    # 2단계: 번역
    regions = stage_translate(image_path, regions)

    with open(Path(image_path).stem + "_translated_v3.json", "w", encoding="utf-8") as f:
        json.dump(regions, f, ensure_ascii=False, indent=2)

    # 3단계: 오버레이
    stage_overlay(image_path, regions, output_path)

    print("\n" + "=" * 60)
    print("완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
