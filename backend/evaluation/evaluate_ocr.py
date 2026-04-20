"""
OCR 평가 스크립트

dataset/ground_truth.json 기준으로 RapidOCR 결과와 비교
지표: CER (Character Error Rate), WER (Word Error Rate)
"""
import json
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).parent / "dataset"
GT_FILE = DATASET_DIR / "ground_truth.json"
RESULT_FILE = Path(__file__).parent / "eval_result.json"


def cer(gt: str, pred: str) -> float:
    """Character Error Rate (편집거리 기반)"""
    if not gt:
        return 0.0 if not pred else 1.0

    import editdistance
    return editdistance.eval(gt, pred) / len(gt)


def wer(gt: str, pred: str) -> float:
    """Word Error Rate"""
    gt_words = gt.split()
    pred_words = pred.split()
    if not gt_words:
        return 0.0 if not pred_words else 1.0

    import editdistance
    return editdistance.eval(gt_words, pred_words) / len(gt_words)


def run_ocr(image_path: Path) -> str:
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    result, _ = ocr(str(image_path))
    if not result:
        return ""
    return "\n".join([line[1] for line in result if line[2] >= 0.5])


def evaluate():
    if not GT_FILE.exists():
        print("[ERROR] ground_truth.json 이 없습니다. build_dataset.py 를 먼저 실행하세요.")
        sys.exit(1)

    try:
        import editdistance  # noqa
    except ImportError:
        print("[ERROR] editdistance 패키지가 필요합니다: pip install editdistance")
        sys.exit(1)

    ground_truth = json.loads(GT_FILE.read_text(encoding="utf-8"))
    print(f"평가 대상: {len(ground_truth)}개 슬라이드\n")

    results = []
    total_cer, total_wer = 0.0, 0.0

    for i, item in enumerate(ground_truth, 1):
        image_path = DATASET_DIR / item["image"]
        gt_text = item["ground_truth"]

        print(f"[{i:3d}/{len(ground_truth)}] {item['id']} ...", end=" ", flush=True)
        pred_text = run_ocr(image_path)

        item_cer = cer(gt_text, pred_text)
        item_wer = wer(gt_text, pred_text)
        total_cer += item_cer
        total_wer += item_wer

        print(f"CER={item_cer:.3f}  WER={item_wer:.3f}")

        results.append({
            **item,
            "predicted": pred_text,
            "cer": round(item_cer, 4),
            "wer": round(item_wer, 4),
        })

    avg_cer = total_cer / len(ground_truth)
    avg_wer = total_wer / len(ground_truth)

    summary = {
        "total_slides": len(ground_truth),
        "avg_cer": round(avg_cer, 4),
        "avg_wer": round(avg_wer, 4),
        "details": results,
    }

    RESULT_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*40}")
    print(f"평균 CER : {avg_cer:.4f} ({avg_cer*100:.1f}%)")
    print(f"평균 WER : {avg_wer:.4f} ({avg_wer*100:.1f}%)")
    print(f"결과 저장: {RESULT_FILE}")


if __name__ == "__main__":
    evaluate()
