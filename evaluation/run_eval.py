"""
AI 모델 통합 평가 스크립트
품질(WER, BLEU, CER) + 속도(RTF, 지연시간, 처리량) 측정

사용법:
    python evaluation/run_eval.py               # 기본 평가 (asr, nmt, tts, pipeline, ocr_nmt)
    python evaluation/run_eval.py --model asr   # 특정 모델만
    python evaluation/run_eval.py --all         # OCR 포함 전체 평가
    python evaluation/run_eval.py --compare     # 이전 결과와 비교
"""
import sys
import os
import json
import argparse
import importlib

# conda aunion 환경 검사 — 잘못된 Python으로 실행 시 자동 재실행
_AUNION_PYTHON = r"C:\Users\SSAFY\miniforge3\envs\aunion\python.exe"
if os.path.isfile(_AUNION_PYTHON) and _AUNION_PYTHON.lower() not in sys.executable.lower():
    import subprocess
    # -E: PYTHON* 환경변수 무시, -s: user site-packages 제외 → Windows Store Python 격리
    clean_env = {k: v for k, v in os.environ.items()
                 if not k.startswith("PYTHON")}
    result = subprocess.run([_AUNION_PYTHON, "-s"] + sys.argv, env=clean_env)
    sys.exit(result.returncode)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND_DIR))

from evaluation.evaluators import eval_asr, eval_nmt, eval_tts, eval_ocr, eval_realtime_pipeline, eval_ocr_nmt

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
(RESULTS_DIR / "history").mkdir(exist_ok=True)


# ──────────────────────────────────────────────
# 결과 비교
# ──────────────────────────────────────────────
def compare_results():
    result_files = sorted((RESULTS_DIR / "history").glob("eval_*.json"))
    if len(result_files) < 2:
        print("비교할 결과가 2개 이상 필요합니다.")
        return

    prev_path, curr_path = result_files[-2], result_files[-1]
    with open(prev_path, encoding="utf-8") as f:
        prev = json.load(f)
    with open(curr_path, encoding="utf-8") as f:
        curr = json.load(f)

    print(f"\n{'='*60}")
    print(f"이전: {prev_path.name}")
    print(f"현재: {curr_path.name}")
    print(f"{'='*60}")

    def diff(label, prev_val, curr_val, lower_better=True):
        if prev_val is None or curr_val is None:
            return
        delta = curr_val - prev_val
        if lower_better:
            sign = "▼" if delta < 0 else "▲"
            good = delta < 0
        else:
            sign = "▲" if delta > 0 else "▼"
            good = delta > 0
        mark = "[OK]" if good else "[NO]"
        print(f"  {label}: {prev_val:.4f} → {curr_val:.4f} ({sign}{abs(delta):.4f}) {mark}")

    for model in ["asr", "nmt", "tts", "ocr", "pipeline", "ocr_nmt"]:
        p = prev.get("models", {}).get(model, {})
        c = curr.get("models", {}).get(model, {})
        if not p or not c or p.get("skipped") or c.get("skipped"):
            continue

        print(f"\n[{model.upper()}]")
        if model == "asr":
            diff("WER", p["quality"].get("avg_wer"), c["quality"].get("avg_wer"), lower_better=True)
            diff("평균RTF", p["speed"].get("avg_rtf"), c["speed"].get("avg_rtf"), lower_better=True)
            diff("평균지연(ms)", p["speed"].get("avg_ms"), c["speed"].get("avg_ms"), lower_better=True)
        elif model == "nmt":
            diff("BLEU", p["quality"].get("bleu", {}).get("avg"), c["quality"].get("bleu", {}).get("avg"), lower_better=False)
            diff("METEOR", p["quality"].get("meteor", {}).get("avg"), c["quality"].get("meteor", {}).get("avg"), lower_better=False)
            diff("BERTScore F1", p["quality"].get("bertscore", {}).get("avg_f1"), c["quality"].get("bertscore", {}).get("avg_f1"), lower_better=False)
            diff("처리량(문장/초)", p["speed"].get("throughput_per_sec"), c["speed"].get("throughput_per_sec"), lower_better=False)
            diff("평균지연(ms)", p["speed"].get("avg_ms"), c["speed"].get("avg_ms"), lower_better=True)
        elif model == "tts":
            diff("평균RTF", p["speed"].get("avg_rtf"), c["speed"].get("avg_rtf"), lower_better=True)
            diff("평균지연(ms)", p["speed"].get("avg_ms"), c["speed"].get("avg_ms"), lower_better=True)
        elif model == "ocr":
            diff("CER", p["quality"].get("avg_cer"), c["quality"].get("avg_cer"), lower_better=True)
            diff("처리량(이미지/초)", p["speed"].get("throughput_per_sec"), c["speed"].get("throughput_per_sec"), lower_better=False)
            diff("평균지연(ms)", p["speed"].get("avg_ms"), c["speed"].get("avg_ms"), lower_better=True)
        elif model == "pipeline":
            diff("ASR WER", p["quality"].get("asr_wer"), c["quality"].get("asr_wer"), lower_better=True)
            diff("NMT BERTScore F1", p["quality"].get("nmt_bertscore_f1"), c["quality"].get("nmt_bertscore_f1"), lower_better=False)
            diff("TTS RTF", p["quality"].get("tts_avg_rtf"), c["quality"].get("tts_avg_rtf"), lower_better=True)
            diff("파이프라인 평균(ms)", p["speed"].get("pipeline_avg_ms"), c["speed"].get("pipeline_avg_ms"), lower_better=True)
        elif model == "ocr_nmt":
            diff("OCR CER", p["quality"].get("ocr_cer"), c["quality"].get("ocr_cer"), lower_better=True)
            diff("파이프라인 BLEU", p["quality"].get("pipeline_bleu"), c["quality"].get("pipeline_bleu"), lower_better=False)
            diff("파이프라인 BERTScore", p["quality"].get("pipeline_bertscore_f1"), c["quality"].get("pipeline_bertscore_f1"), lower_better=False)
            diff("파이프라인 지연(ms)", p["speed"].get("pipeline_avg_ms"), c["speed"].get("pipeline_avg_ms"), lower_better=True)


