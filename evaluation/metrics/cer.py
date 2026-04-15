"""
CER (Character Error Rate) 계산
OCR 품질 평가 지표
"""


def compute_cer(reference: str, hypothesis: str) -> float:
    """
    CER 계산 (문자 단위 편집 거리)

    CER = 편집거리 / 정답 문자 수
    낮을수록 좋음
    """
    ref = reference.strip()
    hyp = hypothesis.strip()

    if len(ref) == 0:
        return 0.0 if len(hyp) == 0 else 1.0

    r, h = len(ref), len(hyp)
    dp = [[0] * (h + 1) for _ in range(r + 1)]

    for i in range(r + 1):
        dp[i][0] = i
    for j in range(h + 1):
        dp[0][j] = j

    for i in range(1, r + 1):
        for j in range(1, h + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    return dp[r][h] / r


def compute_avg_cer(pairs: list[tuple[str, str]]) -> dict:
    """
    여러 쌍의 평균 CER 계산

    Args:
        pairs: [(reference, hypothesis), ...]

    Returns:
        {"avg_cer": float, "per_sample": [float, ...]}
    """
    cers = [compute_cer(ref, hyp) for ref, hyp in pairs]
    return {
        "avg_cer": sum(cers) / len(cers) if cers else 0.0,
        "per_sample": cers,
    }
