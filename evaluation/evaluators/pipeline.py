import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

"""
파이프라인 평가
- eval_realtime_pipeline: ASR → NMT (실시간 강의 통역, TTS는 클라이언트 WASM 처리)
- eval_ocr_nmt: OCR → NMT (슬라이드 번역)
"""
import json
from datetime import datetime
from pathlib import Path

from evaluation.metrics.wer import compute_avg_wer
from evaluation.metrics.bleu import compute_avg_bleu, compute_avg_meteor, compute_bertscore
from evaluation.metrics.cer import compute_avg_cer
from evaluation.metrics.speed import timer, compute_rtf, compute_throughput, summarize_latencies

DATASETS_DIR = Path(__file__).parent.parent / "datasets"


def eval_realtime_pipeline() -> dict:
    print("\n[PIPELINE] 실시간 강의 파이프라인 평가 (ASR → NMT)...")

    from app.config import ModelConfig
    from app.services.asr_service import ASRService
    from app.services.nmt_service import NMTService

    samples_dir = DATASETS_DIR / "asr_samples"
    ground_truth_path = samples_dir / "ground_truth.json"

    with open(ground_truth_path, encoding="utf-8") as f:
        samples = json.load(f)

    wav_samples = [s for s in samples if (samples_dir / s["file"]).exists()]

    if not wav_samples:
        return {"skipped": True, "reason": "no_audio_files"}

    asr_service = ASRService(model_name=ModelConfig.ASR_MODEL, device=ModelConfig.ASR_DEVICE, dtype=ModelConfig.ASR_DTYPE)
    nmt_service = NMTService(model_name=ModelConfig.NMT_ASR_MODEL, device=ModelConfig.NMT_ASR_DEVICE, dtype=ModelConfig.NMT_ASR_DTYPE)

    # 출력 디렉토리 생성
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(__file__).parent.parent / "results" / "pipeline_outputs" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  [출력] 결과 저장 경로: {output_dir}")

    wer_pairs = []
    asr_latencies_ms = []
    nmt_latencies_ms = []
    pipeline_latencies_ms = []
    ref_translations = []
    hyp_translations = []

    # 1단계: ASR 전체 순차 실행
    korean_texts = []
    for sample in wav_samples:
        audio_bytes = (samples_dir / sample["file"]).read_bytes()
        with timer() as t_asr:
            korean_text = asr_service.transcribe(audio_bytes, language="ko")
        asr_latencies_ms.append(t_asr["elapsed"] * 1000)
        korean_texts.append(korean_text)
        wer_pairs.append((sample["text"], korean_text))
        print(f"  [ASR {sample['file']}] {t_asr['elapsed']*1000:.0f}ms → {korean_text[:40]}")

    # 2단계: NMT 개별 번역 (발화당 실제 지연시간 측정)
    print(f"\n  [NMT] 개별 번역 중 ({len(korean_texts)}개)...")
    english_texts = []
    for i, text in enumerate(korean_texts):
        valid_text = text if text.strip() else " "
        with timer() as t_nmt:
            result = nmt_service.translate_batch([valid_text])
        nmt_latencies_ms.append(t_nmt["elapsed"] * 1000)
        english_texts.append(result[0])
        print(f"  [NMT {i+1}/{len(korean_texts)}] {t_nmt['elapsed']*1000:.0f}ms → {result[0][:40]}")

    gt_texts = [s["text"] for s in wav_samples]
    ref_translations = nmt_service.translate_batch(gt_texts)
    hyp_translations = english_texts

    pipeline_latencies_ms = [a + n for a, n in zip(asr_latencies_ms, nmt_latencies_ms)]

    # 텍스트 결과 누적 및 출력
    text_results = []
    for i, (sample, english_text) in enumerate(zip(wav_samples, english_texts)):
        pipeline_ms = pipeline_latencies_ms[i]
        text_results.append({
            "file": sample["file"],
            "gt_ko": sample["text"],
            "asr_ko": korean_texts[i],
            "nmt_en": english_text,
            "asr_ms": round(asr_latencies_ms[i], 1),
            "nmt_ms": round(nmt_latencies_ms[i], 1),
            "pipeline_ms": round(pipeline_ms, 1),
        })
        print(f"  [{sample['file']}] ASR={asr_latencies_ms[i]:.0f}ms | NMT={nmt_latencies_ms[i]:.0f}ms | 합계={pipeline_ms:.0f}ms")
        print(f"    NMT: {english_text[:60]}")

    # 텍스트 결과 JSON 저장
    text_output_path = output_dir / "transcriptions.json"
    with open(text_output_path, "w", encoding="utf-8") as f:
        json.dump(text_results, f, ensure_ascii=False, indent=2)
    print(f"\n  [출력] 텍스트 결과 저장: {text_output_path}")

    wer_result = compute_avg_wer(wer_pairs)
    bleu_result = compute_avg_bleu(list(zip(ref_translations, hyp_translations)))

    print("\n  [BERTScore] 파이프라인 번역 품질 계산 중...")
    bert_result = compute_bertscore(ref_translations, hyp_translations)

    asr_speed  = summarize_latencies(asr_latencies_ms)
    nmt_speed  = summarize_latencies(nmt_latencies_ms)
    pipe_speed = summarize_latencies(pipeline_latencies_ms)
    avg_asr_rtf = sum(
        compute_rtf(ms / 1000, s["duration_sec"])
        for ms, s in zip(asr_latencies_ms, wav_samples)
    ) / len(wav_samples)

    result = {
        "models": {
            "asr": ModelConfig.ASR_MODEL,
            "nmt_asr": ModelConfig.NMT_ASR_MODEL,
        },
        "quality": {
            "asr_wer": round(wer_result["avg_wer"], 4),
            "nmt_bleu": round(bleu_result["avg_bleu"] * 100, 2),
            "nmt_bertscore_f1": round(bert_result.get("avg_f1", 0) * 100, 2) if not bert_result.get("skipped") else None,
            "note": "NMT 품질: ASR 인식 텍스트 번역 vs 정답 텍스트 번역 비교",
        },
        "speed": {
            "asr_avg_ms": round(asr_speed.get("avg_ms", 0), 1),
            "asr_avg_rtf": round(avg_asr_rtf, 4),
            "nmt_avg_ms": round(nmt_speed.get("avg_ms", 0), 1),
            "pipeline_avg_ms": round(pipe_speed.get("avg_ms", 0), 1),
            "pipeline_p95_ms": round(pipe_speed.get("p95_ms", 0), 1),
        },
        "num_samples": len(wav_samples),
    }

    bert_str = f"{result['quality']['nmt_bertscore_f1']:.1f}%" if result['quality']['nmt_bertscore_f1'] else "스킵"
    print(f"\n[PIPELINE] 결과:")
    print(f"  ASR  WER={wer_result['avg_wer']:.1%} | RTF={avg_asr_rtf:.3f} | {asr_speed.get('avg_ms',0):.0f}ms")
    print(f"  NMT  BLEU={bleu_result['avg_bleu']*100:.1f}% | BERTScore={bert_str} | {nmt_speed.get('avg_ms',0):.0f}ms")
    print(f"  전체 파이프라인 평균={pipe_speed.get('avg_ms',0):.0f}ms | P95={pipe_speed.get('p95_ms',0):.0f}ms")
    return result