# ──────────────────────────────────────────────
# 비전공자 친화적 결과 해설
# ──────────────────────────────────────────────
def _grade(value, good_thresh, ok_thresh, lower_better=True):
    if lower_better:
        if value <= good_thresh:   return "[우수]"
        elif value <= ok_thresh:   return "[보통]"
        else:                      return "[개선필요]"
    else:
        if value >= good_thresh:   return "[우수]"
        elif value >= ok_thresh:   return "[보통]"
        else:                      return "[개선필요]"


def print_friendly_summary(model: str, result: dict):
    if result.get("skipped") or result.get("error"):
        return

    q = result.get("quality", {})
    s = result.get("speed", {})

    print("")
    print("=" * 60)
    print("  [알기 쉬운 결과 해설]")
    print("=" * 60)

    if model == "asr":
        wer = q.get("avg_wer", 1.0)
        acc = (1 - wer) * 100
        rtf = s.get("avg_rtf", 9.9)
        avg_ms = s.get("avg_ms", 0)
        grade = _grade(wer, 0.10, 0.25, lower_better=True)
        print(f"  [음성 인식 정확도] {grade}")
        print(f"    100단어 중 약 {acc:.0f}단어 정확히 인식  (오류 {wer*100:.1f}%)")
        if wer <= 0.10:
            comment = "매우 정확합니다. 전문 용어도 잘 인식합니다."
        elif wer <= 0.25:
            comment = "강의 내용 파악에 충분한 수준입니다."
        else:
            comment = "오류가 다소 많습니다. 전문 용어나 발음이 부정확할 수 있습니다."
        print(f"    {comment}")
        print(f"")
        print(f"  [처리 속도]")
        print(f"    1초짜리 음성을 약 {avg_ms/1000:.1f}초 만에 처리 (실시간 비율 {rtf:.2f})")
        if rtf < 1.0:
            print(f"    실시간 처리 가능합니다. (재생 시간보다 {1/rtf:.1f}배 빠름)")
        else:
            print(f"    실시간 처리 불가. 지연이 발생할 수 있습니다.")

    elif model == "nmt":
        bleu   = q.get("bleu", {}).get("avg_pct", 0)
        meteor = q.get("meteor", {}).get("avg_pct", 0)
        bert   = q.get("bertscore", {}).get("avg_f1_pct", None)
        avg_ms = s.get("avg_ms", 0)
        grade  = _grade(bert if bert else meteor, 90, 70, lower_better=False)
        print(f"  [번역 품질] {grade}")
        print(f"    BLEU     {bleu:.1f}%  <- 단어 일치율 (동의어 불인정, 낮게 나옴)")
        print(f"    METEOR   {meteor:.1f}%  <- 비슷한 뜻 단어 포함 정확도")
        if bert:
            print(f"    BERTScore {bert:.1f}%  <- AI가 직접 의미 비교 (가장 실제 체감에 가까움)")
            main_score = bert
        else:
            main_score = meteor
        if main_score >= 90:
            comment = "매우 자연스러운 번역입니다."
        elif main_score >= 70:
            comment = "뜻은 전달되나 표현이 어색할 수 있습니다."
        else:
            comment = "번역이 부정확합니다. 모델 개선이 필요합니다."
        print(f"    => {comment}")
        print(f"")
        print(f"  [처리 속도]")
        print(f"    문장 1개를 약 {avg_ms:.0f}ms({avg_ms/1000:.2f}초) 만에 번역")

    elif model == "tts":
        rtf    = s.get("avg_rtf", 9.9)
        avg_ms = s.get("avg_ms", 0)
        rt_ok  = s.get("realtime_capable", False)
        grade  = "[우수]" if rtf < 0.5 else ("[보통]" if rtf < 1.0 else "[개선필요]")
        print(f"  [음성 합성 속도] {grade}")
        if avg_ms > 0:
            print(f"    문장 1개 음성을 평균 {avg_ms:.0f}ms({avg_ms/1000:.1f}초) 만에 생성")
        print(f"    실시간 비율(RTF) {rtf:.3f} => 재생 시간의 {rtf*100:.0f}% 시간에 생성")
        if rt_ok:
            print(f"    실시간 서비스에 적합합니다.")
        else:
            print(f"    실시간 사용 불가. 음성이 늦게 나올 수 있습니다.")
        print(f"    * 음질은 직접 들어봐야 판단 가능합니다.")

    elif model == "ocr":
        cer = q.get("avg_cer", 1.0)
        acc = (1 - cer) * 100
        avg_ms = s.get("avg_ms", 0)
        grade  = _grade(cer, 0.05, 0.20, lower_better=True)
        print(f"  [글자 인식 정확도] {grade}")
        print(f"    100글자 중 약 {acc:.0f}글자 정확히 읽음  (오류 {cer*100:.1f}%)")
        if cer <= 0.05:
            comment = "매우 정확합니다."
        elif cer <= 0.20:
            comment = "대부분 읽을 수 있습니다."
        elif cer <= 0.50:
            comment = "절반 정도 인식합니다. 한국어 지원 개선이 필요합니다."
        else:
            comment = "인식률이 매우 낮습니다. 현재 모델은 한국어를 지원하지 않습니다."
        print(f"    {comment}")
        print(f"")
        print(f"  [처리 속도]")
        print(f"    슬라이드 이미지 1장을 약 {avg_ms:.0f}ms({avg_ms/1000:.1f}초) 만에 처리")

    elif model == "pipeline":
        asr_wer  = q.get("asr_wer", 1.0)
        bert     = q.get("nmt_bertscore_f1")
        tts_rtf  = q.get("tts_avg_rtf", 9.9)
        total_ms = s.get("pipeline_avg_ms", 0)
        p95_ms   = s.get("pipeline_p95_ms", 0)
        asr_ms   = s.get("asr_avg_ms", 0)
        nmt_ms   = s.get("nmt_avg_ms", 0)
        tts_ms   = s.get("tts_avg_ms", 0)
        print(f"  [실시간 파이프라인 전체 성능]")
        print(f"    교수님 말씀 후 영어 음성 출력까지 평균 {total_ms:.0f}ms ({total_ms/1000:.1f}초)")
        print(f"    95%의 경우 최대 {p95_ms:.0f}ms ({p95_ms/1000:.1f}초) 이내")
        if total_ms < 2000:
            delay_comment = "매우 빠릅니다. 거의 즉시 통역됩니다."
        elif total_ms < 4000:
            delay_comment = "동시통역 수준으로 빠릅니다."
        elif total_ms < 8000:
            delay_comment = "약간의 지연이 있지만 사용 가능한 수준입니다."
        else:
            delay_comment = "지연이 큽니다. 실시간 사용에 어려움이 있습니다."
        print(f"    => {delay_comment}")
        print(f"")
        print(f"  [각 단계 처리 시간]")
        print(f"    듣기(ASR)  {asr_ms:.0f}ms  | 음성 -> 한국어 텍스트")
        print(f"    번역(NMT)  {nmt_ms:.0f}ms   | 한국어 -> 영어")
        print(f"    말하기(TTS) {tts_ms:.0f}ms | 영어 텍스트 -> 음성")
        print(f"")
        print(f"  [번역 품질]")
        asr_acc = (1 - asr_wer) * 100
        print(f"    음성 인식 정확도: {asr_acc:.0f}%")
        if bert:
            grade = _grade(bert, 90, 70, lower_better=False)
            print(f"    번역 의미 유사도: {bert:.1f}% {grade}")

    elif model == "ocr_nmt":
        cer      = q.get("ocr_cer", 1.0)
        bleu     = q.get("pipeline_bleu", 0)
        bert     = q.get("pipeline_bertscore_f1")
        total_ms = s.get("pipeline_avg_ms", 0)
        ocr_ms   = s.get("ocr_avg_ms", 0)
        nmt_ms   = s.get("nmt_avg_ms", 0)
        print(f"  [슬라이드 번역 파이프라인 전체 성능]")
        print(f"    슬라이드 1장 번역까지 평균 {total_ms:.0f}ms ({total_ms/1000:.1f}초)")
        print(f"")
        print(f"  [각 단계 결과]")
        print(f"    글자 인식(OCR)  오류율 {cer*100:.1f}%  | 슬라이드 글자 추출")
        print(f"    번역(NMT)       BLEU {bleu:.1f}%       | 추출된 글자 번역")
        if bert:
            print(f"    번역 의미 유사도  BERTScore {bert:.1f}%")
        print(f"")
        if cer > 0.5:
            print(f"  [주의] OCR 인식률이 낮아 번역 품질도 떨어집니다.")
            print(f"         한국어 슬라이드는 한국어 지원 OCR 모델이 필요합니다.")
        else:
            print(f"  OCR 인식이 양호하여 번역도 잘 동작합니다.")

    print("=" * 60)


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
MENU_ITEMS = [
    ("asr",      "ASR      (음성인식)"),
    ("nmt",      "NMT      (번역)"),
    ("tts",      "TTS      (음성합성)"),
    ("ocr",      "OCR      (문자인식)"),
    ("pipeline", "Pipeline (ASR→NMT→TTS 전체)"),
    ("ocr_nmt",  "OCR+NMT  (슬라이드 번역)"),
    ("__all__",  "전체 평가"),
    ("__cmp__",  "이전 결과와 비교"),
]


