"""
속도 지표 계산
RTF, 지연시간, 처리량
"""
import time
from contextlib import contextmanager


@contextmanager
def timer():
    """경과 시간 측정 컨텍스트 매니저"""
    state = {"elapsed": 0.0}
    start = time.perf_counter()
    try:
        yield state
    finally:
        state["elapsed"] = time.perf_counter() - start


def compute_rtf(processing_time_sec: float, audio_duration_sec: float) -> float:
    """
    RTF (Real-Time Factor) 계산

    RTF = 처리시간 / 오디오길이
    RTF < 1.0 이면 실시간 처리 가능
    """
    if audio_duration_sec <= 0:
        return float("inf")
    return processing_time_sec / audio_duration_sec


def compute_throughput(total_time_sec: float, num_samples: int) -> float:
    """처리량 계산 (샘플/초)"""
    if total_time_sec <= 0:
        return 0.0
    return num_samples / total_time_sec


def summarize_latencies(latencies_ms: list[float]) -> dict:
    """지연시간 통계 요약"""
    if not latencies_ms:
        return {}

    sorted_lat = sorted(latencies_ms)
    n = len(sorted_lat)

    return {
        "avg_ms": sum(latencies_ms) / n,
        "min_ms": sorted_lat[0],
        "max_ms": sorted_lat[-1],
        "p50_ms": sorted_lat[int(n * 0.50)],
        "p95_ms": sorted_lat[int(n * 0.95)],
    }