def eval_ocr_nmt() -> dict:
    print("\n[OCR+NMT] 슬라이드 번역 파이프라인 평가 시작...")

    from app.config import ModelConfig
    from app.services.ocr_service import OCRService
    from app.services.nmt_service import NMTService

    ocr_dir = DATASETS_DIR / "ocr_samples"
    ground_truth_path = ocr_dir / "ground_truth.json"

    if not ground_truth_path.exists():
        return {"skipped": True, "reason": "no_ocr_samples"}

    with open(ground_truth_path, encoding="utf-8") as f:
        samples = json.load(f)

    image_samples = [s for s in samples if (ocr_dir / s["file"]).exists()]

    if not image_samples:
        return {"skipped": True, "reason": "no_image_files"}

    ocr_service = OCRService()
    nmt_service = NMTService(model_name=ModelConfig.NMT_ASR_MODEL, device=ModelConfig.NMT_ASR_DEVICE, dtype=ModelConfig.NMT_ASR_DTYPE)

    cer_pairs = []
    ocr_latencies_ms = []
    ocr_texts = []

    # Step 1: OCR 순차 실행
    for sample in image_samples:
        img_bytes = (ocr_dir / sample["file"]).read_bytes()

        with timer() as t_ocr:
            texts = ocr_service.extract_texts(img_bytes)
        ocr_ms = t_ocr["elapsed"] * 1000
        ocr_latencies_ms.append(ocr_ms)

        ocr_text = " ".join(texts).strip()
        ocr_texts.append(ocr_text)
        cer_pairs.append((sample["text"], ocr_text))

        print(f"  [OCR {sample['file']}] {ocr_ms:.0f}ms | extracted: {ocr_text[:40] or '(none)'}")

    # Step 2: NMT 개별 번역 (슬라이드당 실제 지연시간 측정)
    print(f"  [NMT] 개별 번역 중 ({len(ocr_texts)}개)...")
    hyp_translations = []
    nmt_latencies_ms = []
    for i, text in enumerate(ocr_texts):
        valid_text = text if text.strip() else " "
        with timer() as t_nmt:
            result = nmt_service.translate_batch([valid_text])
        nmt_latencies_ms.append(t_nmt["elapsed"] * 1000)
        hyp_translations.append(result[0])

    gt_texts = [s["text"] if s["text"].strip() else " " for s in image_samples]
    ref_translations = nmt_service.translate_batch(gt_texts)

    pipeline_latencies_ms = [ocr_ms + nmt_ms for ocr_ms, nmt_ms in zip(ocr_latencies_ms, nmt_latencies_ms)]

    for i, (sample, ocr_text, translated) in enumerate(zip(image_samples, ocr_texts, hyp_translations)):
        print(f"  [{sample['file']}] OCR={ocr_latencies_ms[i]:.0f}ms | NMT={nmt_latencies_ms[i]:.0f}ms")
        print(f"    translated: {translated[:60] or '(none)'}")

    cer_result = compute_avg_cer(cer_pairs)
    translation_pairs = list(zip(ref_translations, hyp_translations))
    bleu_result = compute_avg_bleu(translation_pairs)
    meteor_result = compute_avg_meteor(translation_pairs)

    print("\n  [BERTScore] 파이프라인 번역 품질 계산 중...")
    bert_result = compute_bertscore(ref_translations, hyp_translations)

    ocr_speed      = summarize_latencies(ocr_latencies_ms)
    nmt_speed      = summarize_latencies(nmt_latencies_ms)
    pipeline_speed = summarize_latencies(pipeline_latencies_ms)
    throughput     = compute_throughput(sum(pipeline_latencies_ms) / 1000, len(image_samples))

    result = {
        "ocr_model": ocr_service.mode,
        "nmt_model": ModelConfig.NMT_ASR_MODEL,
        "quality": {
            "ocr_cer": round(cer_result["avg_cer"], 4),
            "pipeline_bleu": round(bleu_result["avg_bleu"] * 100, 2),
            "pipeline_meteor": round(meteor_result["avg_meteor"] * 100, 2),
            "pipeline_bertscore_f1": round(bert_result.get("avg_f1", 0) * 100, 2) if not bert_result.get("skipped") else None,
            "note": "번역 품질은 정답 한국어 기반 번역 vs OCR 추출 기반 번역 비교",
        },
        "speed": {
            "ocr_avg_ms": round(ocr_speed.get("avg_ms", 0), 1),
            "nmt_avg_ms": round(nmt_speed.get("avg_ms", 0), 1),
            "pipeline_avg_ms": round(pipeline_speed.get("avg_ms", 0), 1),
            "throughput_per_sec": round(throughput, 2),
        },
        "num_samples": len(image_samples),
    }

    bert_str = f"{result['quality']['pipeline_bertscore_f1']:.1f}%" if result['quality']['pipeline_bertscore_f1'] else "스킵"
    print(f"\n[OCR+NMT] 결과: "
          f"OCR CER={cer_result['avg_cer']:.1%} | "
          f"BLEU={result['quality']['pipeline_bleu']:.1f}% | "
          f"METEOR={result['quality']['pipeline_meteor']:.1f}% | "
          f"BERTScore={bert_str} | "
          f"파이프라인 평균={pipeline_speed.get('avg_ms', 0):.1f}ms")
    return result
