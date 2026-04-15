"""
ASR (Automatic Speech Recognition) 평가
품질: WER (Word Error Rate)
속도: RTF, 지연시간
"""
import json
from pathlib import Path

from evaluation.metrics.wer import compute_avg_wer
from evaluation.metrics.speed import timer, compute_rtf, summarize_latencies

DATASETS_DIR = Path(__file__).parent.parent / "datasets"


def eval_asr() -> dict:
    print("\n[ASR] 평가 시작...")

    from app.config import ModelConfig
    from app.services.asr_service import ASRService

    ground_truth_path = DATASETS_DIR / "asr_samples" / "ground_truth.json"
    samples_dir = DATASETS_DIR / "asr_samples"

    with open(ground_truth_path, encoding="utf-8") as f:
        samples = json.load(f)

    wav_samples = [s for s in samples if (samples_dir / s["file"]).exists()]

    if not wav_samples:
        print("[ASR] 음성 샘플 파일 없음. datasets/asr_samples/ 에 WAV 파일을 추가하세요.")
        print("[ASR] ground_truth.json 의 file 필드와 파일명이 일치해야 합니다.")
        return {"skipped": True, "reason": "no_audio_files"}

    service = ASRService(model_name=ModelConfig.ASR_MODEL, device=ModelConfig.ASR_DEVICE)

    wer_pairs = []
    latencies_ms = []
    rtf_list = []

    for sample in wav_samples:
        audio_path = samples_dir / sample["file"]
        audio_bytes = audio_path.read_bytes()
        duration = sample["duration_sec"]

        with timer() as t:
            hypothesis = service.transcribe(audio_bytes, language="ko")

        elapsed_ms = t["elapsed"] * 1000
        latencies_ms.append(elapsed_ms)
        rtf_list.append(compute_rtf(t["elapsed"], duration))
        wer_pairs.append((sample["text"], hypothesis))

        print(f"  [{sample['file']}] {elapsed_ms:.1f}ms | RTF={rtf_list[-1]:.3f}")
        print(f"    정답: {sample['text']}")
        print(f"    인식: {hypothesis}")

    wer_result = compute_avg_wer(wer_pairs)
    speed_result = summarize_latencies(latencies_ms)
    avg_rtf = sum(rtf_list) / len(rtf_list)

    result = {
        "model": ModelConfig.ASR_MODEL,
        "device": ModelConfig.ASR_DEVICE,
        "quality": {
            "avg_wer": round(wer_result["avg_wer"], 4),
            "per_sample_wer": [round(w, 4) for w in wer_result["per_sample"]],
        },
        "speed": {
            "avg_rtf": round(avg_rtf, 4),
            "realtime_capable": avg_rtf < 1.0,
            **{k: round(v, 1) for k, v in speed_result.items()},
        },
        "num_samples": len(wav_samples),
    }

    print(f"\n[ASR] 결과: WER={result['quality']['avg_wer']:.1%} | "
          f"평균RTF={avg_rtf:.3f} | 평균지연={speed_result.get('avg_ms', 0):.1f}ms")
    return result