def select_device() -> str:
    """CPU / GPU 선택 메뉴. 'cpu' 또는 'cuda' 반환."""
    print("=" * 60)
    print("  실행 환경 선택")
    print("=" * 60)
    print("  1. CPU")
    print("  2. GPU")
    print("-" * 60)
    while True:
        raw = input("선택 (1-2): ").strip()
        if raw == "1":
            os.environ["ASR_DEVICE"] = "cpu"
            os.environ["NMT_DEVICE"] = "cpu"
            print("  → CPU 모드")
        elif raw == "2":
            os.environ["ASR_DEVICE"] = "cuda"
            os.environ["NMT_DEVICE"] = "cuda"
            print("  → GPU 모드 (TTS/OCR은 CPU 고정)")
        else:
            print("  1 또는 2를 입력하세요.")
            continue

        if "app.config" in sys.modules:
            importlib.reload(sys.modules["app.config"])
        return "cuda" if raw == "2" else "cpu"


def interactive_menu() -> list[str] | str:
    """번호 선택 메뉴. 선택된 model key 리스트 또는 특수 커맨드 문자열 반환."""
    select_device()

    print("=" * 60)
    print("  AI 모델 평가")
    print("=" * 60)
    for i, (_, label) in enumerate(MENU_ITEMS, 1):
        print(f"  {i}. {label}")
    print("-" * 60)

    while True:
        raw = input("선택 (1-8): ").strip()
        if not raw.isdigit() or not (1 <= int(raw) <= len(MENU_ITEMS)):
            print(f"  1~{len(MENU_ITEMS)} 사이 숫자를 입력하세요.")
            continue
        key, _ = MENU_ITEMS[int(raw) - 1]
        if key == "__all__":
            return ["asr", "nmt", "tts", "ocr", "pipeline", "ocr_nmt"]
        if key == "__cmp__":
            return "__compare__"
        return [key]


