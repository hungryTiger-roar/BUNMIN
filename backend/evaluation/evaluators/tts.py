"""
TTS (Text-to-Speech) 평가
속도 중심: RTF, 지연시간
품질: MOS는 주관적 평가 필요
"""
import io
import wave
import json
from pathlib import Path

from evaluation.metrics.speed import timer, compute_rtf, summarize_latencies

DATASETS_DIR = Path(__file__).parent.parent / "datasets"


def eval_tts() -> dict:
    print("\n[TTS] 평가 시작...")

    from app.config import ModelConfig
    from app.services.tts_service import TTSService

    texts_path = DATASETS_DIR / "tts_samples" / "texts.json"
    with open(texts_path, encoding="utf-8") as f:
        texts = json.load(f)

    service = TTSService(model_dir=str(ModelConfig.TTS_MODEL_DIR))

    latencies_ms = []
    rtf_list = []

    for text in texts:
        estimated_duration = len(text.split()) / 2.5

        with timer() as t:
            audio_bytes = service.synthesize(text)

        elapsed_ms = t["elapsed"] * 1000
        latencies_ms.append(elapsed_ms)

        try:
            with wave.open(io.BytesIO(audio_bytes)) as wf:
                actual_duration = wf.getnframes() / wf.getframerate()
        except Exception:
            actual_duration = estimated_duration

        rtf = compute_rtf(t["elapsed"], actual_duration)
        rtf_list.append(rtf)

        print(f"  [{elapsed_ms:.1f}ms | RTF={rtf:.3f}] {text[:40]}...")

    speed_result = summarize_latencies(latencies_ms)
    avg_rtf = sum(rtf_list) / len(rtf_list)

    result = {
        "model": "piper-tts",
        "quality": {
            "note": "TTS 품질은 MOS(Mean Opinion Score)로 측정 (주관적 청취 평가 필요)"
        },
        "speed": {
            "avg_rtf": round(avg_rtf, 4),
            "realtime_capable": avg_rtf < 1.0,
            **{k: round(v, 1) for k, v in speed_result.items()},
        },
        "num_samples": len(texts),
    }

    print(f"\n[TTS] 결과: 평균RTF={avg_rtf:.3f} | "
          f"실시간가능={'[OK]' if avg_rtf < 1.0 else '[NO]'} | "
          f"평균지연={speed_result.get('avg_ms', 0):.1f}ms")
    return result
