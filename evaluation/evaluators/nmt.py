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

from evaluation.metrics.bleu import compute_avg_bleu, compute_avg_meteor, compute_bertscore, compute_comet
from evaluation.metrics.speed import timer, compute_throughput, summarize_latencies

DATASETS_DIR = Path(__file__).parent.parent / "datasets"


def eval_nmt(use_xcomet: bool = False) -> dict:
    print("\n[NMT] 평가 시작...")

    from app.config import ModelConfig
    from app.services.nmt_service import NMTService

    pairs_path = DATASETS_DIR / "nmt_samples" / "ko_en_pairs.json"
    with open(pairs_path, encoding="utf-8") as f:
        samples = json.load(f)

    service = NMTService(model_name=ModelConfig.NMT_ASR_MODEL, device=ModelConfig.NMT_ASR_DEVICE, dtype=ModelConfig.NMT_ASR_DTYPE)

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

    if use_xcomet:
        print("\n  [XCOMET-XL] 계산 중 (처음 실행 시 모델 다운로드)...")
        gpus = 1 if ModelConfig.NMT_ASR_DEVICE == "cuda" else 0
        comet_result = compute_comet(ko_texts, hypotheses, references, gpus=gpus)
    else:
        print("\n  [XCOMET-XL] 스킵 (--xcomet 플래그로 활성화 가능)")
        comet_result = {"skipped": True, "reason": "use --xcomet flag to enable"}

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
            "note": "의미 기반 유사도. 동의어에 강함.",
        }
    else:
        quality["bertscore"] = bert_result

    if not comet_result.get("skipped"):
        quality["comet22"] = {
            "avg_score": comet_result["avg_score"],
            "avg_score_pct": round(comet_result["avg_score"] * 100, 2),
            "per_sample": comet_result["per_sample"],
            "note": "소스 문장까지 참조. 에러 스팬 감지. 사람 평가와 상관관계 가장 높음.",
        }
    else:
        quality["comet22"] = comet_result

    result = {
        "model": ModelConfig.NMT_ASR_MODEL,
        "device": ModelConfig.NMT_ASR_DEVICE,
        "quality": quality,
        "speed": {
            "throughput_per_sec": round(throughput, 2),
            **{k: round(v, 1) for k, v in speed_result.items()},
        },
        "num_samples": len(samples),
    }

    # 속도 기준 모델 자동 전환: avg_ms > 1000ms 이면 1.3B로 교체
    if speed_result.get("avg_ms", 0) > 1000:
        env_path = Path(__file__).parent.parent.parent / ".env"
        lines = env_path.read_text(encoding="utf-8").splitlines()
        new_lines = [
            f"NMT_ASR_MODEL=facebook/nllb-200-distilled-1.3B" if l.startswith("NMT_ASR_MODEL=") else l
            for l in lines
        ]
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"\n[NMT] 평균 지연 {speed_result['avg_ms']:.0f}ms > 1000ms → .env NMT_ASR_MODEL을 facebook/nllb-200-distilled-1.3B 로 자동 전환했습니다.")

    bert_f1_str = (
        f"BERTScore F1={quality['bertscore'].get('avg_f1_pct', 'N/A'):.1f}%"
        if not bert_result.get("skipped") else "BERTScore=스킵"
    )
    comet_str = (
        f"XCOMET-XL={quality['comet22'].get('avg_score_pct', 'N/A'):.1f}%"
        if not comet_result.get("skipped") else "XCOMET-XL=스킵"
    )
    print(f"\n[NMT] 결과: "
          f"BLEU={quality['bleu']['avg_pct']:.1f}% | "
          f"METEOR={quality['meteor']['avg_pct']:.1f}% | "
          f"{bert_f1_str} | "
          f"{comet_str} | "
          f"처리량={throughput:.1f}문장/초 | 평균지연={speed_result.get('avg_ms', 0):.1f}ms")
    return result
