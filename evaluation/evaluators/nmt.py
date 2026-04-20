import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

"""
NMT (Neural Machine Translation) 평가
품질: BLEU, METEOR, BERTScore
속도: 지연시간, 처리량
"""
import json
from pathlib import Path

from evaluation.metrics.bleu import compute_avg_bleu, compute_avg_meteor, compute_bertscore
from evaluation.metrics.speed import timer, compute_throughput, summarize_latencies

DATASETS_DIR = Path(__file__).parent.parent / "datasets"


def eval_nmt() -> dict:
    print("\n[NMT] 평가 시작...")

    from app.config import ModelConfig
    from app.services.nmt_service import NMTService

    pairs_path = DATASETS_DIR / "nmt_samples" / "ko_en_pairs.json"
    with open(pairs_path, encoding="utf-8") as f:
        samples = json.load(f)

    service = NMTService(model_name=ModelConfig.NMT_MODEL, device=ModelConfig.NMT_DEVICE)

    references = [s["en"] for s in samples]
    ko_texts   = [s["ko"] for s in samples]

    print(f"  배치 번역 중 ({len(samples)}개)...")
    with timer() as t:
        hypotheses = service.translate_batch(ko_texts)
    total_ms = t["elapsed"] * 1000
    per_ms   = total_ms / len(samples)
    latencies_ms = [per_ms] * len(samples)

    for i, (sample, hyp) in enumerate(zip(samples, hypotheses)):
        print(f"  [{i+1}/{len(samples)} | {per_ms:.1f}ms/샘플] {sample['ko'][:20]}...")
        print(f"    정답: {sample['en']}")
        print(f"    번역: {hyp}")

    pairs = list(zip(references, hypotheses))

    bleu_result   = compute_avg_bleu(pairs)
    meteor_result = compute_avg_meteor(pairs)

    print("\n  [BERTScore] 계산 중 (시간이 걸릴 수 있습니다)...")
    bert_result = compute_bertscore(references, hypotheses)

    speed_result = summarize_latencies(latencies_ms)
    total_time = sum(latencies_ms) / 1000
    throughput = compute_throughput(total_time, len(samples))

    quality = {
        "bleu": {
            "avg": round(bleu_result["avg_bleu"], 4),
            "avg_pct": round(bleu_result["avg_bleu"] * 100, 2),
            "per_sample": [round(b, 4) for b in bleu_result["per_sample"]],
            "note": "단어 n-gram 일치율. 동의어 미반영.",
        },
        "meteor": {
            "avg": round(meteor_result["avg_meteor"], 4),
            "avg_pct": round(meteor_result["avg_meteor"] * 100, 2),
            "per_sample": [round(m, 4) for m in meteor_result["per_sample"]],
            "note": "동의어·어간 고려. BLEU보다 사람 평가와 상관관계 높음.",
        },
    }

    if not bert_result.get("skipped"):
        quality["bertscore"] = {
            "avg_f1": round(bert_result["avg_f1"], 4),
            "avg_f1_pct": round(bert_result["avg_f1"] * 100, 2),
            "avg_precision": round(bert_result["avg_precision"], 4),
            "avg_recall": round(bert_result["avg_recall"], 4),
            "per_sample_f1": [round(f, 4) for f in bert_result["per_sample_f1"]],
            "note": "의미 기반 유사도. 동의어에 가장 강함. 사람 평가와 상관관계 최고.",
        }
    else:
        quality["bertscore"] = bert_result

    result = {
        "model": ModelConfig.NMT_MODEL,
        "device": ModelConfig.NMT_DEVICE,
        "quality": quality,
        "speed": {
            "throughput_per_sec": round(throughput, 2),
            **{k: round(v, 1) for k, v in speed_result.items()},
        },
        "num_samples": len(samples),
    }

    bert_f1_str = (
        f"BERTScore F1={quality['bertscore'].get('avg_f1_pct', 'N/A'):.1f}%"
        if not bert_result.get("skipped") else "BERTScore=스킵"
    )
    print(f"\n[NMT] 결과: "
          f"BLEU={quality['bleu']['avg_pct']:.1f}% | "
          f"METEOR={quality['meteor']['avg_pct']:.1f}% | "
          f"{bert_f1_str} | "
          f"처리량={throughput:.1f}문장/초 | 평균지연={speed_result.get('avg_ms', 0):.1f}ms")
    return result
