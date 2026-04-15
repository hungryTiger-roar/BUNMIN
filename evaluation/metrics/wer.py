"""
WER (Word Error Rate) 계산
ASR 품질 평가 지표
"""


def compute_wer(reference: str, hypothesis: str) -> float:
    """
    WER 계산 (편집 거리 기반)

    WER = (S + D + I) / N
      S: 대체 수, D: 삭제 수, I: 삽입 수, N: 정답 단어 수

    Returns:
        WER (0.0 ~ 1.0+), 낮을수록 좋음
    """
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()

    if len(ref_words) == 0:
        return 0.0 if len(hyp_words) == 0 else 1.0

    r, h = len(ref_words), len(hyp_words)
    dp = [[0] * (h + 1) for _ in range(r + 1)]

    for i in range(r + 1):
        dp[i][0] = i
    for j in range(h + 1):
        dp[0][j] = j

    for i in range(1, r + 1):
        for j in range(1, h + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    return dp[r][h] / r


def compute_avg_wer(pairs: list[tuple[str, str]]) -> dict:
    """
    여러 쌍의 평균 WER 계산

    Args:
        pairs: [(reference, hypothesis), ...]

    Returns:
        {"avg_wer": float, "per_sample": [float, ...]}
    """
    wers = [compute_wer(ref, hyp) for ref, hyp in pairs]
    return {
        "avg_wer": sum(wers) / len(wers) if wers else 0.0,
        "per_sample": wers,
    }
