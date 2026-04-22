"""
BLEU / METEOR / BERTScore / COMET-22 계산
NMT 품질 평가 지표

- BLEU: 단어 n-gram 일치율 (표준 베이스라인)
- METEOR: 동의어·어간 고려한 일치율
- BERTScore: 의미 기반 유사도
- XCOMET-XL: 소스 문장까지 참조, 사람 평가와 상관관계 가장 높음
"""
import math
from collections import Counter


# ──────────────────────────────────────────────
# BLEU
# ──────────────────────────────────────────────
def _ngrams(tokens: list[str], n: int) -> Counter:
    return Counter(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def compute_bleu(reference: str, hypothesis: str, max_n: int = 4) -> float:
    """
    BLEU-4 계산 (단일 문장)

    Returns:
        BLEU score (0.0 ~ 1.0), 높을수록 좋음
    """
    ref_tokens = reference.strip().lower().split()
    hyp_tokens = hypothesis.strip().lower().split()

    if not hyp_tokens:
        return 0.0

    bp = math.exp(min(0, 1 - len(ref_tokens) / len(hyp_tokens)))

    precisions = []
    for n in range(1, max_n + 1):
        ref_ng = _ngrams(ref_tokens, n)
        hyp_ng = _ngrams(hyp_tokens, n)

        clipped = sum(min(count, ref_ng[ng]) for ng, count in hyp_ng.items())
        total = max(len(hyp_tokens) - n + 1, 0)

        if total == 0:
            precisions.append(0.0)
        else:
            precisions.append(clipped / total)

    if any(p == 0 for p in precisions):
        return 0.0

    log_avg = sum(math.log(p) for p in precisions) / max_n
    return bp * math.exp(log_avg)


def compute_avg_bleu(pairs: list[tuple[str, str]]) -> dict:
    """
    Args:
        pairs: [(reference, hypothesis), ...]
    Returns:
        {"avg_bleu": float, "per_sample": [float, ...]}
    """
    scores = [compute_bleu(ref, hyp) for ref, hyp in pairs]
    return {
        "avg_bleu": sum(scores) / len(scores) if scores else 0.0,
        "per_sample": scores,
    }


# ──────────────────────────────────────────────
# METEOR
# ──────────────────────────────────────────────
def compute_meteor(reference: str, hypothesis: str) -> float:
    """
    METEOR 계산 (nltk 사용, 동의어·어간 고려)

    nltk 미설치 시 단순 어간 매칭으로 폴백

    Returns:
        METEOR score (0.0 ~ 1.0), 높을수록 좋음
    """
    try:
        from nltk.translate.meteor_score import single_meteor_score
        import nltk

        # wordnet 데이터 없으면 다운로드
        try:
            nltk.data.find("corpora/wordnet")
        except LookupError:
            nltk.download("wordnet", quiet=True)
            nltk.download("omw-1.4", quiet=True)

        ref_tokens = reference.strip().lower().split()
        hyp_tokens = hypothesis.strip().lower().split()
        return float(single_meteor_score(ref_tokens, hyp_tokens))

    except ImportError:
        # nltk 없으면 단순 unigram F1으로 폴백
        return _simple_unigram_f1(reference, hypothesis)


def _simple_unigram_f1(reference: str, hypothesis: str) -> float:
    """nltk 없을 때 단순 unigram F1 폴백"""
    ref_tokens = set(reference.strip().lower().split())
    hyp_tokens = set(hypothesis.strip().lower().split())

    if not ref_tokens or not hyp_tokens:
        return 0.0

    common = ref_tokens & hyp_tokens
    precision = len(common) / len(hyp_tokens)
    recall = len(common) / len(ref_tokens)

    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def compute_avg_meteor(pairs: list[tuple[str, str]]) -> dict:
    """
    Args:
        pairs: [(reference, hypothesis), ...]
    Returns:
        {"avg_meteor": float, "per_sample": [float, ...]}
    """
    scores = [compute_meteor(ref, hyp) for ref, hyp in pairs]
    return {
        "avg_meteor": sum(scores) / len(scores) if scores else 0.0,
        "per_sample": scores,
    }


# ──────────────────────────────────────────────
# BERTScore
# ──────────────────────────────────────────────
def compute_bertscore(references: list[str], hypotheses: list[str]) -> dict:
    """
    BERTScore 계산 (bert-score 라이브러리 사용)
    의미 기반 유사도 — 동의어에 강함

    Returns:
        {"avg_f1": float, "avg_precision": float, "avg_recall": float,
         "per_sample_f1": [float, ...]}
    """
    try:
        from bert_score import score as bert_score

        P, R, F1 = bert_score(
            hypotheses,
            references,
            lang="en",
            verbose=False,
        )

        f1_list = F1.tolist()
        p_list = P.tolist()
        r_list = R.tolist()

        return {
            "avg_f1": sum(f1_list) / len(f1_list),
            "avg_precision": sum(p_list) / len(p_list),
            "avg_recall": sum(r_list) / len(r_list),
            "per_sample_f1": f1_list,
        }

    except ImportError:
        print("[BERTScore] bert-score 미설치: pip install bert-score")
        return {"skipped": True, "reason": "bert-score not installed"}
    except Exception as e:
        print(f"[BERTScore] 오류: {e}")
        return {"skipped": True, "reason": str(e)}


# ──────────────────────────────────────────────
# COMET-22
# ──────────────────────────────────────────────
def compute_comet(sources: list[str], hypotheses: list[str], references: list[str], gpus: int = 0) -> dict:
    """
    COMET-22 계산 (unbabel-comet 사용)
    소스 문장까지 참조 — 사람 평가와 상관관계 가장 높음

    Returns:
        {"avg_score": float, "per_sample": [float, ...]}
    """
    try:
        from huggingface_hub import snapshot_download
        from comet import load_from_checkpoint

        print("[XCOMET-XL] 모델 로드 중...")
        model_path = snapshot_download(repo_id="Unbabel/XCOMET-XL")
        ckpt_path = f"{model_path}/checkpoints/model.ckpt"
        model = load_from_checkpoint(ckpt_path)

        data = [
            {"src": src, "mt": mt, "ref": ref}
            for src, mt, ref in zip(sources, hypotheses, references)
        ]
        output = model.predict(data, batch_size=8, gpus=gpus)
        scores = output.scores

        return {
            "avg_score": round(sum(scores) / len(scores), 4),
            "per_sample": [round(s, 4) for s in scores],
        }

    except ImportError:
        print("[XCOMET-XL] unbabel-comet 미설치: pip install unbabel-comet")
        return {"skipped": True, "reason": "unbabel-comet not installed"}
    except Exception as e:
        print(f"[XCOMET-XL] 오류: {e}")
        return {"skipped": True, "reason": str(e)}