def main():
    parser = argparse.ArgumentParser(description="AI 모델 평가")
    parser.add_argument("--model", choices=["asr", "nmt", "tts", "ocr", "pipeline", "ocr_nmt"], help="특정 모델만 평가")
    parser.add_argument("--all", action="store_true", help="모든 모델 평가 (OCR 포함)")
    parser.add_argument("--compare", action="store_true", help="이전 결과와 비교")
    args = parser.parse_args()

    # 인자가 없으면 대화형 메뉴
    no_args = not args.model and not args.all and not args.compare
    if no_args:
        selection = interactive_menu()
        if selection == "__compare__":
            compare_results()
            return
        targets = selection
    elif args.compare:
        compare_results()
        return

    print("=" * 60)
    print("AI 모델 통합 평가")
    print("=" * 60)

    results = {"timestamp": datetime.now().isoformat(), "models": {}}

    eval_map = {
        "asr":      eval_asr,
        "nmt":      eval_nmt,
        "tts":      eval_tts,
        "ocr":      eval_ocr,
        "pipeline": eval_realtime_pipeline,
        "ocr_nmt":  eval_ocr_nmt,
    }

    if no_args:
        pass  # targets already set above
    elif args.model:
        targets = [args.model]
    elif args.all:
        targets = ["asr", "nmt", "tts", "ocr", "pipeline", "ocr_nmt"]
    else:
        targets = ["asr", "nmt", "tts", "pipeline", "ocr_nmt"]

    for model in targets:
        try:
            results["models"][model] = eval_map[model]()
        except Exception as e:
            print(f"[{model.upper()}] 평가 오류: {e}")
            results["models"][model] = {"error": str(e)}

    # 결과 저장: latest.json (항상 최신) + history/ (누적)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_path = RESULTS_DIR / "history" / f"eval_{timestamp}.json"
    latest_path  = RESULTS_DIR / "latest.json"

    for path in [history_path, latest_path]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"평가 완료.")
    print(f"  최신 결과: {latest_path}")
    print(f"  히스토리:  {history_path}")
    print("=" * 60)

    # 최종 요약
    print("\n[최종 요약]")
    for model, result in results["models"].items():
        if result.get("skipped"):
            print(f"  {model.upper()}: 스킵 ({result.get('reason')})")
        elif result.get("error"):
            print(f"  {model.upper()}: 오류 ({result['error'][:50]})")
        else:
            q = result.get("quality", {})
            s = result.get("speed", {})
            if model == "asr":
                print(f"  ASR     | WER: {q.get('avg_wer', 'N/A'):.1%} | RTF: {s.get('avg_rtf', 'N/A'):.3f} | 지연: {s.get('avg_ms', 'N/A'):.1f}ms")
            elif model == "nmt":
                bleu   = q.get("bleu", {}).get("avg_pct", "N/A")
                meteor = q.get("meteor", {}).get("avg_pct", "N/A")
                bert   = q.get("bertscore", {}).get("avg_f1_pct", "스킵")
                print(f"  NMT     | BLEU: {bleu:.1f}% | METEOR: {meteor:.1f}% | BERTScore: {bert if bert == '스킵' else f'{bert:.1f}%'} | "
                      f"처리량: {s.get('throughput_per_sec', 'N/A'):.1f}문장/초 | 지연: {s.get('avg_ms', 'N/A'):.1f}ms")
            elif model == "tts":
                print(f"  TTS     | RTF: {s.get('avg_rtf', 'N/A'):.3f} | 실시간: {'[OK]' if s.get('realtime_capable') else '[NO]'} | 지연: {s.get('avg_ms', 'N/A'):.1f}ms")
            elif model == "ocr":
                print(f"  OCR     | CER: {q.get('avg_cer', 'N/A'):.1%} | 처리량: {s.get('throughput_per_sec', 'N/A'):.1f}이미지/초 | 지연: {s.get('avg_ms', 'N/A'):.1f}ms")
            elif model == "pipeline":
                bert = q.get("nmt_bertscore_f1")
                bert_str = f"{bert:.1f}%" if bert else "스킵"
                print(f"  PIPELINE| ASR WER: {q.get('asr_wer', 'N/A'):.1%} | NMT BERTScore: {bert_str} | TTS RTF: {q.get('tts_avg_rtf', 'N/A'):.3f} | 전체: {s.get('pipeline_avg_ms', 'N/A'):.0f}ms")
            elif model == "ocr_nmt":
                bert = result.get("quality", {}).get("pipeline_bertscore_f1")
                bert_str = f"{bert:.1f}%" if bert else "스킵"
                print(f"  OCR+NMT | OCR CER: {q.get('ocr_cer', 'N/A'):.1%} | "
                      f"BLEU: {q.get('pipeline_bleu', 'N/A'):.1f}% | "
                      f"BERTScore: {bert_str} | "
                      f"파이프라인: {s.get('pipeline_avg_ms', 'N/A'):.1f}ms")

    for model, result in results["models"].items():
        if not result.get("skipped") and not result.get("error"):
            print_friendly_summary(model, result)


if __name__ == "__main__":
    main()
