"""
OCR (Optical Character Recognition) 평가
품질: CER (Character Error Rate)
속도: 지연시간, 처리량
"""
import json
from pathlib import Path

from evaluation.metrics.cer import compute_avg_cer
from evaluation.metrics.speed import timer, compute_throughput, summarize_latencies

DATASETS_DIR = Path(__file__).parent.parent / "datasets"


def eval_ocr() -> dict:
    print("\n[OCR] 평가 시작...")

    from app.services.ocr_service import OCRService

    ocr_dir = DATASETS_DIR / "ocr_samples"
    ground_truth_path = ocr_dir / "ground_truth.json"

    if not ground_truth_path.exists():
        print("[OCR] ground_truth.json 없음. datasets/ocr_samples/ 에 이미지와 정답을 추가하세요.")
        return {"skipped": True, "reason": "no_ocr_samples"}

    with open(ground_truth_path, encoding="utf-8") as f:
        samples = json.load(f)

    image_samples = [s for s in samples if (ocr_dir / s["file"]).exists()]

    if not image_samples:
        print("[OCR] 이미지 파일 없음.")
        return {"skipped": True, "reason": "no_image_files"}

    service = OCRService()

    cer_pairs = []
    latencies_ms = []

    for sample in image_samples:
        img_bytes = (ocr_dir / sample["file"]).read_bytes()

        with timer() as t:
            texts = service.extract_texts(img_bytes)

        elapsed_ms = t["elapsed"] * 1000
        latencies_ms.append(elapsed_ms)

        hypothesis = " ".join(texts)
        cer_pairs.append((sample["text"], hypothesis))

        print(f"  [{sample['file']}] {elapsed_ms:.1f}ms")
        print(f"    정답: {sample['text'][:50]}")
        print(f"    추출: {hypothesis[:50]}")

    cer_result = compute_avg_cer(cer_pairs)
    speed_result = summarize_latencies(latencies_ms)
    throughput = compute_throughput(sum(latencies_ms) / 1000, len(image_samples))

    result = {
        "model": service.mode,
        "quality": {
            "avg_cer": round(cer_result["avg_cer"], 4),
            "per_sample_cer": [round(c, 4) for c in cer_result["per_sample"]],
        },
        "speed": {
            "throughput_per_sec": round(throughput, 2),
            **{k: round(v, 1) for k, v in speed_result.items()},
        },
        "num_samples": len(image_samples),
    }

    print(f"\n[OCR] 결과: CER={result['quality']['avg_cer']:.1%} | "
          f"처리량={throughput:.1f}이미지/초 | 평균지연={speed_result.get('avg_ms', 0):.1f}ms")
    return result
